"""Tenant isolation tests for injected-database inventory primitives."""

import asyncio
from dataclasses import dataclass
from functools import wraps

import pytest
from mongomock_motor import AsyncMongoMockClient

from tenant_inventory import TenantInventoryRepository, TenantInventoryScopeError


@dataclass(frozen=True)
class Context:
    tenant_id: str


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


@async_test
async def test_add_rejects_inventory_owned_by_another_tenant():
    database = AsyncMongoMockClient()["tenant_inventory"]
    repository = TenantInventoryRepository(Context("acme"), database)

    with pytest.raises(TenantInventoryScopeError, match="tenant_id"):
        await repository.add_item(
            {"_id": "other-1", "tenant_id": "other", "product_id": "sku-1", "status": "available"}
        )

    assert await database.inventory_items.count_documents({}) == 0


@async_test
async def test_available_items_only_returns_context_tenant_available_inventory():
    database = AsyncMongoMockClient()["tenant_inventory"]
    await database.inventory_items.insert_many(
        [
            {"_id": "acme-available", "tenant_id": "acme", "product_id": "sku-1", "status": "available"},
            {"_id": "acme-reserved", "tenant_id": "acme", "product_id": "sku-1", "status": "reserved"},
            {"_id": "other-available", "tenant_id": "other", "product_id": "sku-1", "status": "available"},
        ]
    )

    items = await TenantInventoryRepository(Context("acme"), database).available_items("sku-1")

    assert [item["_id"] for item in items] == ["acme-available"]


@async_test
async def test_reserve_only_claims_available_items_for_context_tenant():
    database = AsyncMongoMockClient()["tenant_inventory"]
    await database.inventory_items.insert_many(
        [
            {"_id": "acme-available", "tenant_id": "acme", "product_id": "sku-1", "status": "available"},
            {"_id": "acme-reserved", "tenant_id": "acme", "product_id": "sku-1", "status": "reserved"},
            {"_id": "other-available", "tenant_id": "other", "product_id": "sku-1", "status": "available"},
        ]
    )

    reserved = await TenantInventoryRepository(Context("acme"), database).reserve_items(
        "sku-1", quantity=1, reservation_id="order-1"
    )

    assert [item["_id"] for item in reserved] == ["acme-available"]
    updated_item = await database.inventory_items.find_one({"_id": "acme-available"})
    assert updated_item is not None
    assert updated_item["status"] == "reserved"
    assert updated_item["reservation_id"] == "order-1"
    assert updated_item["tenant_id"] == "acme"
    assert updated_item["product_id"] == "sku-1"
    assert "reserved_at" in updated_item
    assert (await database.inventory_items.find_one({"_id": "other-available"}))["status"] == "available"


@async_test
async def test_reserve_insufficient_stock_rolls_back_and_never_allocates_cross_tenant():
    database = AsyncMongoMockClient()["tenant_inventory"]
    await database.inventory_items.insert_many(
        [
            {"_id": "acme-1", "tenant_id": "acme", "product_id": "sku-1", "status": "available"},
            {"_id": "other-1", "tenant_id": "other", "product_id": "sku-1", "status": "available"},
            {"_id": "other-2", "tenant_id": "other", "product_id": "sku-1", "status": "available"},
        ]
    )

    repository = TenantInventoryRepository(Context("acme"), database)
    reserved = await repository.reserve_items("sku-1", quantity=2, reservation_id="order-fail")

    assert reserved == []
    acme_1 = await database.inventory_items.find_one({"_id": "acme-1"})
    assert acme_1 is not None
    assert acme_1["status"] == "available"
    assert acme_1.get("reservation_id") is None

    other_1 = await database.inventory_items.find_one({"_id": "other-1"})
    assert other_1 is not None
    assert other_1["status"] == "available"


@async_test
async def test_reservation_rejects_mismatched_explicit_tenant_id():
    database = AsyncMongoMockClient()["tenant_inventory"]
    repository = TenantInventoryRepository(Context("acme"), database)

    with pytest.raises(TenantInventoryScopeError, match="tenant_id"):
        await repository.reserve_items("sku-1", quantity=1, reservation_id="order-1", tenant_id="other")


@async_test
async def test_release_items_only_affects_context_tenant_reserved_inventory():
    database = AsyncMongoMockClient()["tenant_inventory"]
    await database.inventory_items.insert_many(
        [
            {"_id": "acme-reserved", "tenant_id": "acme", "product_id": "sku-1", "status": "reserved", "reservation_id": "order-1", "reserved_at": "2026-10-01T00:00:00Z"},
            {"_id": "other-reserved", "tenant_id": "other", "product_id": "sku-1", "status": "reserved", "reservation_id": "order-1", "reserved_at": "2026-10-01T00:00:00Z"},
        ]
    )

    released_count = await TenantInventoryRepository(Context("acme"), database).release_items("order-1")

    assert released_count == 1
    acme_item = await database.inventory_items.find_one({"_id": "acme-reserved"})
    assert acme_item is not None
    assert acme_item["status"] == "available"
    assert acme_item.get("reservation_id") is None
    assert acme_item.get("reserved_at") is None
    
    other_item = await database.inventory_items.find_one({"_id": "other-reserved"})
    assert other_item is not None
    assert other_item["status"] == "reserved"
    assert other_item["reservation_id"] == "order-1"


@async_test
async def test_available_items_respects_limit_parameter():
    database = AsyncMongoMockClient()["tenant_inventory"]
    await database.inventory_items.insert_many(
        [
            {"_id": f"acme-{i}", "tenant_id": "acme", "product_id": "sku-1", "status": "available"}
            for i in range(10)
        ]
    )

    items = await TenantInventoryRepository(Context("acme"), database).available_items("sku-1", limit=3)

    assert len(items) == 3


@async_test
async def test_add_item_tags_untagged_items_with_context_tenant_id():
    database = AsyncMongoMockClient()["tenant_inventory"]
    repository = TenantInventoryRepository(Context("acme"), database)

    result = await repository.add_item({"product_id": "sku-1", "status": "available"})

    assert result["tenant_id"] == "acme"
    assert result["product_id"] == "sku-1"
    assert result["status"] == "available"
    assert "_id" in result
    assert "created_at" in result
    
    stored_item = await database.inventory_items.find_one({"_id": result["_id"]})
    assert stored_item is not None
    assert stored_item["tenant_id"] == "acme"


@async_test
async def test_commit_items_only_commits_context_tenant_reserved_inventory():
    database = AsyncMongoMockClient()["tenant_inventory"]
    await database.inventory_items.insert_many(
        [
            {"_id": "acme-reserved", "tenant_id": "acme", "product_id": "sku-1", "status": "reserved", "reservation_id": "res-101"},
            {"_id": "other-reserved", "tenant_id": "other", "product_id": "sku-1", "status": "reserved", "reservation_id": "res-101"},
        ]
    )

    repository = TenantInventoryRepository(Context("acme"), database)
    committed = await repository.commit_items(
        reservation_id="res-101",
        order_id="ord-999",
        user_tid=12345,
        customer_id="cust-1",
    )

    assert committed == 1

    acme_doc = await database.inventory_items.find_one({"_id": "acme-reserved"})
    assert acme_doc is not None
    assert acme_doc["status"] == "sold"
    assert acme_doc["order_id"] == "ord-999"
    assert acme_doc["user_tid"] == 12345
    assert acme_doc["customer_id"] == "cust-1"
    assert acme_doc.get("reservation_id") is None
    assert "sold_at" in acme_doc

    other_doc = await database.inventory_items.find_one({"_id": "other-reserved"})
    assert other_doc is not None
    assert other_doc["status"] == "reserved"
    assert other_doc["reservation_id"] == "res-101"
    assert other_doc.get("order_id") is None
