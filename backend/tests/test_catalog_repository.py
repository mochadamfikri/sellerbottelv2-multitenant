"""Offline tests for the injected, tenant-scoped product catalog repository."""
import asyncio
from functools import wraps
from types import SimpleNamespace

import pytest
from mongomock_motor import AsyncMongoMockClient


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def test_catalog_repository_accepts_tenant_context():
    """Repository should be initialized with a TenantContext."""
    from catalog_repository import CatalogRepository
    
    context = SimpleNamespace(
        tenant_id="test-tenant",
        database={"products": []},
        status="active"
    )
    
    repo = CatalogRepository(context)
    
    assert repo.tenant_id == "test-tenant"
    assert repo.database == {"products": []}


def test_catalog_repository_requires_valid_tenant_id():
    """Repository rejects missing or invalid tenant_id."""
    from catalog_repository import CatalogRepository

    with pytest.raises(ValueError, match="tenant ID"):
        CatalogRepository(None)

    with pytest.raises(ValueError, match="tenant ID"):
        CatalogRepository({}, tenant_id="invalid/tenant")


@async_test
async def test_create_assigns_context_tenant_to_untagged_product():
    """Repository creates product, sets tenant_id and _id if missing."""
    from catalog_repository import CatalogRepository
    from mongomock_motor import AsyncMongoMockClient

    database = AsyncMongoMockClient()["tenant_catalog"]
    context_obj = SimpleNamespace(tenant_id="tenant-a", database=database, status="active")
    repo = CatalogRepository(context_obj)

    product = {"name": "Test Product", "price": 100}
    created = await repo.create_product(product)

    assert created["tenant_id"] == "tenant-a"
    assert "_id" in created
    assert created["name"] == "Test Product"
    stored = await database.products.find_one({"_id": created["_id"]})
    assert stored is not None
    assert stored["tenant_id"] == "tenant-a"


@async_test
async def test_get_and_list_are_strictly_scoped_to_context_tenant():
    """Cross-tenant products are never returned by get or list."""
    from catalog_repository import CatalogRepository
    from mongomock_motor import AsyncMongoMockClient

    database = AsyncMongoMockClient()["tenant_catalog"]
    await database.products.insert_many([
        {"_id": "tenant-a-product", "tenant_id": "tenant-a", "name": "A"},
        {"_id": "tenant-b-product", "tenant_id": "tenant-b", "name": "B"},
    ])
    repo = CatalogRepository(SimpleNamespace(tenant_id="tenant-a", database=database, status="active"))

    assert (await repo.get_product("tenant-a-product"))["name"] == "A"
    assert await repo.get_product("tenant-b-product") is None
    assert [product["_id"] for product in await repo.list_products()] == ["tenant-a-product"]


@async_test
async def test_update_and_delete_are_strictly_scoped_to_context_tenant():
    """Updates and deletes cannot affect another tenant's product."""
    from catalog_repository import CatalogRepository
    from mongomock_motor import AsyncMongoMockClient

    database = AsyncMongoMockClient()["tenant_catalog"]
    await database.products.insert_many([
        {"_id": "tenant-a-product", "tenant_id": "tenant-a", "name": "A"},
        {"_id": "tenant-b-product", "tenant_id": "tenant-b", "name": "B"},
    ])
    repo = CatalogRepository(SimpleNamespace(tenant_id="tenant-a", database=database, status="active"))

    assert (await repo.update_product("tenant-a-product", {"name": "Updated"}))["name"] == "Updated"
    assert await repo.update_product("tenant-b-product", {"name": "Hijacked"}) is None
    assert await repo.delete_product("tenant-b-product") is False
    assert await repo.delete_product("tenant-a-product") is True
    assert (await database.products.find_one({"_id": "tenant-b-product"}))["name"] == "B"


@async_test
async def test_update_rejects_mismatched_tenant_id():
    """An update cannot change product ownership."""
    from catalog_repository import CatalogRepository
    from mongomock_motor import AsyncMongoMockClient

    database = AsyncMongoMockClient()["tenant_catalog"]
    await database.products.insert_one({"_id": "tenant-a-product", "tenant_id": "tenant-a", "name": "A"})
    repo = CatalogRepository(SimpleNamespace(tenant_id="tenant-a", database=database, status="active"))

    with pytest.raises(ValueError, match="tenant_id"):
        await repo.update_product("tenant-a-product", {"tenant_id": "tenant-b"})

    assert (await database.products.find_one({"_id": "tenant-a-product"}))["tenant_id"] == "tenant-a"


@async_test
async def test_list_products_filtering_sorting_and_pagination():
    """Repository supports filtering, sorting, and pagination strictly within tenant."""
    from catalog_repository import CatalogRepository
    from mongomock_motor import AsyncMongoMockClient

    database = AsyncMongoMockClient()["tenant_catalog"]
    await database.products.insert_many([
        {"_id": "p1", "tenant_id": "tenant-a", "category": "books", "price": 10, "active": True},
        {"_id": "p2", "tenant_id": "tenant-a", "category": "electronics", "price": 100, "active": True},
        {"_id": "p3", "tenant_id": "tenant-a", "category": "books", "price": 30, "active": False},
        {"_id": "p4", "tenant_id": "tenant-a", "category": "books", "price": 20, "active": True},
        {"_id": "p5", "tenant_id": "other-tenant", "category": "books", "price": 5, "active": True},
    ])
    repo = CatalogRepository(SimpleNamespace(tenant_id="tenant-a", database=database, status="active"))

    # Filter active books
    active_books = await repo.list_products(filter_query={"category": "books", "active": True}, sort=[("price", 1)])
    assert [p["_id"] for p in active_books] == ["p1", "p4"]

    # Pagination: limit=1, skip=1
    page = await repo.list_products(filter_query={"category": "books"}, sort=[("price", 1)], limit=1, skip=1)
    assert [p["_id"] for p in page] == ["p4"]

    # Filter query with mismatched tenant_id raises ValueError
    with pytest.raises(ValueError, match="Tenant scope mismatch"):
        await repo.list_products(filter_query={"tenant_id": "other-tenant"})



