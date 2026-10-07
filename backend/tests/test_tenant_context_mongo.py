import asyncio
import inspect
from functools import wraps

from mongomock_motor import AsyncMongoMockClient

from fastapi import HTTPException
import pytest

from tenant_context import (
    configure_tenant_registry_resolver,
    get_tenant_context,
    resolve_tenant_context,
)


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


async def _resolve(result):
    return await result if inspect.isawaitable(result) else result


@async_test
async def test_resolve_tenant_context_reads_active_tenant_from_mongo_collection():
    client = AsyncMongoMockClient()
    platform_database = client["platform"]
    await platform_database.tenants.insert_one(
        {
            "slug": "acme-shop",
            "status": "active",
            "database_name": "acme_isolated",
            "name": "Acme Shop",
            "plan": "pro",
        }
    )

    context = await _resolve(
        resolve_tenant_context("acme-shop", platform_database.tenants, client)
    )

    assert context.tenant_id == "acme-shop"
    assert context.database.name == "acme_isolated"
    assert context.status == "active"
    assert context.metadata == {"name": "Acme Shop", "plan": "pro"}


class SyncRegistry:
    def __init__(self, tenant):
        self.tenant = tenant
        self.requested_slug = None

    def get_tenant(self, slug):
        self.requested_slug = slug
        return self.tenant


def test_resolve_tenant_context_reads_tenant_from_sync_registry():
    registry = SyncRegistry(
        {
            "slug": "acme-shop",
            "status": "active",
            "database_name": "acme_isolated",
            "name": "Acme Shop",
            "plan": "starter",
        }
    )
    database_client = {"acme_isolated": "isolated-db"}

    context = resolve_tenant_context("acme-shop", registry, database_client)

    assert registry.requested_slug == "acme-shop"
    assert context.database == "isolated-db"
    assert context.metadata == {"name": "Acme Shop", "plan": "starter"}


@async_test
async def test_resolve_tenant_context_rejects_inactive_mongo_tenant():
    client = AsyncMongoMockClient()
    platform_database = client["platform"]
    await platform_database.tenants.insert_one(
        {"slug": "paused", "status": "suspended"}
    )

    with pytest.raises(HTTPException) as exc_info:
        await _resolve(resolve_tenant_context("paused", platform_database.tenants, client))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Tenant is not active"


@async_test
async def test_get_tenant_context_uses_configured_persistent_registry():
    client = AsyncMongoMockClient()
    platform_database = client["platform"]
    await platform_database.tenants.insert_one(
        {"slug": "acme-shop", "status": "active", "name": "Acme Shop", "plan": "pro"}
    )
    configure_tenant_registry_resolver(platform_database.tenants, client)

    context = await get_tenant_context("acme-shop")

    assert context.tenant_id == "acme-shop"
    assert context.metadata == {"name": "Acme Shop", "plan": "pro"}
