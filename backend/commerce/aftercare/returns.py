from uuid import uuid5, NAMESPACE_URL
from pymongo.errors import DuplicateKeyError
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from payments.models import now

TRANSITIONS = {"return_requested": {"reviewing", "cancelled"}, "reviewing": {"approved", "rejected", "cancelled"}, "approved": {"return_shipped", "received", "cancelled"}, "return_shipped": {"received"}, "received": {"inspected"}, "inspected": {"resolved"}}

async def request_return(database, tenant, customer, oid, key, lines, reason):
    if not reason.strip() or len(reason) > 500 or not lines or len(lines) > 50:
        raise CommerceError("Return item quantities and reason required")
    rid = str(uuid5(NAMESPACE_URL, f"return:{database.name}:{tenant}:{customer}:{oid}:{key}"))
    merged = {}
    for line in lines:
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 1000 or not isinstance(line.get("line_id"), str):
            raise CommerceError("Invalid return quantity")
        merged[line["line_id"]] = merged.get(line["line_id"], 0) + qty
    items = [{"line_id": k, "quantity": v} for k, v in sorted(merged.items())]
    for _ in range(30):
        order = await database.purchases.find_one({"_id": oid, "tenant_id": {"$in": [None, tenant]}, "customer_id": customer})
        if not order:
            raise CommerceError("Return order not found")
        prior = next((r for r in order.get("return_claims", []) if r["_id"] == rid), None)
        if prior:
            if prior["item_lines"] != items or prior["reason"] != reason:
                raise CommerceError("Return idempotency conflict")
            await project_request(database, prior)
            return await database.return_requests.find_one({"_id": rid})
        fulfillment_ids = []
        for entry in items:
            line = next((l for l in order["items"] if l["line_id"] == entry["line_id"] and l["fulfillment_type"] == "physical"), None)
            fulfilled = await database.fulfillments.find_one({"order_id": oid, "line_id": entry["line_id"], "tenant_id": tenant, "type": "physical", "status": "delivered"})
            if not line or not fulfilled:
                raise CommerceError("Only delivered physical items are eligible")
            active_claims = []
            for claim in order.get("return_claims", []):
                saved = await database.return_requests.find_one({"_id": claim["_id"], "tenant_id": tenant})
                if not saved or saved["status"] not in {"rejected", "cancelled"}:
                    active_claims.append(claim)
            used = sum(i["quantity"] for claim in active_claims for i in claim["item_lines"] if i["line_id"] == entry["line_id"])
            if entry["quantity"] + used > line["qty"]:
                raise CommerceError("Return quantity exceeds purchased quantity")
            fulfillment_ids.append(fulfilled["_id"])
        doc = {"_id": rid, "tenant_id": tenant, "customer_id": customer, "order_id": oid, "fulfillment_ids": fulfillment_ids, "item_lines": items, "reason": reason, "notes": "", "status": "return_requested", "requested_at": now(), "updated_at": now(), "history": [{"status": "return_requested", "at": now()}]}
        version = order.get("return_version", 0)
        query = {"_id": oid, **({"return_version": version} if "return_version" in order else {"return_version": {"$exists": False}})}
        changed = await database.purchases.update_one(query, {"$inc": {"return_version": 1}, "$push": {"return_claims": doc}})
        if changed.modified_count:
            await project_request(database, doc)
            return doc
    raise FulfillmentUnavailable("Return quantity changed; retry")

async def project_request(database, doc):
    try:
        await database.return_requests.update_one({"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
    except DuplicateKeyError:
        pass

async def transition(database, tenant, rid, status, resolution=None, notes=""):
    doc = await database.return_requests.find_one({"_id": rid, "tenant_id": tenant})
    if not doc:
        raise CommerceError("Return not found")
    if status == doc["status"]:
        if status in {"inspected", "resolved"} and resolution and resolution != doc.get("resolution"):
            raise CommerceError("Return resolution conflict")
        await repair_stock(database, doc)
        return await database.return_requests.find_one({"_id": rid})
    if status not in TRANSITIONS.get(doc["status"], set()):
        raise CommerceError("Invalid return transition")
    updates = {"status": status, "updated_at": now(), "notes": str(notes)[:500], status + "_at": now()}
    if status == "inspected":
        if resolution not in {"restock", "damaged"}:
            raise CommerceError("Inspection must select restock or damaged")
        updates.update({"resolution": resolution, "stock_compensation_pending": True})
    if status == "resolved":
        await repair_stock(database, doc)
        if (await database.return_requests.find_one({"_id": rid})).get("stock_compensation_pending"):
            raise CommerceError("Stock compensation incomplete")
    changed = await database.return_requests.update_one({"_id": rid, "tenant_id": tenant, "status": doc["status"]}, {"$set": updates, "$push": {"history": {"status": status, "resolution": resolution, "notes": str(notes)[:500], "at": now()}}})
    if not changed.modified_count:
        raise FulfillmentUnavailable("Return changed concurrently; retry")
    doc = await database.return_requests.find_one({"_id": rid})
    await repair_stock(database, doc)
    return await database.return_requests.find_one({"_id": rid})

async def repair_stock(database, doc):
    if not doc.get("stock_compensation_pending"):
        return
    from commerce.physical.stock import PhysicalStock
    order = await database.purchases.find_one({"_id": doc["order_id"], "tenant_id": {"$in": [None, doc["tenant_id"]]}})
    for entry in doc["item_lines"]:
        line = next(l for l in order["items"] if l["line_id"] == entry["line_id"])
        await PhysicalStock(database).return_quantity(line["variant_id"], entry["quantity"], sale_reference=line["line_id"], reference=doc["_id"] + ":" + line["line_id"], damaged=doc["resolution"] == "damaged")
    await database.return_requests.update_one({"_id": doc["_id"]}, {"$set": {"stock_compensation_pending": False}})


async def eligible_lines(database, tenant, order):
    eligible = []
    for line in order.get("items", []):
        record = await database.fulfillments.find_one({"order_id": order["_id"], "line_id": line["line_id"], "tenant_id": tenant, "type": "physical", "status": "delivered"})
        if not record:
            continue
        claims = await database.return_requests.find({"order_id": order["_id"], "tenant_id": tenant, "status": {"$nin": ["rejected", "cancelled"]}}).to_list(200)
        used = sum(i["quantity"] for claim in claims for i in claim["item_lines"] if i["line_id"] == line["line_id"])
        # Interrupted projections still reserve quantities in the order journal.
        for claim in order.get("return_claims", []):
            if not await database.return_requests.find_one({"_id": claim["_id"]}):
                used += sum(i["quantity"] for i in claim["item_lines"] if i["line_id"] == line["line_id"])
        if line["qty"] > used:
            eligible.append({"line_id": line["line_id"], "quantity": line["qty"] - used})
    return eligible
