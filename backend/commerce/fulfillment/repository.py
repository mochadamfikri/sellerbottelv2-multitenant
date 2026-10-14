"""Tenant-local records and atomic claims; ambiguous sends are never replayed."""
from datetime import datetime, timedelta, timezone
from uuid import uuid5, uuid4, NAMESPACE_URL
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from ..fulfillment_types import CommerceError, FulfillmentUnavailable, FulfillmentType, STATES, initial_status


async def ensure_fulfillment_indexes(database):
    await database.fulfillments.create_index([("tenant_id", 1), ("order_id", 1), ("line_id", 1)], unique=True, name="fulfillment_order_line_unique")
    await database.fulfillments.create_index([("tenant_id", 1), ("execution_status", 1), ("lease_expires_at", 1)], name="fulfillment_recovery")


class FulfillmentRepository:
    def __init__(self, database, tenant_id, *, tenant_slug=None):
        if not tenant_id:
            raise CommerceError("Tenant fulfillment context required")
        self.database = database
        self.tenant_id = str(tenant_id)
        self.allowed_order_tenant_ids = {None, self.tenant_id}
        if tenant_slug:
            self.allowed_order_tenant_ids.add(str(tenant_slug))
        self.collection = database.fulfillments

    def query(self, **fields):
        return {**fields, "tenant_id": self.tenant_id}

    async def create(self, order, item):
        if order.get("tenant_id") not in self.allowed_order_tenant_ids:
            raise CommerceError("Tenant fulfillment context mismatch")
        now = datetime.now(timezone.utc)
        record = {"_id": str(uuid5(NAMESPACE_URL, f"sellerbottel:fulfillment:{self.tenant_id}:{order['_id']}:{item['line_id']}")),
                  "tenant_id": self.tenant_id, "order_id": order["_id"], "line_id": item["line_id"],
                  "type": item["fulfillment_type"], "status": initial_status(item["fulfillment_type"]),
                  "item_refs": [item["line_id"]], "attempts": 0, "execution_status": "ready",
                  "error_code": None, "error_detail_safe": None, "created_at": now, "updated_at": now, "completed_at": None}
        if order.get("status") in {"delivered", "completed"}:
            record["status"] = {FulfillmentType.SERVICE: "completed", FulfillmentType.DIGITAL_AUTO: "delivered"}.get(item["fulfillment_type"], "pending")
            record["execution_status"] = "done"
            record["completed_at"] = now
        try:
            await self.collection.update_one(self.query(order_id=order["_id"], line_id=item["line_id"]), {"$setOnInsert": record}, upsert=True)
        except DuplicateKeyError:
            pass  # A concurrent identical upsert won; read and validate below.
        saved = await self.collection.find_one(self.query(order_id=order["_id"], line_id=item["line_id"]))
        if saved is None or saved["type"] != item["fulfillment_type"]:
            raise CommerceError("Fulfillment snapshot conflict")
        return saved

    async def claim(self, record):
        now = datetime.now(timezone.utc)
        return await self.collection.find_one_and_update(
            self.query(_id=record["_id"], execution_status="ready"),
            {"$set": {"execution_status": "running", "claim_token": str(uuid4()), "lease_expires_at": now + timedelta(minutes=5),
                      "updated_at": now, "status": "delivering" if record["type"] == FulfillmentType.DIGITAL_AUTO else record["status"]}, "$inc": {"attempts": 1}},
            return_document=ReturnDocument.AFTER)

    async def finish(self, claim, state, error_code=None):
        now = datetime.now(timezone.utc)
        failed = state in {"failed", "delivery_failed"}
        result = await self.collection.update_one(self.query(_id=claim["_id"], execution_status="running", claim_token=claim["claim_token"]),
            {"$set": {"status": state, "execution_status": "failed" if failed else "done", "updated_at": now,
                      "completed_at": now if state in {"delivered", "completed"} else None,
                      "error_code": error_code, "error_detail_safe": error_code}, "$unset": {"claim_token": "", "lease_expires_at": ""}})
        if result.modified_count != 1:
            raise FulfillmentUnavailable("Fulfillment completion requires reconciliation")

    async def list_order(self, order_id):
        return await self.collection.find(self.query(order_id=order_id)).sort("line_id", 1).to_list(None)

    async def transition(self, record_id, state):
        record = await self.collection.find_one(self.query(_id=record_id))
        if record is None:
            raise CommerceError("Fulfillment not found")
        if record.get("execution_status") == "running":
            raise FulfillmentUnavailable("Fulfillment is processing; retry")
        if record["status"] == state:
            return record
        if state not in STATES[FulfillmentType(record["type"])].get(record["status"], set()):
            raise CommerceError("Invalid fulfillment transition")
        changed = await self.collection.update_one(self.query(_id=record_id, status=record["status"], execution_status={"$ne": "running"}), {"$set": {"status": state, "updated_at": datetime.now(timezone.utc), "completed_at": datetime.now(timezone.utc) if state in {"delivered", "completed"} else None}})
        if changed.modified_count != 1:
            raise FulfillmentUnavailable("Fulfillment transition raced; retry")
        return await self.collection.find_one(self.query(_id=record_id))

    async def mark_ambiguous_claims(self, now=None):
        return await self.collection.update_many(self.query(execution_status="running", lease_expires_at={"$lte": now or datetime.now(timezone.utc)}),
            {"$set": {"execution_status": "ambiguous", "error_code": "DELIVERY_ACK_UNKNOWN", "error_detail_safe": "Manual reconciliation required"}})
