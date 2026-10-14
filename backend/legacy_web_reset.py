"""Legacy web password-reset requirement sidecars.

The migration keeps ``store_customers`` byte-for-byte compatible with the
source snapshot. Mandatory V3 reset state therefore lives in tenant-scoped
sidecars, not in the customer documents themselves.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
import hashlib
import hmac

from bson import BSON


REQUIREMENT_COLLECTION = "legacy_customer_reset_requirements"
STATE_COLLECTION = "customer_security_state"
MARKER_VERSION = 1


def now() -> datetime:
    return datetime.now(timezone.utc)


def requirement_id(customer_id: str) -> str:
    return f"legacy-web-reset:{customer_id}"


def password_hash_digest(password_hash: Any) -> str:
    return hashlib.sha256(str(password_hash or "").encode("utf-8")).hexdigest()


async def password_reset_required(database: Any, customer: Mapping[str, Any] | None) -> bool:
    """Return whether this customer must reset before any password verification."""
    if not customer:
        return False
    if customer.get("force_password_reset") is False or customer.get("v3_password_reset_at"):
        return False

    customer_id = str(customer.get("_id") or "")
    if not customer_id:
        return bool(customer.get("force_password_reset") is True or customer.get("legacy_web_account") is True)
    state = await database[STATE_COLLECTION].find_one(
        {"_id": requirement_id(customer_id)},
        {"reset_completed_at": 1, "pending_password_hash_digest": 1},
    )
    if state and state.get("reset_completed_at"):
        return False
    if state and hmac.compare_digest(
        state.get("pending_password_hash_digest", ""),
        password_hash_digest(customer.get("password_hash")),
    ):
        return False
    if customer.get("force_password_reset") is True or customer.get("legacy_web_account") is True:
        return True
    marker = await database[REQUIREMENT_COLLECTION].find_one(
        {"_id": requirement_id(customer_id), "required": True}, {"_id": 1}
    )
    return bool(marker)


async def begin_password_reset(database: Any, customer_id: str, password_hash: str) -> None:
    """Persist recovery metadata before changing the customer password."""
    marker_id = requirement_id(str(customer_id))
    await database[STATE_COLLECTION].update_one(
        {"_id": marker_id},
        {
            "$set": {
                "customer_id": str(customer_id),
                "reset_started_at": now(),
                "pending_password_hash_digest": password_hash_digest(password_hash),
                "marker_version": MARKER_VERSION,
            },
            "$setOnInsert": {"created_at": now()},
        },
        upsert=True,
    )


async def record_password_reset_completion(database: Any, customer_id: str) -> None:
    """Record one-way V3 completion without changing the immutable marker."""
    marker_id = requirement_id(str(customer_id))
    marker = await database[REQUIREMENT_COLLECTION].find_one({"_id": marker_id}, {"_id": 1})
    if not marker:
        return
    await database[STATE_COLLECTION].update_one(
        {"_id": marker_id},
        {
            "$set": {
                "customer_id": str(customer_id),
                "reset_completed_at": now(),
                "marker_version": MARKER_VERSION,
            },
            "$unset": {"pending_password_hash_digest": "", "reset_started_at": ""},
            "$setOnInsert": {"created_at": now()},
        },
        upsert=True,
    )


async def mark_legacy_web_customer_bindings(client: Any, migration_db_name: str) -> dict[str, int]:
    """Create immutable reset requirements from migration account bindings.

    Bindings are the authoritative migration provenance. This function never
    updates a customer document and only inserts a marker when it is absent.
    """
    migration_db = client[migration_db_name]
    bindings = await migration_db.account_tenant_bindings.find(
        {"source_collection": "store_customers"}
    ).to_list(None)
    created = existing = 0
    for binding in bindings:
        customer_id = str(BSON(binding["source_id_bson"]).decode()["_id"])
        tenant_db = client[binding["database_name"]]
        result = await tenant_db[REQUIREMENT_COLLECTION].update_one(
            {"_id": requirement_id(customer_id)},
            {
                "$setOnInsert": {
                    "customer_id": customer_id,
                    "tenant_id": binding["tenant_id"],
                    "required": True,
                    "marker_version": MARKER_VERSION,
                    "created_at": now(),
                    "source_collection": "store_customers",
                }
            },
            upsert=True,
        )
        if result.upserted_id is None:
            existing += 1
        else:
            created += 1
    return {"bindings": len(bindings), "created": created, "existing": existing}
