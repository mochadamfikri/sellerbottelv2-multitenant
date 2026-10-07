#!/usr/bin/env python3
"""Development-only executor for the IDSE Stage 3 migration.

It defaults to a no-write plan.  A real migration requires both --apply and
--confirm-idse-stage3, and may only use the hard-coded local development Mongo
instance and the fixed IDSE source/target database names.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

MONGO_URI = "mongodb://127.0.0.1:27018"
SOURCE_DATABASE = "sellerbottel_dev"
TARGET_DATABASE = "sellerbottel_tenant_idse"
ALLOWED_ENVIRONMENTS = frozenset({"development", "test"})


class SafetyError(RuntimeError):
    """Raised before this executable can connect or write unsafely."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the development-only IDSE Stage 3 migration.")
    parser.add_argument("--dry-run", action="store_true", help="Plan only (the default).")
    parser.add_argument("--apply", action="store_true", help="Request real writes; requires confirmation.")
    parser.add_argument(
        "--confirm-idse-stage3",
        action="store_true",
        help="Confirm real writes for the IDSE Stage 3 migration.",
    )
    parser.add_argument("--resume", action="store_true", help="Allow applying to a non-empty target.")
    args = parser.parse_args(argv)
    # Dry-run is intentionally the default; --dry-run also wins over --apply.
    args.dry_run = bool(args.dry_run or not args.apply)
    return args


def validate_environment(environment: str | None) -> str:
    normalized = (environment or "").strip().lower()
    if normalized not in ALLOWED_ENVIRONMENTS:
        raise SafetyError("Stage 3 execution is allowed only in development or test; production is forbidden")
    return normalized


def validate_uri(uri: str) -> None:
    parsed = urlparse(uri)
    # Check the prohibited production-default port first, even if the host is
    # also invalid, so overrides to it cannot be obscured by another error.
    if parsed.port == 27017 or ":27017" in uri:
        raise SafetyError("MongoDB port 27017 is prohibited for Stage 3 execution")
    if (
        parsed.scheme != "mongodb"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port != 27018
    ):
        raise SafetyError("Stage 3 execution only permits local MongoDB port 27018")


def _development_uri() -> str:
    """Return the fixed runner URI after validating its code-level invariant."""
    validate_uri(MONGO_URI)
    return MONGO_URI


def should_execute_migration(*, apply: bool, confirm: bool) -> bool:
    return apply and confirm


def check_target_safety(collection_counts: Mapping[str, int], *, resume: bool) -> None:
    occupied = {name: count for name, count in collection_counts.items() if count > 0}
    if occupied and not resume:
        raise SafetyError("Target already contains safe business documents; pass --resume to continue")


def format_summary(report: Mapping[str, Any]) -> str:
    """Return count-only output; never serialize database documents or errors."""
    return (
        "migration summary: "
        f"mode={'dry-run' if report.get('dry_run', True) else 'apply'} "
        f"collections={len(report.get('collections', {}))} "
        f"planned={int(report.get('total_planned', 0))} "
        f"migrated={int(report.get('total_migrated', 0))} "
        f"skipped={int(report.get('total_skipped', 0))}"
    )


def format_reconciliation_summary(report: Mapping[str, Any]) -> str:
    return "reconciliation summary: " + ("passed" if report.get("passed") else "mismatch")


async def _await_result(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _safe_collection_counts(target: Any, collection_names: tuple[str, ...]) -> dict[str, int]:
    return {
        name: int(await _await_result(target[name].count_documents({})))
        for name in collection_names
    }


async def run_stage3(args: argparse.Namespace, *, environment: str | None = None) -> int:
    """Run the migration with async database handles; returns a process exit code."""
    env = validate_environment(environment or os.environ.get("ENVIRONMENT"))
    validate_uri(MONGO_URI)
    apply = should_execute_migration(apply=args.apply and not args.dry_run, confirm=args.confirm_idse_stage3)
    if args.apply and not args.dry_run and not apply:
        raise SafetyError("Real writes require both --apply and --confirm-idse-stage3")

    from motor.motor_asyncio import AsyncIOMotorClient
    from idse_stage3_migration import IDSEStage3Migration, SAFE_BUSINESS_COLLECTIONS, verify_reconciliation

    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
        source = client[SOURCE_DATABASE]
        target = client[TARGET_DATABASE]
        if apply:
            check_target_safety(
                await _safe_collection_counts(target, SAFE_BUSINESS_COLLECTIONS), resume=args.resume
            )

        migration = IDSEStage3Migration(
            source,
            target,
            tenant_id="idse",
            dry_run=not apply,
            environment=env,
            source_uri=MONGO_URI,
            target_uri=MONGO_URI,
        )
        # The migration library owns the operation.  Support its current sync
        # API and an async API when it is upgraded, without bypassing it.
        run_method = getattr(migration, "run_async", migration.run)
        report = await _await_result(run_method())
        print(format_summary(report))

        if apply:
            reconciliation_method = getattr(migration, "financial_reconciliation_async", migration.financial_reconciliation)
            reconciliation = await _await_result(reconciliation_method())
            print(format_reconciliation_summary(reconciliation))
            verify_reconciliation(reconciliation)
        return 0
    finally:
        client.close()


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return await run_stage3(args)
    except SafetyError as exc:
        print(f"safety error: {exc}")
        return 2
    except Exception:
        # Do not print database exception payloads, document values, or URIs.
        print("stage3 execution failed")
        return 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
