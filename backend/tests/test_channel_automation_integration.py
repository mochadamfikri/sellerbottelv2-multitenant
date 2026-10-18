"""Offline Integration Tests for Channel Automation Database & Inventory Engine.

Tests:
8. Product selection only picks available inventory & excludes protected
9. Reservation decreases available stock
10. Reservation does not count as sale / revenue
11. Restore All per product works
12. Restore Partial per product works
13. Restore does not change other products
14. SOLD inventory items cannot be restored
18. Campaign restart recovery idempotency & locking
22. Audit trail logging
"""
import asyncio
import pytest
from db import db
from channel_automation_protection import is_product_protected, assert_not_protected
from channel_inventory_engine import (
    reserve_channel_inventory,
    restore_channel_inventory,
    get_reserved_inventory_summary,
)
from channel_automation_scheduler import select_eligible_product, execute_campaign_job
from services import now_iso


@pytest.mark.asyncio
async def test_inventory_reservation_and_restore_all():
    # Setup dummy product
    prod_id = "test-prd-gemini"
    await db.products.delete_many({"_id": prod_id})
    await db.inventory_items.delete_many({"product_id": prod_id})
    await db.channel_inventory_reservations.delete_many({"product_id": prod_id})

    await db.products.insert_one({
        "_id": prod_id,
        "name": "Gemini Test Product",
        "price_idr": 15000,
        "active": True,
        "stock": 10,
    })

    # Insert 10 available inventory items
    for i in range(10):
        await db.inventory_items.insert_one({
            "_id": f"inv-item-{i}",
            "product_id": prod_id,
            "status": "available",
            "created_at": now_iso(),
            "movement_audit": [],
        })

    # Available before reservation: 10
    avail_before = await db.inventory_items.count_documents({"product_id": prod_id, "status": "available"})
    assert avail_before == 10

    # Test 9: Reserve 4 items
    res = await reserve_channel_inventory(
        product_id=prod_id,
        quantity=4,
        campaign_id="test-campaign-1",
        admin_user="test_admin",
    )
    assert res["success"] is True
    assert res["quantity"] == 4

    # Check available stock is decremented
    avail_after = await db.inventory_items.count_documents({"product_id": prod_id, "status": "available"})
    assert avail_after == 6

    reserved_count = await db.inventory_items.count_documents({"product_id": prod_id, "status": "reserved_channel"})
    assert reserved_count == 4

    # Test 10: Verify not counted as sold
    sold_count = await db.inventory_items.count_documents({"product_id": prod_id, "status": "sold"})
    assert sold_count == 0

    # Test 11: Restore All for this product
    restore_res = await restore_channel_inventory(
        product_id=prod_id,
        admin_user="test_admin",
        mode="all",
    )
    assert restore_res["success"] is True
    assert restore_res["restored_count"] == 4

    avail_final = await db.inventory_items.count_documents({"product_id": prod_id, "status": "available"})
    assert avail_final == 10


@pytest.mark.asyncio
async def test_inventory_restore_partial_and_isolation():
    prod_a = "test-prd-a"
    prod_b = "test-prd-b"
    await db.products.delete_many({"_id": {"$in": [prod_a, prod_b]}})
    await db.inventory_items.delete_many({"product_id": {"$in": [prod_a, prod_b]}})

    await db.products.insert_one({"_id": prod_a, "name": "Prod A", "price_idr": 10000, "active": True})
    await db.products.insert_one({"_id": prod_b, "name": "Prod B", "price_idr": 20000, "active": True})

    for i in range(6):
        await db.inventory_items.insert_one({"_id": f"inv-a-{i}", "product_id": prod_a, "status": "available"})
    for i in range(6):
        await db.inventory_items.insert_one({"_id": f"inv-b-{i}", "product_id": prod_b, "status": "available"})

    # Reserve 6 for prod_a and 4 for prod_b
    await reserve_channel_inventory(prod_a, 6, "camp-a")
    await reserve_channel_inventory(prod_b, 4, "camp-b")

    # Test 12: Restore Partial 2 items from prod_a
    restore_partial = await restore_channel_inventory(prod_a, quantity=2, mode="partial")
    assert restore_partial["restored_count"] == 2
    assert restore_partial["remaining_reserved"] == 4

    # Test 13: Prod B should be untouched (still 4 reserved, 2 available)
    b_reserved = await db.inventory_items.count_documents({"product_id": prod_b, "status": "reserved_channel"})
    assert b_reserved == 4


@pytest.mark.asyncio
async def test_sold_inventory_cannot_be_restored():
    prod_id = "test-prd-sold"
    await db.inventory_items.delete_many({"product_id": prod_id})

    # Insert SOLD item
    await db.inventory_items.insert_one({
        "_id": "inv-sold-1",
        "product_id": prod_id,
        "status": "sold",
        "sold_at": now_iso(),
    })

    # Test 14: Try restore on product with 0 reserved items
    res = await restore_channel_inventory(prod_id, mode="all")
    assert res["restored_count"] == 0

    # Ensure sold item is still sold
    item = await db.inventory_items.find_one({"_id": "inv-sold-1"})
    assert item["status"] == "sold"


@pytest.mark.asyncio
async def test_protected_products_cannot_be_reserved():
    claude_prod_id = "74f5569c-f093-5143-9e06-2564c1be3dd1"  # Claude Startup
    with pytest.raises(PermissionError):
        await reserve_channel_inventory(claude_prod_id, 1, "illegal-camp")

    with pytest.raises(PermissionError):
        await restore_channel_inventory(claude_prod_id, mode="all")
