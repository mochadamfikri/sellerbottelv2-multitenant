"""Offline TDD coverage for global customer identities (Owner Decision 1B)."""
import asyncio

import pytest
from mongomock_motor import AsyncMongoMockClient


def run(coro):
    return asyncio.run(coro)


def test_creates_global_customer_by_email_and_associates_it_with_tenant():
    """A platform-owned email identity is created once and linked to a tenant."""
    from customer_identity_repository import find_or_create_customer_by_email

    database = AsyncMongoMockClient()["platform"]

    customer = run(find_or_create_customer_by_email(
        database,
        email="newuser@example.com",
        tenant_id="idse",
    ))

    assert customer["email"] == "newuser@example.com"
    assert customer["_id"] is not None
    assert run(database.store_customers.count_documents({"email": "newuser@example.com"})) == 1
    assert run(database.customer_tenant_associations.count_documents({
        "customer_id": customer["_id"],
        "tenant_id": "idse",
    })) == 1


def test_returns_existing_customer_without_creating_duplicate():
    """Finding an existing customer returns it without creating a duplicate record."""
    from customer_identity_repository import find_or_create_customer_by_email

    database = AsyncMongoMockClient()["platform"]

    first = run(find_or_create_customer_by_email(
        database,
        email="existing@example.com",
        tenant_id="idse",
    ))

    second = run(find_or_create_customer_by_email(
        database,
        email="existing@example.com",
        tenant_id="acme",
    ))

    assert second["_id"] == first["_id"]
    assert second["email"] == "existing@example.com"
    assert run(database.store_customers.count_documents({"email": "existing@example.com"})) == 1
    assert run(database.customer_tenant_associations.count_documents({
        "customer_id": first["_id"],
    })) == 2


def test_creates_global_customer_by_telegram_and_associates_it_with_tenant():
    """A Telegram identity is platform-owned and may be linked to a tenant."""
    from customer_identity_repository import find_or_create_customer_by_telegram

    database = AsyncMongoMockClient()["platform"]

    customer = run(find_or_create_customer_by_telegram(
        database,
        telegram_id=123456789,
        tenant_id="idse",
    ))

    assert customer["telegram_id"] == 123456789
    assert run(database.store_customers.count_documents({"telegram_id": 123456789})) == 1
    assert run(database.customer_tenant_associations.count_documents({
        "customer_id": customer["_id"],
        "tenant_id": "idse",
    })) == 1


def test_find_customer_by_email_returns_global_identity_or_none():
    """Lookup reads the platform identity without requiring a tenant association."""
    from customer_identity_repository import (
        find_customer_by_email,
        find_or_create_customer_by_email,
    )

    database = AsyncMongoMockClient()["platform"]
    created = run(find_or_create_customer_by_email(
        database,
        email="lookup@example.com",
        tenant_id="idse",
    ))

    found = run(find_customer_by_email(database, "lookup@example.com"))

    assert found["_id"] == created["_id"]
    assert run(find_customer_by_email(database, "missing@example.com")) is None


def test_find_customer_by_telegram_returns_global_identity_or_none():
    """Lookup reads a global Telegram identity without creating a record."""
    from customer_identity_repository import (
        find_customer_by_telegram,
        find_or_create_customer_by_telegram,
    )

    database = AsyncMongoMockClient()["platform"]
    created = run(find_or_create_customer_by_telegram(
        database,
        telegram_id=987654321,
        tenant_id="idse",
    ))

    found = run(find_customer_by_telegram(database, 987654321))

    assert found["_id"] == created["_id"]
    assert run(find_customer_by_telegram(database, 555555555)) is None


def test_attach_tenant_association_is_idempotent_and_contains_no_pii():
    """Tenant links carry only identifiers and cannot duplicate an existing link."""
    from customer_identity_repository import (
        attach_customer_to_tenant,
        find_or_create_customer_by_email,
    )

    database = AsyncMongoMockClient()["platform"]
    customer = run(find_or_create_customer_by_email(
        database,
        email="linked@example.com",
        tenant_id="idse",
    ))

    run(attach_customer_to_tenant(database, customer["_id"], "idse"))
    association = run(database.customer_tenant_associations.find_one({
        "customer_id": customer["_id"],
        "tenant_id": "idse",
    }))

    assert run(database.customer_tenant_associations.count_documents({
        "customer_id": customer["_id"],
        "tenant_id": "idse",
    })) == 1
    assert set(association) >= {"_id", "customer_id", "tenant_id", "created_at"}
    assert "email" not in association
    assert "telegram_id" not in association
    assert "password_hash" not in association


def test_attaches_multiple_tenants_to_one_identity_without_duplicating_pii():
    """One platform identity can be associated with multiple tenants."""
    from customer_identity_repository import find_or_create_customer_by_email

    database = AsyncMongoMockClient()["platform"]
    first = run(find_or_create_customer_by_email(
        database,
        email="shared@example.com",
        tenant_id="idse",
    ))
    second = run(find_or_create_customer_by_email(
        database,
        email="shared@example.com",
        tenant_id="acme",
    ))

    assert second["_id"] == first["_id"]
    assert run(database.store_customers.count_documents({"email": "shared@example.com"})) == 1
    assert run(database.customer_tenant_associations.count_documents({
        "customer_id": first["_id"],
    })) == 2
    assert run(database.customer_tenant_associations.count_documents({"email": {"$exists": True}})) == 0
    assert run(database.customer_tenant_associations.count_documents({"telegram_id": {"$exists": True}})) == 0


def test_normalizes_email_to_lowercase_for_uniqueness():
    """Email normalization ensures case-insensitive global uniqueness."""
    from customer_identity_repository import find_or_create_customer_by_email

    database = AsyncMongoMockClient()["platform"]

    first = run(find_or_create_customer_by_email(
        database,
        email="User@EXAMPLE.COM",
        tenant_id="idse",
    ))
    second = run(find_or_create_customer_by_email(
        database,
        email="user@example.com",
        tenant_id="acme",
    ))

    assert first["_id"] == second["_id"]
    assert first["email"] == "user@example.com"
    assert run(database.store_customers.count_documents({})) == 1


def test_list_customer_tenant_associations_returns_tenant_ids():
    """List all tenant IDs associated with a customer."""
    from customer_identity_repository import (
        find_or_create_customer_by_email,
        list_customer_tenant_associations,
    )

    database = AsyncMongoMockClient()["platform"]
    customer = run(find_or_create_customer_by_email(
        database,
        email="multi-tenant@example.com",
        tenant_id="idse",
    ))
    run(find_or_create_customer_by_email(
        database,
        email="multi-tenant@example.com",
        tenant_id="acme",
    ))
    run(find_or_create_customer_by_email(
        database,
        email="multi-tenant@example.com",
        tenant_id="beta",
    ))

    tenant_ids = run(list_customer_tenant_associations(database, customer["_id"]))

    assert len(tenant_ids) == 3
    assert set(tenant_ids) == {"idse", "acme", "beta"}


def test_rejects_invalid_tenant_id():
    """Tenant ID must be a valid slug according to platform rules."""
    from customer_identity_repository import find_or_create_customer_by_email

    database = AsyncMongoMockClient()["platform"]

    with pytest.raises(ValueError, match="tenant ID"):
        run(find_or_create_customer_by_email(
            database,
            email="user@example.com",
            tenant_id="invalid__tenant",
        ))


def test_rejects_invalid_telegram_id():
    """Telegram ID must be a positive integer."""
    from customer_identity_repository import find_or_create_customer_by_telegram

    database = AsyncMongoMockClient()["platform"]

    with pytest.raises(ValueError, match="telegram_id must be a positive integer"):
        run(find_or_create_customer_by_telegram(
            database,
            telegram_id=-1,
            tenant_id="idse",
        ))

    with pytest.raises(ValueError, match="telegram_id must be a positive integer"):
        run(find_or_create_customer_by_telegram(
            database,
            telegram_id=0,
            tenant_id="idse",
        ))


def test_ensure_customer_identity_indexes_creates_required_indexes():
    """Ensure unique and lookup indexes on store_customers and customer_tenant_associations."""
    from customer_identity_repository import ensure_customer_identity_indexes

    database = AsyncMongoMockClient()["platform"]
    run(ensure_customer_identity_indexes(database))

    # In mongomock_motor, index_information() returns index specifications
    customer_indexes = run(database.store_customers.index_information())
    association_indexes = run(database.customer_tenant_associations.index_information())

    assert "email_unique" in customer_indexes or any(
        idx.get("key") == [("email", 1)] and idx.get("unique") for idx in customer_indexes.values()
    )
    assert any(
        idx.get("key") == [("customer_id", 1), ("tenant_id", 1)] and idx.get("unique")
        for idx in association_indexes.values()
    )

