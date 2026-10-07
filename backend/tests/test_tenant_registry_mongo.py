"""Offline tests for the MongoDB-backed tenant registry."""

import asyncio
from datetime import datetime, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from tenant_registry import MongoTenantRegistry


def run(coro):
    return asyncio.run(coro)


def registry() -> MongoTenantRegistry:
    return MongoTenantRegistry(
        environment={"DB_NAME": "platform_db"},
        client=AsyncMongoMockClient(),
    )


def test_create_tenant_persists_complete_schema_with_plan_metadata():
    async def check():
        tenants = registry()
        created = await tenants.create_tenant(
            slug="acme-shop",
            name="Acme Shop",
            plan="monthly",
            quotas={"products": 1000},
            metadata={"source": "referral"},
        )
        stored = await tenants.get_tenant("acme-shop")

        assert stored == created
        assert created["_id"]
        assert created["slug"] == "acme-shop"
        assert created["name"] == "Acme Shop"
        assert created["status"] == "provisioning"
        assert created["plan"] == "monthly"
        assert created["quotas"] == {"products": 1000}
        assert created["metadata"] == {"source": "referral"}
        assert created["database_name"] == "sellerbottel_tenant_acme_shop"
        assert isinstance(created["created_at"], datetime)
        assert created["created_at"].tzinfo == timezone.utc
        assert created["updated_at"] == created["created_at"]

    run(check())


def test_create_tenant_rejects_invalid_plan_and_duplicate_slug():
    async def check():
        tenants = registry()
        with pytest.raises(ValueError, match="plan"):
            await tenants.create_tenant("acme", "Acme", "enterprise")

        await tenants.create_tenant("acme", "Acme", "demo")
        with pytest.raises(ValueError, match="slug"):
            await tenants.create_tenant("acme", "Duplicate", "yearly")

    run(check())


def test_registry_lists_tenants_and_returns_none_for_unknown_slug():
    async def check():
        tenants = registry()
        await tenants.create_tenant("alpha", "Alpha", "demo")
        await tenants.create_tenant("beta", "Beta", "lifetime")

        assert await tenants.get_tenant("missing") is None
        assert [tenant["slug"] for tenant in await tenants.list_tenants()] == ["alpha", "beta"]

    run(check())


def test_update_status_supports_every_tenant_lifecycle_status():
    async def check():
        tenants = registry()
        created = await tenants.create_tenant("acme", "Acme", "monthly")

        for status in ("active", "suspended", "disabled", "failed", "provisioning"):
            updated = await tenants.update_status("acme", status)
            assert updated["status"] == status
            assert updated["updated_at"] >= created["updated_at"]

        with pytest.raises(ValueError, match="status"):
            await tenants.update_status("acme", "deleting")
        with pytest.raises(KeyError, match="slug"):
            await tenants.update_status("missing", "active")

    run(check())


def test_update_plan_quotas_and_metadata_replace_values_and_touch_timestamp():
    async def check():
        tenants = registry()
        created = await tenants.create_tenant("acme", "Acme", "demo")

        planned = await tenants.update_plan("acme", "yearly")
        quotaed = await tenants.set_quotas("acme", {"products": 500})
        updated = await tenants.set_metadata("acme", {"sales_rep": "jane"})

        assert planned["plan"] == "yearly"
        assert quotaed["quotas"] == {"products": 500}
        assert updated["metadata"] == {"sales_rep": "jane"}
        assert updated["updated_at"] >= created["updated_at"]
        with pytest.raises(ValueError, match="plan"):
            await tenants.update_plan("acme", "enterprise")
        with pytest.raises(KeyError, match="slug"):
            await tenants.set_quotas("missing", {})
        with pytest.raises(KeyError, match="slug"):
            await tenants.set_metadata("missing", {})

    run(check())


def test_registry_enforces_unique_slug_index():
    async def check():
        tenants = registry()
        await tenants.ensure_indexes()
        await tenants.create_tenant("unique", "Unique", "demo")

        with pytest.raises(Exception):
            await tenants.collection.insert_one({"slug": "unique"})

    run(check())
