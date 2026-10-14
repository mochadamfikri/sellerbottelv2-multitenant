import hashlib
import json
from datetime import timedelta
from uuid import uuid4, uuid5, NAMESPACE_URL
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from commerce.fulfillment_types import CommerceError
from .models import now, money
from .orchestrator import payment_adapter, apply_event

def reference_hint(raw):
    # Untrusted reference is used only for lookup; no mutation before auth.
    try:
        value = json.loads(raw)
        reference = value.get("reference") or value.get("order_id") or value.get("data", {}).get("external_id")
        if not isinstance(reference, str) or not 1 <= len(reference) <= 255:
            raise ValueError
        return reference
    except Exception:
        raise CommerceError("Malformed webhook") from None

async def receive(platform, database_client, name, raw, signature):
    route = await platform.payment_routes.find_one({"provider": name, "provider_reference": reference_hint(raw)})
    if not route:
        raise CommerceError("Unknown payment route")
    # Registry validation prevents tampered routes/DB names from binding a
    # payment to an unrelated tenant. A suspended tenant's paid event is kept
    # durable, but fulfillment waits for reactivation.
    tenant = await platform.tenants.find_one({"_id": route["tenant_id"], "database_name": route["tenant_database"]})
    if not tenant:
        raise CommerceError("Payment tenant routing mismatch")
    database = database_client[route["tenant_database"]]
    payment = await database.order_payments.find_one({"_id": route["_id"], "tenant_id": route["tenant_id"], "order_id": route["order_id"], "provider": name, "provider_reference": route["provider_reference"]})
    if not payment:
        raise CommerceError("Payment route binding mismatch")
    adapter = await payment_adapter(database, platform, payment)
    event = adapter.verify_webhook(raw, signature)
    if not payment.get("provider_payment_id") and payment["status"] == "created" and isinstance(event.get("provider_payment_id"), str):
        if route.get("provider_payment_id") and route["provider_payment_id"] != event["provider_payment_id"]:
            raise CommerceError("Webhook provider ID conflict")
        # A signed confirmation can arrive before the create response. Bind
        # the ID without issuing another create; settlement separately fetches
        # a verified fee before crediting funds.
        if event.get("reference") != payment["provider_reference"] or money(event.get("amount")) != payment["amount"] or event.get("currency") != "IDR":
            raise CommerceError("Early webhook binding mismatch")
        bound = await platform.payment_routes.update_one({"_id": route["_id"], "$or": [{"provider_payment_id": {"$exists": False}}, {"provider_payment_id": event["provider_payment_id"]}]}, {"$set": {"provider_payment_id": event["provider_payment_id"]}})
        if not bound.matched_count:
            raise CommerceError("Webhook provider ID conflict")
        await database.order_payments.update_one({"_id": payment["_id"], "provider_payment_id": None}, {"$set": {"provider_payment_id": event["provider_payment_id"]}})
        payment = await database.order_payments.find_one({"_id": payment["_id"]})
    if event.get("reference") != payment["provider_reference"] or event.get("currency") != "IDR" or money(event.get("amount")) != payment["amount"] or not isinstance(event.get("event_id"), str) or not 1 <= len(event["event_id"]) <= 200 or event.get("provider_payment_id") != payment.get("provider_payment_id"):
        raise CommerceError("Webhook payment binding mismatch")
    eid = str(uuid5(NAMESPACE_URL, f"payment-event:{platform.name}:{route['_id']}:{event['event_id']}"))
    safe = {k: event[k] for k in ("event_id", "reference", "amount", "currency", "status", "provider_payment_id")}
    if event["status"] == "refund_succeeded":
        if payment["environment"] != "mock":
            raise CommerceError("Sandbox refund notifications require provider reconciliation")
        for key in ("refund_id", "refund_amount", "provider_refund_id"):
            if key not in event:
                raise CommerceError("Malformed refund notification")
            safe[key] = event[key]
    try:
        await platform.payment_events.update_one({"_id": eid}, {"$setOnInsert": {"route_id": route["_id"], "event_id": event["event_id"], "payload": safe, "received_at": now(), "state": "accepted"}}, upsert=True)
    except DuplicateKeyError:
        pass
    saved = await platform.payment_events.find_one({"_id": eid})
    if saved["payload"] != safe:
        raise CommerceError("Provider event ID conflict")
    if saved["state"] == "applied":
        return {"ok": True, "duplicate": True}
    await process_receipt(platform, database_client, saved)
    return {"ok": True, "duplicate": False}

async def process_receipt(platform, database_client, receipt):
    token = str(uuid4())
    claimed = await platform.payment_events.find_one_and_update({"_id": receipt["_id"], "$or": [{"state": "accepted"}, {"state": "processing", "lease_until": {"$lte": now()}}]}, {"$set": {"state": "processing", "claim_token": token, "lease_until": now() + timedelta(minutes=5)}}, return_document=ReturnDocument.AFTER)
    if not claimed:
        return  # Another durable handler owns this event; never replay its work.
    try:
        await _process_claim(platform, database_client, claimed)
    except Exception as error:
        await platform.payment_events.update_one({"_id": receipt["_id"], "claim_token": token}, {"$set": {"state": "accepted", "error_code": type(error).__name__}, "$unset": {"claim_token": "", "lease_until": ""}})
        raise


async def _process_claim(platform, database_client, receipt):
    from bot_tenant_scope import BotTenantScope, use_bot_tenant
    route = await platform.payment_routes.find_one({"_id": receipt["route_id"]})
    tenant = await platform.tenants.find_one({"_id": route["tenant_id"], "database_name": route["tenant_database"]})
    if not tenant or tenant.get("status") != "active":
        raise CommerceError("Tenant inactive; signed receipt retained for reconciliation")
    database = database_client[route["tenant_database"]]
    payment = await database.order_payments.find_one({"_id": route["_id"], "tenant_id": tenant["_id"]})
    if not payment:
        raise CommerceError("Reconciliation payment binding mismatch")
    scope = BotTenantScope(tenant_id=tenant["_id"], slug=tenant["slug"], database_name=database.name, db_handle=database)
    async with use_bot_tenant(scope):
        if receipt["payload"]["status"] == "refund_succeeded":
            from commerce.aftercare.refunds import repair_refund
            payload = receipt["payload"]
            refund = next((r for r in payment.get("refunds", []) if r["_id"] == payload["refund_id"]), None)
            operation = await platform.refund_operations.find_one({"_id": payload["refund_id"], "tenant_id": tenant["_id"], "tenant_database": database.name, "payment_id": payment["_id"]})
            if not refund or not operation or money(payload["refund_amount"]) != refund["amount"] or not isinstance(payload["provider_refund_id"], str) or not 1 <= len(payload["provider_refund_id"]) <= 200 or operation["state"] not in {"external_unknown", "confirmed", "applied"}:
                raise CommerceError("Refund notification binding mismatch")
            result = {"status": "succeeded", "provider_refund_id": payload["provider_refund_id"]}
            if operation.get("result") and operation["result"] != result:
                raise CommerceError("Refund provider result conflict")
            await platform.refund_operations.update_one({"_id": operation["_id"], "state": "external_unknown"}, {"$set": {"state": "confirmed", "result": result, "confirmed_at": now()}})
            await repair_refund(database, platform, payment, operation["_id"])
        else:
            await apply_event(database, platform, payment, receipt["payload"])
    await platform.payment_events.update_one({"_id": receipt["_id"], "claim_token": receipt["claim_token"]}, {"$set": {"state": "applied", "applied_at": now()}, "$unset": {"claim_token": "", "lease_until": ""}})
