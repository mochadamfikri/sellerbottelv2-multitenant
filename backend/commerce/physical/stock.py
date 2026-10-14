"""Atomic variant journal and immutable ledger projection, compatible with standalone Mongo.

Counters and authoritative movement event are changed in ONE document CAS.
stock_movements is an idempotently repairable projection, never a pre-write promise.
"""
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL
from pymongo.errors import DuplicateKeyError
from ..fulfillment_types import CommerceError, FulfillmentUnavailable

TYPES = {"RECEIVE", "SALE", "RESERVATION", "RELEASE", "RETURN", "DAMAGE", "ADJUSTMENT"}


async def ensure_indexes(database):
    await database.physical_variants.create_index("sku", unique=True, name="physical_sku_unique")
    await database.physical_variants.create_index([("product_id", 1), ("active", 1)], name="physical_product_variants")
    await database.stock_movements.create_index([("variant_id", 1), ("created_at", 1)], name="physical_movement_history")
    await database.shipments.create_index("fulfillment_id", unique=True, name="physical_shipment_unique")


class PhysicalStock:
    def __init__(self, database):
        self.database = database

    async def project(self, variant):
        for event in variant.get("stock_events", []):
            try:
                await self.database.stock_movements.update_one({"_id": event["_id"]}, {"$setOnInsert": event}, upsert=True)
            except DuplicateKeyError:
                pass

    async def get(self, variant_id):
        variant = await self.database.physical_variants.find_one({"_id": variant_id})
        if variant is None:
            raise CommerceError("Variant not found")
        await self.project(variant)
        return variant

    async def move(self, variant_id, kind, quantity, *, reference_id, actor="system", reason=""):
        if kind not in TYPES or not reference_id:
            raise CommerceError("Invalid stock movement")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not quantity or abs(quantity) > 1000000000 or (kind != "ADJUSTMENT" and quantity < 0):
            raise CommerceError("Invalid stock quantity")
        event_id = str(uuid5(NAMESPACE_URL, f"physical:{self.database.name}:{variant_id}:{kind}:{reference_id}"))
        for _ in range(30):
            variant = await self.get(variant_id)
            prior = next((e for e in variant.get("stock_events", []) if e["_id"] == event_id), None)
            if prior:
                if prior["quantity"] != quantity:
                    raise CommerceError("Stock idempotency conflict")
                return prior
            if kind in {"RECEIVE", "DAMAGE", "ADJUSTMENT", "RESERVATION"} and len(variant.get("stock_events", [])) >= 3000:
                raise FulfillmentUnavailable("Stock journal capacity reached; archival required")
            on_hand, reserved = int(variant.get("on_hand", 0)), int(variant.get("reserved", 0))
            delta_hand = delta_reserved = 0
            if kind == "RESERVATION":
                if not variant.get("active", True):
                    raise CommerceError("Inactive variant")
                delta_reserved = quantity
            elif kind in {"SALE", "RELEASE", "RETURN"}:
                events = [e for e in variant.get("stock_events", []) if e["reference_id"] == reference_id]
                reservation = next((e for e in events if e["type"] == "RESERVATION"), None)
                sale = next((e for e in events if e["type"] == "SALE"), None)
                sold = sale is not None
                released = any(e["type"] == "RELEASE" for e in events)
                returned = any(e["type"] == "RETURN" for e in events)
                if kind in {"SALE", "RELEASE"} and (not reservation or reservation["quantity"] != quantity or sold or released):
                    raise CommerceError("Reservation unavailable")
                if kind == "RETURN" and (not sold or sale["quantity"] != quantity or returned):
                    raise CommerceError("Sale reversal unavailable")
                delta_reserved = -quantity if kind != "RETURN" else 0
                delta_hand = -quantity if kind == "SALE" else quantity if kind == "RETURN" else 0
            else:
                delta_hand = -quantity if kind == "DAMAGE" else quantity
            next_hand, next_reserved = on_hand + delta_hand, reserved + delta_reserved
            if min(next_hand, next_reserved, next_hand - next_reserved) < 0:
                raise CommerceError("Insufficient physical stock")
            event = {"_id": event_id, "variant_id": variant_id, "sku": variant["sku"], "type": kind,
                     "quantity": quantity, "delta_on_hand": delta_hand, "delta_reserved": delta_reserved,
                     "reference_type": "order_line" if kind in {"RESERVATION", "SALE", "RELEASE", "RETURN"} else "admin",
                     "reference_id": reference_id, "reason": str(reason)[:240], "actor": str(actor)[:80],
                     "created_at": datetime.now(timezone.utc)}
            result = await self.database.physical_variants.update_one({"_id": variant_id, "stock_version": variant.get("stock_version", 0), **({"active": True} if kind == "RESERVATION" else {})},
                {"$inc": {"stock_version": 1, "on_hand": delta_hand, "reserved": delta_reserved}, "$push": {"stock_events": event}})
            if result.modified_count:
                # Failure here is recoverable: retry projects the already committed
                # authoritative event, without changing counters a second time.
                await self.project(await self.database.physical_variants.find_one({"_id": variant_id}))
                return event
        raise FulfillmentUnavailable("Stock changed concurrently; retry")

    async def release_order(self, order, *, reverse_sale=False):
        for line in order.get("items", []):
            if not line.get("variant_id") or line.get("fulfillment_type") != "physical":
                continue
            variant = await self.get(line["variant_id"])
            events = [e for e in variant.get("stock_events", []) if e["reference_id"] == line["line_id"]]
            if not any(e["type"] == "RESERVATION" for e in events):
                continue
            if any(e["type"] == "SALE" for e in events):
                if reverse_sale:
                    await self.move(line["variant_id"], "RETURN", line["qty"], reference_id=line["line_id"], reason="Checkout compensation")
            else:
                await self.move(line["variant_id"], "RELEASE", line["qty"], reference_id=line["line_id"], reason="Checkout cancelled/expired")

    async def consume_order(self, order):
        for line in order.get("items", []):
            if line.get("fulfillment_type") == "physical":
                await self.move(line["variant_id"], "SALE", line["qty"], reference_id=line["line_id"])
