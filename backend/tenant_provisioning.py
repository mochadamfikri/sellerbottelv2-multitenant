"""Tenant database provisioning for database-per-tenant isolation."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from db import DEFAULT_SETTINGS
from tenant_db import tenant_database_name


ESSENTIAL_COLLECTIONS = (
    "settings",
    "_meta",
    "products",
    "inventory_items",
    "purchases",
    "deposits",
    "store_customers",
    "bot_users",
)


async def provision_tenant_database(tenant_id: str, database_client: Any) -> dict[str, Any]:
    """Initialize the isolated database and baseline schema for one tenant.

    The function is safe to retry: existing settings and metadata are preserved,
    while MongoDB index creation is idempotent for matching definitions.
    """
    database_name = tenant_database_name(tenant_id)
    database = database_client[database_name]

    settings = deepcopy(DEFAULT_SETTINGS)
    settings.update({"_id": "main", "tenant_id": tenant_id, "store_name": ""})
    await database.settings.update_one(
        {"_id": "main"}, {"$setOnInsert": settings}, upsert=True
    )
    await database["_meta"].update_one(
        {"_id": "schema"},
        {
            "$setOnInsert": {
                "schema_version": 1,
                "created_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )

    await database.products.create_index(
        [("tenant_id", 1), ("active", 1), ("created_at", -1)],
        name="active_created_at",
    )
    await database.inventory_items.create_index(
        [("tenant_id", 1), ("product_id", 1), ("status", 1)],
        name="product_status",
    )
    await database.inventory_items.create_index(
        [("tenant_id", 1), ("product_id", 1), ("fingerprint", 1)],
        unique=True,
        name="product_fingerprint_unique",
    )
    await database.purchases.create_index(
        "invoice_id", unique=True, sparse=True, name="invoice_id_unique"
    )
    await database.purchases.create_index(
        [("tenant_id", 1), ("user_tid", 1), ("created_at", -1)],
        name="user_created_at",
    )
    await database.purchases.create_index(
        [("tenant_id", 1), ("customer_id", 1), ("idempotency_key", 1)],
        unique=True,
        name="store_customer_idempotency_unique",
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )
    await database.deposits.create_index(
        "tx_hash",
        unique=True,
        partialFilterExpression={"tx_hash": {"$type": "string"}},
        name="tx_hash_unique",
    )
    await database.deposits.create_index(
        [("tenant_id", 1), ("user_tid", 1), ("created_at", -1)],
        name="user_created_at",
    )
    await database.deposits.create_index(
        [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)],
        name="customer_created_at",
    )
    await database.store_customers.create_index(
        "email", unique=True, name="email_unique"
    )
    await database.store_customers.create_index(
        "telegram_id",
        unique=True,
        partialFilterExpression={"telegram_id": {"$type": "number"}},
        name="telegram_id_unique",
    )
    await database.bot_users.create_index(
        "telegram_id", unique=True, name="telegram_id_unique"
    )

    return {
        "status": "success",
        "database_name": database_name,
        "collections_initialized": list(ESSENTIAL_COLLECTIONS),
    }
