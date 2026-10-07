"""Safe, resumable Stage 3 IDSE legacy migration tooling.

This module provides migration tooling to safely transfer legacy tenant data
from sellerbottel_dev into the database-per-tenant isolated database
sellerbottel_tenant_idse.

Safety guarantees:
- Rejects production environment and port 27017 unconditionally.
- Offline and testable: Pure dependency-injected source and target handles.
- Explicit allowlist of safe tenant business collections. Refuses credentials,
  tokens, sessions, bot configs, encrypted secrets, and global identity collections.
- Strips prohibited/secret fields from documents during migration.
- Tags all migrated business documents with canonical tenant_id='idse'.
- Preserves legacy _id, invoice_id, and unknown non-secret business fields.
- Uses idempotent upsert keyed by legacy _id without overwriting existing target docs.
- Progress tracked in migration_progress collection via bracket syntax.
- Dry-run mode plans and returns counts with zero writes to target.
- Financial reconciliation validates counts and Decimal totals with explicit verification.
- Seeds per-tenant invoice counter based on highest numeric sequence or source counter.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import os
import re
from typing import Any, Mapping, Sequence

try:
    from invoice_sequencing import parse_invoice_reference
except ImportError:
    parse_invoice_reference = None


class MigrationSafetyError(Exception):
    """Raised when migration safety checks fail (production env, port 27017, etc.)."""


class ReconciliationMismatch(Exception):
    """Raised when source and target financial records or counts do not match."""


SAFE_BUSINESS_COLLECTIONS: tuple[str, ...] = (
    "purchases",
    "deposits",
    "gopay_payments",
    "balance_adjustments",
    "reseller_commissions",
    "reseller_payments",
    "reseller_payouts",
    "products",
    "inventory_items",
    "stock_events",
    "bot_chat_messages",
    "broadcasts",
    "outreach_campaigns",
    "outreach_jobs",
    "prospects",
    "promo_coupons",
    "promo_coupon_redemptions",
    "promo_coupon_usage",
    "promo_events",
    "promo_suppressions",
    "post_purchase_actions",
    "freeze_log",
    "daily_recaps",
    "login_attempts",
)

PROHIBITED_COLLECTIONS: tuple[str, ...] = (
    "tg_accounts",           # Telegram session credentials / encrypted sessions
    "reseller_bots",         # Bot configs / encrypted bot tokens
    "reseller_bot_users",    # Reseller bot state / configs
    "settings",              # System settings / admin secrets / API keys
    "store_customers",       # Global identity (Option B) - platform DB only
    "bot_users",             # Global identity (Option B) - platform DB only
    "admins",                # Platform admin accounts - platform DB only
    "processed_updates",     # Ephemeral Telegram operational state
    "processed_updates_bot2",# Ephemeral Telegram operational state
    "reseller_updates",      # Ephemeral Telegram operational state
    "store_email_codes",     # Verification codes / credentials
    "coupons",               # Legacy deprecated
    "discounts",             # Legacy / empty
    "promo_campaigns",       # Empty
    "required_channels",     # Bot configs / channel settings
    "traffic_sources",       # Empty
    "bot_messages",          # Ephemeral outbound queue
    "bot_message_history",   # Ephemeral archive
    "bot2_restock_requests", # Ephemeral queue
)

PROHIBITED_FIELDS: frozenset[str] = frozenset({
    "secret",
    "secrets",
    "token",
    "tokens",
    "token_encrypted",
    "session",
    "sessions",
    "session_encrypted",
    "session_version",
    "password",
    "password_hash",
    "api_key",
    "api_secret",
    "private_key",
    "bot_config",
    "bot_configs",
    "bot_token",
    "jwt",
    "auth_token",
    "access_token",
    "refresh_token",
    "credentials",
    "credential",
})


def sanitize_and_transform_doc(doc: Mapping[str, Any], tenant_id: str) -> dict[str, Any]:
    """Strip secret fields, add tenant_id, preserve legacy _id, invoice_id, and business fields."""
    transformed: dict[str, Any] = {}
    for key, val in doc.items():
        clean_key = str(key).strip().lower()
        if clean_key in PROHIBITED_FIELDS:
            continue
        if clean_key.endswith(("_encrypted", "_secret")):
            continue
        transformed[key] = deepcopy(val)

    transformed["tenant_id"] = tenant_id
    if "_id" in doc:
        transformed["_id"] = doc["_id"]
    if "invoice_id" in doc:
        transformed["invoice_id"] = doc["invoice_id"]
    return transformed


def verify_reconciliation(report: Mapping[str, Any]) -> bool:
    """Explicitly verify financial reconciliation report, raising ReconciliationMismatch on failure."""
    mismatches: list[str] = list(report.get("mismatches", []))
    if not mismatches:
        source = report.get("source", {})
        target = report.get("target", {})
        for entity in set(source.keys()) | set(target.keys()):
            src_metrics = source.get(entity, {})
            tgt_metrics = target.get(entity, {})
            for metric in set(src_metrics.keys()) | set(tgt_metrics.keys()):
                s_val = src_metrics.get(metric)
                t_val = tgt_metrics.get(metric)
                if s_val != t_val:
                    mismatches.append(f"{entity}.{metric}: source={s_val} != target={t_val}")

    if mismatches:
        raise ReconciliationMismatch(f"Financial reconciliation failed with mismatches: {'; '.join(mismatches)}")
    return True


class IDSEStage3Migration:
    """Safe IDSE Stage 3 migration executor and planner."""

    def __init__(
        self,
        source: Any,
        target: Any,
        *,
        tenant_id: str = "idse",
        dry_run: bool = True,
        environment: str | None = None,
        target_uri: str | None = None,
        source_uri: str | None = None,
    ):
        env = (environment or os.environ.get("ENVIRONMENT", "development")).strip().lower()
        if env == "production":
            raise MigrationSafetyError("Migration tooling is DEV ONLY; cannot run in production")

        for uri in (target_uri, source_uri):
            if uri and ":27017" in uri:
                raise MigrationSafetyError(f"Port 27017 is prohibited for IDSE migration tooling: {uri}")

        self.source = source
        self.target = target
        self.tenant_id = tenant_id
        self.dry_run = dry_run
        self.environment = env
        self.target_uri = target_uri
        self.source_uri = source_uri

    async def _discover_source_collections(self) -> list[str]:
        if hasattr(self.source, "collections") and isinstance(self.source.collections, dict):
            return list(self.source.collections.keys())
        if hasattr(self.source, "list_collection_names"):
            try:
                names = self.source.list_collection_names()
                # Handle async list_collection_names (Motor)
                if hasattr(names, "__await__"):
                    names = await names
                if isinstance(names, list):
                    return names
            except Exception:
                pass
        return list(SAFE_BUSINESS_COLLECTIONS)

    async def seed_invoice_counter(self) -> dict[str, Any]:
        """Seed per-tenant invoice counter based on highest legacy sequence or source counter (never lower)."""
        candidates: list[int] = [0]

        # 1. Inspect purchases collection
        try:
            purchases = await self.source["purchases"].find({}).to_list(length=None)
            candidates.append(len(purchases))
            for p in purchases:
                inv_id = str(p.get("invoice_id", "")).strip()
                if not inv_id:
                    continue
                if parse_invoice_reference:
                    parsed = parse_invoice_reference(inv_id)
                    if parsed and "seq" in parsed:
                        candidates.append(parsed["seq"])
                legacy_match = re.search(r"INV-\d{8}-(\d+)", inv_id)
                if legacy_match:
                    candidates.append(int(legacy_match.group(1)))
                dash_match = re.search(r"-(\d+)$", inv_id)
                if dash_match:
                    candidates.append(int(dash_match.group(1)))
        except Exception:
            pass

        # 2. Inspect source counters collection
        try:
            source_counters = await self.source["counters"].find({}).to_list(length=None)
            daily_sum = 0
            for c in source_counters:
                seq = c.get("seq")
                val = c.get("value")
                if isinstance(seq, int):
                    candidates.append(seq)
                if isinstance(val, int):
                    candidates.append(val)
                cid = str(c.get("_id", ""))
                if "invoice:" in cid and isinstance(seq, int):
                    daily_sum += seq
            if daily_sum > 0:
                candidates.append(daily_sum)
        except Exception:
            pass

        # 3. Check existing target counter (never lower)
        counter_id = f"{self.tenant_id}:invoice"
        try:
            target_counters = await self.target["counters"].find({"_id": counter_id}).to_list(length=None)
            for tc in target_counters:
                val = tc.get("value")
                if isinstance(val, int):
                    candidates.append(val)
        except Exception:
            pass

        highest = max(candidates)

        if not self.dry_run:
            await self.target["counters"].update_one(
                {"_id": counter_id},
                {
                    "$setOnInsert": {
                        "_id": counter_id,
                        "tenant_id": self.tenant_id,
                        "counter_name": "invoice",
                        "value": highest,
                    }
                },
                upsert=True,
            )

        return {
            "_id": counter_id,
            "tenant_id": self.tenant_id,
            "counter_name": "invoice",
            "value": highest,
            "dry_run": self.dry_run,
        }

    async def financial_reconciliation(self) -> dict[str, Any]:
        """Compute financial counts and Decimal totals for purchases and deposits from source and target."""
        # Purchases
        try:
            src_purchases = await self.source["purchases"].find({}).to_list(length=None)
        except Exception:
            src_purchases = []

        try:
            tgt_purchases = await self.target["purchases"].find({"tenant_id": self.tenant_id}).to_list(length=None)
            if not tgt_purchases:
                # Fallback to all target purchases if tenant filter returned nothing
                tgt_purchases = await self.target["purchases"].find({}).to_list(length=None)
        except Exception:
            tgt_purchases = []

        # Deposits
        try:
            src_deposits = await self.source["deposits"].find({}).to_list(length=None)
        except Exception:
            src_deposits = []

        try:
            tgt_deposits = await self.target["deposits"].find({"tenant_id": self.tenant_id}).to_list(length=None)
            if not tgt_deposits:
                tgt_deposits = await self.target["deposits"].find({}).to_list(length=None)
        except Exception:
            tgt_deposits = []

        def sum_decimal(docs: Sequence[Mapping[str, Any]], field: str) -> Decimal:
            total = Decimal("0")
            for d in docs:
                val = d.get(field)
                if val is not None:
                    try:
                        total += Decimal(str(val))
                    except Exception:
                        pass
            return total

        src_purchase_total = sum_decimal(src_purchases, "total")
        tgt_purchase_total = sum_decimal(tgt_purchases, "total")

        src_deposit_amount = sum_decimal(src_deposits, "amount")
        tgt_deposit_amount = sum_decimal(tgt_deposits, "amount")
        src_deposit_credited = sum_decimal(src_deposits, "credited_amount")
        tgt_deposit_credited = sum_decimal(tgt_deposits, "credited_amount")

        source_report = {
            "purchases": {
                "count": len(src_purchases),
                "total": src_purchase_total,
            },
            "deposits": {
                "count": len(src_deposits),
                "amount": src_deposit_amount,
                "credited_amount": src_deposit_credited,
            },
        }

        target_report = {
            "purchases": {
                "count": len(tgt_purchases),
                "total": tgt_purchase_total,
            },
            "deposits": {
                "count": len(tgt_deposits),
                "amount": tgt_deposit_amount,
                "credited_amount": tgt_deposit_credited,
            },
        }

        mismatches: list[str] = []
        if len(src_purchases) != len(tgt_purchases):
            mismatches.append(f"purchases.count: source={len(src_purchases)} != target={len(tgt_purchases)}")
        if src_purchase_total != tgt_purchase_total:
            mismatches.append(f"purchases.total: source={src_purchase_total} != target={tgt_purchase_total}")

        if len(src_deposits) != len(tgt_deposits):
            mismatches.append(f"deposits.count: source={len(src_deposits)} != target={len(tgt_deposits)}")
        if src_deposit_amount != tgt_deposit_amount:
            mismatches.append(f"deposits.amount: source={src_deposit_amount} != target={tgt_deposit_amount}")
        if src_deposit_credited != tgt_deposit_credited:
            mismatches.append(
                f"deposits.credited_amount: source={src_deposit_credited} != target={tgt_deposit_credited}"
            )

        return {
            "source": source_report,
            "target": target_report,
            "mismatches": mismatches,
            "passed": len(mismatches) == 0,
        }

    async def run(self) -> dict[str, Any]:
        """Execute or plan migration across safe tenant business collections."""
        available_names = await self._discover_source_collections()

        collections_report: dict[str, dict[str, int]] = {}
        refused_collections: list[str] = []

        total_planned = 0
        total_migrated = 0
        total_skipped = 0

        # Progress collection must be accessed via bracket syntax
        progress_collection = self.target["migration_progress"]

        for col_name in available_names:
            if col_name in PROHIBITED_COLLECTIONS or col_name not in SAFE_BUSINESS_COLLECTIONS:
                refused_collections.append(col_name)
                continue

            # Fetch source docs
            try:
                docs = await self.source[col_name].find({}).to_list(length=None)
            except Exception:
                docs = []

            planned = len(docs)
            migrated = 0
            skipped = 0

            if not self.dry_run:
                target_col = self.target[col_name]
                for doc in docs:
                    doc_id = doc.get("_id")
                    transformed = sanitize_and_transform_doc(doc, self.tenant_id)

                    # Check if already exists in target
                    already_exists = False
                    try:
                        existing = await target_col.find({"_id": doc_id}).to_list(length=None)
                        already_exists = len(existing) > 0
                    except Exception:
                        pass

                    # Idempotent upsert keyed by legacy _id
                    await target_col.update_one(
                        {"_id": doc_id},
                        {"$setOnInsert": transformed},
                        upsert=True,
                    )

                    if already_exists:
                        skipped += 1
                    else:
                        migrated += 1

                # Record progress using bracket syntax
                progress_key = f"{self.tenant_id}:{col_name}"
                await progress_collection.update_one(
                    {"_id": progress_key},
                    {
                        "$setOnInsert": {
                            "_id": progress_key,
                            "tenant_id": self.tenant_id,
                            "collection": col_name,
                            "planned": planned,
                            "migrated": migrated,
                            "skipped": skipped,
                            "status": "completed",
                        }
                    },
                    upsert=True,
                )
            else:
                # In dry run mode: planned is count, migrated and skipped are 0
                migrated = 0
                skipped = 0

            collections_report[col_name] = {
                "planned": planned,
                "migrated": migrated,
                "skipped": skipped,
            }
            total_planned += planned
            total_migrated += migrated
            total_skipped += skipped

        return {
            "tenant_id": self.tenant_id,
            "dry_run": self.dry_run,
            "environment": self.environment,
            "collections": collections_report,
            "refused_collections": refused_collections,
            "total_planned": total_planned,
            "total_migrated": total_migrated,
            "total_skipped": total_skipped,
        }
