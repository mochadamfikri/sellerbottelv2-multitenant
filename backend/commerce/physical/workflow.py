"""Manual shipment workflow with atomic event journal and repairable projection."""
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL
from pymongo.errors import DuplicateKeyError
from ..fulfillment_types import CommerceError, FulfillmentUnavailable, FulfillmentType
from ..fulfillment.router import current_repository, require_active_context, PAID_STATES
from .stock import PhysicalStock

TRANSITIONS = {"pending": {"packing", "cancelled", "failed"}, "packing": {"ready_to_ship", "cancelled", "failed"},
               "ready_to_ship": {"shipped", "cancelled", "failed"}, "shipped": {"delivered"},
               "delivered": set(), "cancelled": set(), "failed": set()}


async def project_shipment(repo, record):
    shipment = record.get("shipment_snapshot")
    if shipment:
        projected = {**shipment, "updated_at": record["updated_at"]}
        try:
            await repo.database.shipments.update_one({"fulfillment_id": record["_id"], **({"status": {"$ne": "delivered"}} if shipment["status"] == "shipped" else {})}, {"$set": projected}, upsert=True)
        except DuplicateKeyError:
            pass  # A newer state has already been projected; never regress it.


async def transition(order_id, fulfillment_id, status, *, carrier_name="", tracking_number=""):
    repo = current_repository()
    await require_active_context(repo)
    order = await repo.database.purchases.find_one({"_id": order_id})
    record = await repo.collection.find_one(repo.query(_id=fulfillment_id, order_id=order_id, type=FulfillmentType.PHYSICAL))
    if not order or not record:
        raise CommerceError("Physical fulfillment not found")
    if order.get("status") not in PAID_STATES:
        raise CommerceError("Paid order required for shipment")
    if record.get("execution_status") != "done":
        raise FulfillmentUnavailable("Fulfillment initialization in progress; retry")
    carrier_name, tracking_number = carrier_name.strip(), tracking_number.strip()
    if record["status"] == status:
        shipment = record.get("shipment_snapshot") or {}
        if status == "shipped" and (carrier_name != shipment.get("carrier_name") or tracking_number != shipment.get("tracking_number")):
            raise CommerceError("Shipment idempotency conflict")
        await repair_compensation(repo, order, record)
        await project_shipment(repo, record)
        await refresh_order(repo, order_id)
        return record
    if status not in TRANSITIONS.get(record["status"], set()):
        raise CommerceError("Invalid physical fulfillment transition")
    now = datetime.now(timezone.utc)
    updates = {"status": status, "updated_at": now}
    if status == "shipped":
        carrier_name, tracking_number = carrier_name.strip(), tracking_number.strip()
        if not carrier_name or not tracking_number or len(carrier_name) > 80 or len(tracking_number) > 100 or any(ord(c) < 32 for c in carrier_name + tracking_number):
            raise CommerceError("Carrier and tracking number required")
        updates["shipment_snapshot"] = {"_id": str(uuid5(NAMESPACE_URL, "shipment:" + record["_id"])), "order_id": order_id,
            "fulfillment_id": record["_id"], "carrier_name": carrier_name, "tracking_number": tracking_number,
            "status": "shipped", "shipped_at": now, "delivered_at": None, "created_at": now}
    elif status == "delivered":
        updates["shipment_snapshot"] = {**record["shipment_snapshot"], "status": "delivered", "delivered_at": now}
        updates["completed_at"] = now
    if status in {"cancelled", "failed"}:
        # Claim cancellation before reversing stock. Retrying this state repairs
        # compensation if the process/DB fails between these two operations.
        updates["stock_compensation_pending"] = True
    changed = await repo.collection.update_one(repo.query(_id=record["_id"], status=record["status"], execution_status={"$ne": "running"}), {"$set": updates})
    if not changed.modified_count:
        raise FulfillmentUnavailable("Physical state changed; retry")
    record = await repo.collection.find_one(repo.query(_id=record["_id"]))
    await repair_compensation(repo, order, record)
    await project_shipment(repo, record)
    await refresh_order(repo, order_id)
    return record


async def repair_compensation(repo, order, record):
    if record.get("stock_compensation_pending"):
        lines = [line for line in order["items"] if line["line_id"] in record["item_refs"]]
        await PhysicalStock(repo.database).release_order({"items": lines}, reverse_sale=True)
        await repo.collection.update_one(repo.query(_id=record["_id"]), {"$set": {"stock_compensation_pending": False}})


async def refresh_order(repo, order_id):
    records = await repo.list_order(order_id)
    if not records:
        return
    if all(r["status"] in {"delivered", "completed"} for r in records):
        await repo.database.purchases.update_one({"_id": order_id, "status": {"$in": ["paid", "physical_pending", "service_waiting"]}},
            {"$set": {"status": "delivered", "delivered_at": datetime.now(timezone.utc).isoformat()}})
