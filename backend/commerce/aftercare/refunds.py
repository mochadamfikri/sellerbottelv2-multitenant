from uuid import uuid5, NAMESPACE_URL
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from payments.models import now, money
from payments.orchestrator import payment_adapter
from payments.ledger import Ledger

async def request_refund(database, platform, tenant, payment_id, key, amount, return_id=None):
    amount = money(amount, positive=True)
    rid = str(uuid5(NAMESPACE_URL, f"refund:{database.name}:{tenant}:{payment_id}:{key}"))
    for _ in range(50):
        payment = await database.order_payments.find_one({"_id": payment_id, "tenant_id": tenant})
        if not payment or payment["status"] not in {"paid", "partially_refunded", "refunded"}:
            raise CommerceError("Paid tenant payment required")
        prior = next((r for r in payment["refunds"] if r["_id"] == rid), None)
        if prior:
            if prior["amount"] != amount or prior.get("return_id") != return_id:
                raise CommerceError("Refund idempotency conflict")
            await repair_refund(database, platform, payment, rid)
            return next(r for r in (await database.order_payments.find_one({"_id": payment_id}))["refunds"] if r["_id"] == rid)
        if return_id:
            returned = await database.return_requests.find_one({"_id": return_id, "tenant_id": tenant, "order_id": payment["order_id"], "status": {"$in": ["inspected", "resolved"]}, "stock_compensation_pending": False})
            if not returned:
                raise CommerceError("Inspected return required for return-linked refund")
        if amount + payment.get("refund_reserved", 0) + payment.get("refunded_amount", 0) > payment["amount"]:
            raise CommerceError("Refund total exceeds paid amount")
        adapter = await payment_adapter(database, platform, payment)
        refund = {"_id": rid, "amount": amount, "return_id": return_id, "status": "requested", "created_at": now()}
        changed = await database.order_payments.update_one({"_id": payment_id, "refund_reserved": payment.get("refund_reserved", 0), "refunded_amount": payment.get("refunded_amount", 0), "refunds._id": {"$ne": rid}}, {"$inc": {"refund_reserved": amount}, "$push": {"refunds": refund}})
        if changed.modified_count:
            break
    else:
        raise FulfillmentUnavailable("Refund changed concurrently; retry")
    # Platform intent exists before the first external call. If recording it
    # fails, no provider call occurs. A lost local result is repaired from this
    # independent receipt; unknown calls are not replayed.
    await platform.refund_operations.update_one({"_id": rid}, {"$setOnInsert": {"tenant_id": tenant, "tenant_database": database.name, "payment_id": payment_id, "amount": amount, "state": "intent", "created_at": now()}}, upsert=True)
    claimed = await platform.refund_operations.update_one({"_id": rid, "state": "intent"}, {"$set": {"state": "external_unknown"}})
    if not claimed.modified_count:
        raise FulfillmentUnavailable("Refund requires reconciliation")
    await database.order_payments.update_one({"_id": payment_id, "refunds._id": rid}, {"$set": {"refunds.$.status": "external_unknown"}})
    if not payment["capabilities"].get("refund_support"):
        result = {"status": "manual_refund_required"}
    else:
        try:
            result = await adapter.refund(payment, refund)
        except Exception:
            return {**refund, "status": "external_unknown", "reconciliation": "Verify provider outcome before any retry"}
    if result.get("status") not in {"succeeded", "manual_refund_required"} or (result["status"] == "succeeded" and not result.get("provider_refund_id")):
        return {**refund, "status": "external_unknown"}
    await platform.refund_operations.update_one({"_id": rid, "state": "external_unknown"}, {"$set": {"state": "confirmed" if result["status"] == "succeeded" else "manual_refund_required", "result": result, "confirmed_at": now()}})
    await repair_refund(database, platform, payment, rid)
    return next(r for r in (await database.order_payments.find_one({"_id": payment_id}))["refunds"] if r["_id"] == rid)

async def repair_refund(database, platform, payment, rid):
    operation = await platform.refund_operations.find_one({"_id": rid, "payment_id": payment["_id"], "tenant_id": payment["tenant_id"], "tenant_database": database.name})
    if not operation:
        # Crash before external call: an intent can be re-created but the UI
        # reports it for review, instead of silently issuing a new refund.
        return
    if operation["state"] == "manual_refund_required":
        await database.order_payments.update_one({"_id": payment["_id"], "refunds._id": rid}, {"$set": {"refunds.$.status": "manual_refund_required"}})
        return
    if operation["state"] not in {"confirmed", "applied"}:
        return
    for _ in range(50):
        current = await database.order_payments.find_one({"_id": payment["_id"], "tenant_id": payment["tenant_id"]})
        refund = next(r for r in current["refunds"] if r["_id"] == rid)
        if refund["status"] == "succeeded":
            break
        total = current["refunded_amount"] + refund["amount"]
        if total > current["amount"] or refund["amount"] != operation["amount"]:
            raise CommerceError("Refund receipt amount mismatch")
        changed = await database.order_payments.update_one({"_id": payment["_id"], "refunded_amount": current["refunded_amount"], "refunds": {"$elemMatch": {"_id": rid, "status": {"$ne": "succeeded"}}}}, {"$inc": {"refunded_amount": refund["amount"], "refund_reserved": -refund["amount"]}, "$set": {"status": "refunded" if total == current["amount"] else "partially_refunded", "refunds.$.status": "succeeded", "refunds.$.provider_refund_id": operation["result"]["provider_refund_id"], "refunds.$.completed_at": now()}})
        if changed.modified_count:
            break
    else:
        raise FulfillmentUnavailable("Refund changed concurrently; retry")
    await Ledger(database, payment["tenant_id"]).reverse(current, refund)
    await platform.refund_operations.update_one({"_id": rid}, {"$set": {"state": "applied"}})
