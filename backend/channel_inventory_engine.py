"""Channel Automation Inventory Engine with explicit PROM status.

Status Lifecycle:
- AVAILABLE: Active and available for purchase on bot and website.
- PROM: Taken out of availability via Channel Automation; NOT a sale, NOT counted in revenue/profit.
- SOLD: Genuine customer transaction.

Flow:
AVAILABLE -> PROM -> AVAILABLE (on restore)
AVAILABLE -> SOLD (on genuine customer order)
"""
import logging
import uuid
from typing import Dict, Any, List, Optional
from db import db
from channel_automation_protection import assert_not_protected, is_product_protected
from services import now_iso

logger = logging.getLogger(__name__)


async def get_prom_inventory_summary() -> List[Dict[str, Any]]:
    """Returns list of products having PROM inventory."""
    pipeline = [
        {"$match": {"status": "PROM"}},
        {"$group": {"_id": "$product_id", "prom_count": {"$sum": 1}}},
    ]
    results = []
    async for doc in db.inventory_items.aggregate(pipeline):
        pid = doc["_id"]
        product = await db.products.find_one({"_id": pid}, {"name": 1, "sku": 1, "price_idr": 1})
        pname = product.get("name", "Unknown Product") if product else "Unknown Product"
        results.append({
            "product_id": pid,
            "product_name": pname,
            "sku": (product or {}).get("sku", ""),
            "prom_count": doc["prom_count"],
            "reserved_count": doc["prom_count"],  # backward compatibility for API
        })
    return results


async def reserve_channel_inventory(
    product_id: str,
    quantity: int,
    campaign_id: str,
    admin_user: str = "system",
    operation_type: str = "campaign_reservation",
    audit_reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Atomic inventory move: AVAILABLE -> PROM.
    
    Status becomes 'PROM'.
    Decrements AVAILABLE stock on bot and website.
    Does NOT register as a sale, revenue, or customer order.
    Protected products strictly asserted against.
    """
    assert_not_protected(product_id, "reserve_channel_inventory")
    quantity = int(quantity)
    if quantity <= 0:
        raise ValueError("Quantity must be greater than 0")

    product = await db.products.find_one({"_id": product_id})
    if not product:
        raise ValueError("Product not found")
    assert_not_protected(product, "reserve_channel_inventory")

    available_count = await db.inventory_items.count_documents({
        "product_id": product_id,
        "status": "available",
    })
    if available_count < quantity:
        raise ValueError(
            f"Insufficient available stock for PROM. Requested: {quantity}, Available: {available_count}"
        )

    reservation_id = str(uuid.uuid4())
    reserved_items = []

    for _ in range(quantity):
        item = await db.inventory_items.find_one_and_update(
            {
                "product_id": product_id,
                "status": "available",
            },
            {
                "$set": {
                    "status": "PROM",
                    "channel_reservation_id": reservation_id,
                    "channel_campaign_id": campaign_id,
                    "channel_reserved_at": now_iso(),
                },
                "$push": {
                    "movement_audit": {
                        "event_id": str(uuid.uuid4()),
                        "action": "moved_to_prom",
                        "quantity": -1,
                        "at": now_iso(),
                        "reference": reservation_id,
                    }
                },
            },
            sort=[("_id", 1)],
        )
        if not item:
            # Rollback partial moves
            await _rollback_channel_reservation(reservation_id)
            raise RuntimeError("Race condition detected during PROM move. Operation rolled back.")

        reserved_items.append(item["_id"])

    # Record receipt
    receipt = {
        "_id": reservation_id,
        "reservation_id": reservation_id,
        "product_id": product_id,
        "campaign_id": campaign_id,
        "quantity": quantity,
        "reserved_item_ids": reserved_items,
        "previous_status": "available",
        "current_status": "PROM",
        "reserved_at": now_iso(),
        "reserved_by": admin_user,
        "restored_at": None,
        "restored_by": None,
        "operation_type": operation_type,
        "audit_reference": audit_reference or reservation_id,
    }
    await db.channel_inventory_reservations.insert_one(receipt)

    # Sync product cached stock for bot & website
    from stock_monitor import schedule_stock_scan
    schedule_stock_scan(product_id)

    # Audit log
    await log_channel_action(
        action="inventory_moved_to_prom",
        actor=admin_user,
        details={
            "reservation_id": reservation_id,
            "product_id": product_id,
            "quantity": quantity,
            "campaign_id": campaign_id,
        },
    )

    return {
        "success": True,
        "reservation_id": reservation_id,
        "product_id": product_id,
        "quantity": quantity,
    }


async def _rollback_channel_reservation(reservation_id: str):
    """Rolls back an uncompleted PROM reservation."""
    await db.inventory_items.update_many(
        {"channel_reservation_id": reservation_id, "status": "PROM"},
        {
            "$set": {
                "status": "available",
                "channel_reservation_id": None,
                "channel_campaign_id": None,
                "channel_reserved_at": None,
            },
            "$push": {
                "movement_audit": {
                    "event_id": str(uuid.uuid4()),
                    "action": "prom_rollback",
                    "quantity": 1,
                    "at": now_iso(),
                    "reference": reservation_id,
                }
            },
        },
    )


async def restore_channel_inventory(
    product_id: str,
    quantity: Optional[int] = None,
    admin_user: str = "admin",
    mode: str = "all",  # "all" or "partial"
) -> Dict[str, Any]:
    """Restore PROM inventory back to AVAILABLE strictly per product.
    
    Rules:
    - Never restores SOLD or DELIVERED items.
    - Strictly per product_id; never affects other products.
    - Validates 0 < requested_quantity <= restorable_quantity.
    - Protected products are asserted against.
    """
    assert_not_protected(product_id, "restore_channel_inventory")

    restorable_count = await db.inventory_items.count_documents({
        "product_id": product_id,
        "status": "PROM",
    })

    if restorable_count == 0:
        return {
            "success": True,
            "restored_count": 0,
            "message": "No PROM items to restore for this product.",
        }

    if mode == "partial":
        if quantity is None or quantity <= 0:
            raise ValueError("Partial restore requires quantity > 0")
        if quantity > restorable_count:
            raise ValueError(
                f"Requested restore quantity ({quantity}) exceeds available PROM quantity ({restorable_count})"
            )
        restore_target = quantity
    else:  # mode == "all"
        restore_target = restorable_count

    # Fetch candidate items
    cursor = db.inventory_items.find(
        {"product_id": product_id, "status": "PROM"},
        {"_id": 1, "channel_reservation_id": 1},
    ).limit(restore_target)

    candidate_ids = [doc["_id"] async for doc in cursor]

    if not candidate_ids:
        return {"success": True, "restored_count": 0}

    restore_event_id = str(uuid.uuid4())
    res = await db.inventory_items.update_many(
        {"_id": {"$in": candidate_ids}, "status": "PROM"},
        {
            "$set": {
                "status": "available",
                "channel_reservation_id": None,
                "channel_campaign_id": None,
                "channel_reserved_at": None,
            },
            "$push": {
                "movement_audit": {
                    "event_id": restore_event_id,
                    "action": "prom_to_available",
                    "quantity": 1,
                    "at": now_iso(),
                    "reference": f"restored_by:{admin_user}",
                }
            },
        },
    )

    actual_restored = res.modified_count

    # Update reservations tracking records
    await db.channel_inventory_reservations.update_many(
        {"product_id": product_id, "current_status": "PROM"},
        {
            "$set": {
                "current_status": "restored",
                "restored_at": now_iso(),
                "restored_by": admin_user,
            }
        },
    )

    # Sync stock
    from stock_monitor import schedule_stock_scan
    schedule_stock_scan(product_id)

    # Log action
    await log_channel_action(
        action="inventory_restored_from_prom",
        actor=admin_user,
        details={
            "product_id": product_id,
            "mode": mode,
            "requested_quantity": quantity,
            "restored_count": actual_restored,
            "remaining_prom": restorable_count - actual_restored,
        },
    )

    return {
        "success": True,
        "restored_count": actual_restored,
        "remaining_reserved": restorable_count - actual_restored,
        "remaining_prom": restorable_count - actual_restored,
    }


async def log_channel_action(action: str, actor: str, details: Dict[str, Any]):
    """Persistent audit trail for Channel Automation."""
    try:
        await db.channel_automation_logs.insert_one({
            "_id": str(uuid.uuid4()),
            "action": action,
            "actor": actor,
            "details": details,
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.error(f"Failed to write channel automation log: {e}")
