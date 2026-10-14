"""Atomic variant journal and immutable ledger projection, compatible with standalone Mongo.

Counters and authoritative movement event are changed in ONE document CAS.
stock_movements is an idempotently repairable projection, never a pre-write promise.
"""
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL
from pymongo.errors import DuplicateKeyError
from commerce.journal import Journal, ensure_archive_indexes, project_events
from ..fulfillment_types import CommerceError, FulfillmentUnavailable

TYPES = {"RECEIVE", "SALE", "RESERVATION", "RELEASE", "RETURN", "DAMAGE", "ADJUSTMENT"}


async def ensure_indexes(database):
    await ensure_archive_indexes(database)
    await database.physical_variants.create_index("sku", unique=True, name="physical_sku_unique")
    await database.physical_variants.create_index([("product_id", 1), ("active", 1)], name="physical_product_variants")
    await database.stock_movements.create_index([("variant_id", 1), ("created_at", 1)], name="physical_movement_history")
    await database.shipments.create_index("fulfillment_id", unique=True, name="physical_shipment_unique")


class PhysicalStock:
    def __init__(self, database):
        self.database = database
        self.journal = Journal(database, "physical_variants", "stock_events", "stock_version", "stock_journal_archive")

    async def project(self, variant):
        await project_events(self.database.stock_movements, variant.get("stock_events", []))

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
            compacted = await self.journal.compact(variant, lambda e: {"on_hand": e.get("delta_on_hand",0), "reserved": e.get("delta_reserved",0)})
            if compacted is None: continue
            variant = compacted
            historical = await self.journal.relevant(variant, {"_id": event_id, "reference_id": reference_id, "sale_reference": reference_id})
            events_all = historical + variant.get("stock_events", [])
            prior = next((e for e in events_all if e["_id"] == event_id), None)
            if prior:
                if prior["quantity"] != quantity:
                    raise CommerceError("Stock idempotency conflict")
                return prior
            on_hand, reserved = int(variant.get("on_hand", 0)), int(variant.get("reserved", 0))
            delta_hand = delta_reserved = 0
            if kind == "RESERVATION":
                if not variant.get("active", True):
                    raise CommerceError("Inactive variant")
                delta_reserved = quantity
            elif kind in {"SALE", "RELEASE", "RETURN"}:
                events = [e for e in events_all if e["reference_id"] == reference_id]
                reservation = next((e for e in events if e["type"] == "RESERVATION"), None)
                sale = next((e for e in events if e["type"] == "SALE"), None)
                sold = sale is not None
                released = any(e["type"] == "RELEASE" for e in events)
                returned = any(e["type"] == "RETURN" and (e["reference_id"] == reference_id or e.get("sale_reference") == reference_id) for e in events_all)
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
            history = await self.journal.relevant(variant, {"reference_id": line["line_id"]})
            events = [e for e in history + variant.get("stock_events", []) if e["reference_id"] == line["line_id"]]
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

    async def return_quantity(self, variant_id, quantity, *, sale_reference, reference, damaged=False):
        """Partial return + damage bundle in ONE CAS: damaged goods never become
        temporarily available. Original SALE and C2 full reversals stay intact.
        """
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 1000000000:
            raise CommerceError("Invalid return quantity")
        event_id = str(uuid5(NAMESPACE_URL, f"partial-return:{self.database.name}:{variant_id}:{reference}"))
        for _ in range(30):
            variant = await self.get(variant_id)
            compacted = await self.journal.compact(variant, lambda e: {"on_hand": e.get("delta_on_hand",0), "reserved": e.get("delta_reserved",0)})
            if compacted is None: continue
            variant = compacted
            history = await self.journal.relevant(variant, {"_id": event_id, "reference_id": sale_reference, "sale_reference": sale_reference})
            events_all = history + variant.get("stock_events", [])
            prior = next((e for e in events_all if e["_id"] == event_id), None)
            if prior:
                if prior["quantity"] != quantity or prior.get("damaged") != damaged or prior["sale_reference"] != sale_reference:
                    raise CommerceError("Return stock idempotency conflict")
                return prior
            sale = next((e for e in events_all if e["type"] == "SALE" and e["reference_id"] == sale_reference), None)
            returned = sum(e["quantity"] for e in events_all if e["type"] == "RETURN" and (e.get("sale_reference") == sale_reference or e["reference_id"] == sale_reference))
            if not sale or quantity + returned > sale["quantity"]:
                raise CommerceError("Return exceeds consumed sale")
            event = {"_id": event_id, "variant_id": variant_id, "sku": variant["sku"], "type": "RETURN", "quantity": quantity, "delta_on_hand": quantity, "delta_reserved": 0, "reference_type": "return", "reference_id": reference, "sale_reference": sale_reference, "damaged": damaged, "actor": "tenant_owner", "reason": "Inspected physical return", "created_at": datetime.now(timezone.utc)}
            entries = [event]
            if damaged:
                entries.append({**event, "_id": event_id + ":damage", "type": "DAMAGE", "delta_on_hand": -quantity})
            changed = await self.database.physical_variants.update_one({"_id": variant_id, "stock_version": variant.get("stock_version", 0)}, {"$inc": {"stock_version": 1, "on_hand": 0 if damaged else quantity}, "$push": {"stock_events": {"$each": entries}}})
            if changed.modified_count:
                await self.project(await self.database.physical_variants.find_one({"_id": variant_id}))
                return event
        raise FulfillmentUnavailable("Stock changed concurrently; retry")
