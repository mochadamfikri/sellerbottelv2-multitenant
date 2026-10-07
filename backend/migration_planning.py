"""Pure migration planning and dry-run validation utilities for IDSE tenant.

Enforces:
- Global customer identity (store_customers / bot_users are global identity;
  referenced, not duplicated into tenant-specific records).
- Strict tenant-owned inventory tagged with tenant_id = 'idse'.
- Per-tenant invoice counter with legacy invoice preservation.
- Dry-run validation and reporting without DB connection or side effects.
"""

from __future__ import annotations

from typing import Any, Mapping

IDSE_TENANT_ID = "idse"


def validate_source_record(
    collection: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a single source record and determine how it maps to idse tenant."""
    if collection == "store_customers":
        return {
            "valid": True,
            "collection": "store_customers",
            "target_collection": "store_customers",
            "operation": "reference_global_identity",
            "identity_scope": "global",
            "tenant_id": None,
            "preserve_fields": ["_id", "email", "telegram_id"],
            "errors": [],
            "warnings": [],
        }

    if collection == "bot_users":
        return {
            "valid": True,
            "collection": "bot_users",
            "target_collection": "bot_users",
            "operation": "reference_global_identity",
            "identity_scope": "global",
            "tenant_id": None,
            "preserve_fields": ["_id", "telegram_id"],
            "errors": [],
            "warnings": [],
        }

    if collection == "inventory_items":
        product_id = record.get("product_id")
        if not product_id or not str(product_id).strip():
            return {
                "valid": False,
                "collection": "inventory_items",
                "target_collection": "inventory_items",
                "operation": "reject",
                "identity_scope": "tenant",
                "tenant_id": IDSE_TENANT_ID,
                "errors": ["inventory_items requires a non-empty product_id"],
                "warnings": [],
            }

        return {
            "valid": True,
            "collection": "inventory_items",
            "target_collection": "inventory_items",
            "operation": "copy_to_tenant",
            "identity_scope": "tenant",
            "tenant_id": IDSE_TENANT_ID,
            "set_fields": {"tenant_id": IDSE_TENANT_ID},
            "errors": [],
            "warnings": [],
        }

    if collection == "purchases":
        return {
            "valid": True,
            "collection": "purchases",
            "target_collection": "purchases",
            "operation": "copy_to_tenant",
            "identity_scope": "tenant",
            "tenant_id": IDSE_TENANT_ID,
            "set_fields": {
                "tenant_id": IDSE_TENANT_ID,
                "invoice_counter_scope": IDSE_TENANT_ID,
            },
            "preserve_fields": ["invoice_id"],
            "errors": [],
            "warnings": [],
        }

    return {
        "valid": False,
        "collection": collection,
        "target_collection": collection,
        "operation": "reject",
        "identity_scope": "unknown",
        "tenant_id": None,
        "errors": [f"Unsupported collection: {collection}"],
        "warnings": [],
    }


def build_dry_run_report(
    records_by_collection: Mapping[str, list[Mapping[str, Any]]],
    tenant_id: str = IDSE_TENANT_ID,
) -> dict[str, Any]:
    """Pure validation dry-run report for migrating source collections to a tenant."""
    total = 0
    valid_count = 0
    invalid_count = 0
    operations: dict[str, int] = {}
    invalid_records: list[dict[str, Any]] = []

    for collection, records in records_by_collection.items():
        for record in records:
            total += 1
            result = validate_source_record(collection, record)
            if result.get("valid"):
                valid_count += 1
                op = str(result.get("operation"))
                if op:
                    operations[op] = operations.get(op, 0) + 1
            else:
                invalid_count += 1
                invalid_records.append(
                    {
                        "collection": collection,
                        "record_id": record.get("_id"),
                        "errors": result.get("errors", []),
                    }
                )

    return {
        "dry_run": True,
        "tenant_id": tenant_id,
        "summary": {
            "total": total,
            "valid": valid_count,
            "invalid": invalid_count,
        },
        "operations": operations,
        "invalid_records": invalid_records,
    }
