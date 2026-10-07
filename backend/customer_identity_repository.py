"""Platform database repository for global customer identities.

Owner Decision 1B keeps customer PII in ``store_customers`` and records tenant
membership separately in ``customer_tenant_associations``.
"""
from datetime import datetime, timezone
from uuid import uuid4

from tenant_db import validate_tenant_id


def normalize_email(email: str) -> str:
    """Normalize email to lowercase and stripped whitespace."""
    if not isinstance(email, str):
        raise ValueError("Email must be a string")
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("Email cannot be empty")
    return normalized


def validate_telegram_id(telegram_id: int) -> int:
    """Validate telegram_id is a positive integer."""
    if not isinstance(telegram_id, int) or telegram_id <= 0:
        raise ValueError("telegram_id must be a positive integer")
    return telegram_id


async def find_customer_by_email(database, email: str):
    """Return the platform-wide customer matching ``email``, if any."""
    normalized = normalize_email(email)
    return await database.store_customers.find_one({"email": normalized})


async def find_customer_by_telegram(database, telegram_id: int):
    """Return the platform-wide customer matching ``telegram_id``, if any."""
    validated_id = validate_telegram_id(telegram_id)
    return await database.store_customers.find_one({"telegram_id": validated_id})


async def attach_customer_to_tenant(database, customer_id: str, tenant_id: str):
    """Idempotently create the PII-free association from customer to tenant."""
    validate_tenant_id(tenant_id)
    await database.customer_tenant_associations.update_one(
        {"customer_id": customer_id, "tenant_id": tenant_id},
        {
            "$setOnInsert": {
                "_id": str(uuid4()),
                "customer_id": customer_id,
                "tenant_id": tenant_id,
                "created_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


async def list_customer_tenant_associations(database, customer_id: str) -> list[str]:
    """Return list of tenant_ids associated with customer_id."""
    cursor = database.customer_tenant_associations.find(
        {"customer_id": customer_id},
        {"tenant_id": 1, "_id": 0},
    )
    docs = await cursor.to_list(length=1000)
    return [doc["tenant_id"] for doc in docs]


async def find_or_create_customer_by_email(database, *, email: str, tenant_id: str):
    """Find or create the platform-wide customer for ``email`` and link a tenant."""
    validate_tenant_id(tenant_id)
    normalized = normalize_email(email)
    customer = await find_customer_by_email(database, normalized)
    if customer is None:
        customer = {
            "_id": str(uuid4()),
            "email": normalized,
            "created_at": datetime.now(timezone.utc),
        }
        await database.store_customers.insert_one(customer)

    await attach_customer_to_tenant(database, customer["_id"], tenant_id)
    return customer


async def find_or_create_customer_by_telegram(database, *, telegram_id: int, tenant_id: str):
    """Find or create the platform-wide customer for ``telegram_id`` and link a tenant."""
    validate_tenant_id(tenant_id)
    validated_id = validate_telegram_id(telegram_id)
    customer = await find_customer_by_telegram(database, validated_id)
    if customer is None:
        customer = {
            "_id": str(uuid4()),
            "telegram_id": validated_id,
            "created_at": datetime.now(timezone.utc),
        }
        await database.store_customers.insert_one(customer)

    await attach_customer_to_tenant(database, customer["_id"], tenant_id)
    return customer


async def ensure_customer_identity_indexes(database):
    """Ensure platform indexes for global identities and tenant associations."""
    await database.store_customers.create_index(
        "email",
        unique=True,
        name="email_unique",
    )
    await database.store_customers.create_index(
        "telegram_id",
        unique=True,
        partialFilterExpression={"telegram_id": {"$type": "number"}},
        name="telegram_id_unique",
    )
    await database.customer_tenant_associations.create_index(
        [("customer_id", 1), ("tenant_id", 1)],
        unique=True,
        name="customer_tenant_unique",
    )
    await database.customer_tenant_associations.create_index(
        "customer_id",
        name="customer_id_lookup",
    )
    await database.customer_tenant_associations.create_index(
        "tenant_id",
        name="tenant_id_lookup",
    )

