import json
from candidate_readonly import assert_service_writable
import os
from uuid import uuid4
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from db import db, _resolve_db, platform_db, client
from physical_routes import owner_scope
from commerce.fulfillment_types import CommerceError
from . import credentials
from .providers.registry import SCHEMAS
from .models import now, money, public_payment
from .orchestrator import tenant_identity, resolve, checkout, payment_adapter, apply_event
from .ledger import Ledger, balances
from . import launch

owner = APIRouter(prefix="/api/public/tenant/full/commerce", tags=["phase3"], dependencies=[Depends(owner_scope)])
hooks = APIRouter(prefix="/api/commerce/webhooks", tags=["phase3-webhooks"])

class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payment_mode: str = Field(pattern="^(platform_settlement|self_gateway)$")
    provider: str = Field(default="kasera", pattern="^(kasera|midtrans)$")
    environment: str = Field(default="mock", pattern="^(mock|sandbox)$")
    credentials: dict[str, str] | None = None
    clearing_delay_seconds: int = Field(default=0, ge=0, le=2592000)
    available_delay_seconds: int = Field(default=0, ge=0, le=2592000)

async def settings_response():
    """Return the effective payment route for this tenant.

    A newly provisioned tenant has no local payment settings or credentials yet.
    It must still inherit the IDSE Kasera Live route, rather than falling back to
    a misleading mock configuration.
    """
    doc = await db.payment_settings.find_one({"_id": "main"}) or {
        "payment_mode": "platform_settlement",
        "provider": "kasera",
    }
    platform = None
    if doc.get("payment_mode", "platform_settlement") == "platform_settlement":
        platform = await platform_db().platform_payment_settings.find_one({"_id": "kasera"}) or {}
        doc = {**doc, "provider": "kasera", "environment": platform.get("environment") or "live"}
    credential = {} if platform is not None else await db.gateway_credentials.find_one({"_id": doc.get("credential_id")}) or {}
    result = {k: v for k, v in doc.items() if k != "secret"}
    result.update({"credential_schemas": SCHEMAS, "masked_fields": credential.get("masked_fields", {}), "revoked": credential.get("revoked", False), "webhook_url": "/api/commerce/webhooks/payments/" + doc.get("provider", "kasera")})
    if launch.enabled():
        result.update({"launch_profile": "v1_kasera", "credential_schemas": {"kasera": SCHEMAS["kasera"]}, "webhook_url": "/api/payments/webhooks/kasera"})
    if platform is not None:
        result["capabilities"] = platform.get("capabilities")
        result["platform_configured"] = bool(platform.get("credential_id") and platform.get("capabilities"))
    if launch.enabled():
        result["platform_fee"] = await launch.platform_fee(platform_db()) if doc.get("payment_mode") == "platform_settlement" else 0
        result["platform_fee_tiers"] = (await launch.platform_fee_policy(platform_db()))["tiers"] if doc.get("payment_mode") == "platform_settlement" else []
        if result.get("capabilities"):
            result["capabilities"] = {**result["capabilities"], "supported_methods": [m for m in result["capabilities"].get("supported_methods", []) if m == "qris"]}
    return result

@owner.get("/payment-settings")
async def get_settings():
    return await settings_response()

@owner.put("/payment-settings")
async def save_settings(body: SettingsBody):
    launch.require_provider(body.provider)
    tenant = tenant_identity(_resolve_db())
    if body.payment_mode == "platform_settlement" and (body.provider != "kasera" or body.credentials):
        raise CommerceError("Platform Kasera credentials are controlled by IDSE")
    if body.credentials:
        await credentials.save(_resolve_db(), tenant, body.provider, body.environment, body.credentials)
    previous = await db.payment_settings.find_one({"_id": "main"}) or {}
    values = body.model_dump(exclude={"credentials"})
    if not body.credentials and body.payment_mode == "self_gateway" and (previous.get("provider") != body.provider or previous.get("environment") != body.environment):
        values.update({"credential_id": None, "capabilities": None})
    await db.payment_settings.update_one({"_id": "main"}, {"$set": values}, upsert=True)
    return await settings_response()

@owner.post("/payment-settings/test")
async def test_connection():
    config = await db.payment_settings.find_one({"_id": "main"}) or {"payment_mode": "platform_settlement"}
    if config.get("payment_mode", "platform_settlement") == "platform_settlement":
        _, _, _, caps = await resolve(_resolve_db(), platform_db(), tenant_identity(_resolve_db()))
        return caps
    return await credentials.test_connection(_resolve_db(), tenant_identity(_resolve_db()))

@owner.post("/payment-settings/revoke")
async def revoke_credentials():
    doc = await db.payment_settings.find_one({"_id": "main"}) or {}
    await db.gateway_credentials.update_one({"_id": doc.get("credential_id"), "tenant_id": tenant_identity(_resolve_db())}, {"$set": {"revoked": True, "revoked_at": now()}})
    await db.payment_settings.update_one({"_id": "main"}, {"$set": {"capabilities": None}})
    return await settings_response()

@owner.get("/transactions")
async def transactions():
    return [public_payment(p) for p in await db.order_payments.find({"tenant_id": tenant_identity(_resolve_db())}).sort("created_at", -1).to_list(200)]

@owner.get("/settlement")
async def settlement():
    ledger = Ledger(_resolve_db(), tenant_identity(_resolve_db()))
    account = await ledger.get()
    # Encrypted bank snapshots are deliberately omitted from normal ledger reads.
    return {"balances": ledger.values(account), "archived_chunks": account.get("archive_generation", 0), "entries": [{k: v for k, v in e.items() if k != "bank_snapshot"} for e in account["events"]], "coverage": "No live payouts"}

class StageBody(BaseModel):
    stage: str = Field(pattern="^(clearing|available)$")

@owner.post("/settlement/{pid}/advance")
async def advance_settlement(pid: str, body: StageBody):
    payment = await db.order_payments.find_one({"_id": pid, "tenant_id": tenant_identity(_resolve_db()), "payment_mode": "platform_settlement", "status": {"$in": ["paid", "partially_refunded", "refunded"]}})
    if not payment:
        raise HTTPException(404, "Settlement payment not found")
    return await Ledger(_resolve_db(), payment["tenant_id"]).advance(payment, body.stage)

class BankBody(BaseModel):
    bank_name: str = Field(min_length=1, max_length=80)
    account_number: str = Field(min_length=5, max_length=40, pattern="^[0-9]+$")
    account_holder: str = Field(min_length=1, max_length=120)

@owner.put("/payout-bank")
async def bank_save(body: BankBody):
    if os.getenv("PHASE3_MOCK_ENABLED") != "true":
        raise CommerceError("Live bank verification/payout is disabled")
    tenant = tenant_identity(_resolve_db())
    key = str(uuid4())
    fields = body.model_dump()
    doc = {"_id": key, "tenant_id": tenant, "bank_name": body.bank_name, "account_holder": body.account_holder, "account_number_masked": "••••" + body.account_number[-4:], "verification_status": "mock_verified", "coverage": "MOCKED", "secret": credentials.seal(f"bank:{_resolve_db().name}:{tenant}:{key}", fields), "created_at": now()}
    await db.payout_banks.insert_one(doc)
    await db.payment_settings.update_one({"_id": "main"}, {"$set": {"bank_id": key}}, upsert=True)
    return {k: v for k, v in doc.items() if k != "secret"}

@owner.get("/payout-bank")
async def bank_get():
    settings = await db.payment_settings.find_one({"_id": "main"}) or {}
    doc = await db.payout_banks.find_one({"_id": settings.get("bank_id"), "tenant_id": tenant_identity(_resolve_db())}) or {}
    return {k: v for k, v in doc.items() if k != "secret"}

class PayoutBody(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=80, pattern="^[A-Za-z0-9_-]+$")
    amount: int = Field(strict=True, ge=1, le=10**12)

@owner.post("/payouts")
async def payout_request(body: PayoutBody):
    assert_service_writable("payments.payout_request")
    settings = await db.payment_settings.find_one({"_id": "main"}) or {}
    if settings.get("payment_mode") != "platform_settlement":
        raise CommerceError("Payout only applies to Settlement IDSE")
    bank = await db.payout_banks.find_one({"_id": settings.get("bank_id"), "tenant_id": tenant_identity(_resolve_db())})
    if not bank:
        raise CommerceError("Payout bank required")
    entries = await Ledger(_resolve_db(), tenant_identity(_resolve_db())).request_payout(body.idempotency_key, body.amount, bank)
    return [{k: v for k, v in entry.items() if k != "bank_snapshot"} for entry in entries]

class StateBody(BaseModel):
    status: str = Field(max_length=50)

@owner.post("/payouts/{key}/simulate")
async def payout_simulate(key: str, body: StateBody):
    if os.getenv("PHASE3_MOCK_ENABLED") != "true":
        raise CommerceError("Payout simulation disabled")
    return await Ledger(_resolve_db(), tenant_identity(_resolve_db())).payout_transition(key, body.status)

@owner.get("/shipping-settings")
async def shipping_settings():
    from shipping.service import config
    doc = await config(_resolve_db(), tenant_identity(_resolve_db()))
    return {k: v for k, v in doc.items() if k != "secret"}

class ShippingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = Field(pattern="^(manual_shipping|integrated_shipping|pickup_only)$")
    provider: str = "mock_courier"
    manual_shipping_fee: int = Field(strict=True, ge=0, le=10000000)
    origin: dict | None = None
    credentials: dict[str, str] | None = None

@owner.put("/shipping-settings")
async def shipping_save(body: ShippingSettings):
    from shipping.service import save_config
    return await save_config(_resolve_db(), tenant_identity(_resolve_db()), body.model_dump())

def public_shipment(doc):
    return {k: v for k, v in doc.items() if k not in {"credentials", "secret"}}

@owner.get("/shipments")
async def shipments():
    return [public_shipment(d) for d in await db.integrated_shipments.find({"tenant_id": tenant_identity(_resolve_db())}).sort("created_at", -1).to_list(200)]

@owner.post("/shipments/{oid}/{fid}")
async def shipment_create(oid: str, fid: str):
    from shipping.service import create_shipment
    return public_shipment(await create_shipment(_resolve_db(), platform_db(), tenant_identity(_resolve_db()), oid, fid))

@owner.get("/returns")
async def returns_list():
    return await db.return_requests.find({"tenant_id": tenant_identity(_resolve_db())}).sort("requested_at", -1).to_list(200)

class ReturnState(StateBody):
    resolution: str | None = None
    notes: str = Field(default="", max_length=500)

@owner.post("/returns/{rid}")
async def return_state(rid: str, body: ReturnState):
    from commerce.aftercare.returns import transition
    return await transition(_resolve_db(), tenant_identity(_resolve_db()), rid, body.status, body.resolution, body.notes)

class RefundBody(PayoutBody):
    return_id: str | None = None

@owner.post("/transactions/{pid}/refunds")
async def refund_request(pid: str, body: RefundBody):
    from commerce.aftercare.refunds import request_refund
    assert_service_writable("payments.refund_request")
    return await request_refund(_resolve_db(), platform_db(), tenant_identity(_resolve_db()), pid, body.idempotency_key, body.amount, body.return_id)

@owner.get("/refunds")
async def refunds_list():
    return [{**r, "payment_id": p["_id"], "order_id": p["order_id"]} for p in await db.order_payments.find({"tenant_id": tenant_identity(_resolve_db())}).to_list(200) for r in p.get("refunds", [])]

@owner.get("/reconciliation")
async def reconciliation():
    tenant = tenant_identity(_resolve_db())
    payments = await db.order_payments.find({"tenant_id": tenant, "reconciliation": {"$ne": None}}).to_list(200)
    refunds = await platform_db().refund_operations.find({"tenant_id": tenant, "state": {"$ne": "applied"}}).to_list(200)
    routes = await platform_db().payment_routes.find({"tenant_id": tenant}).to_list(200)
    events = await platform_db().payment_events.find({"route_id": {"$in": [r["_id"] for r in routes]}, "state": {"$ne": "applied"}}).to_list(200)
    shipments = await db.integrated_shipments.find({"tenant_id": tenant, "status": "create_unknown"}).to_list(200)
    preparing = await db.purchases.find({"tenant_id": tenant, "$or": [{"status": "preparing_payment"}, {"stock_release_pending": True}]}).to_list(200)
    return {"payments": [public_payment(p) for p in payments], "refunds": refunds, "events": [{k: v for k, v in event.items() if k != "claim_token"} for event in events], "shipments": [public_shipment(s) for s in shipments], "preparing_orders": [{"order_id": o["_id"], "status": o["status"], "stock_release_pending": o.get("stock_release_pending", False)} for o in preparing], "policy": "Replay trusted local receipts only; unknown external actions require provider verification"}

@owner.post("/reconciliation/repair")
async def reconcile_repair():
    from .webhook import process_receipt
    from .orchestrator import repair_paid
    from commerce.aftercare.refunds import repair_refund
    from commerce.aftercare.returns import project_request, repair_stock
    from shipping.service import project
    tenant = tenant_identity(_resolve_db())
    routes = await platform_db().payment_routes.find({"tenant_id": tenant}).to_list(200)
    for event in await platform_db().payment_events.find({"route_id": {"$in": [r["_id"] for r in routes]}, "state": {"$ne": "applied"}}).to_list(200):
        await process_receipt(platform_db(), client, event)
    for payment in await db.order_payments.find({"tenant_id": tenant}).to_list(200):
        if payment.get("reconciliation") == "create_unknown" and payment["status"] == "created":
            route = await platform_db().payment_routes.find_one({"_id": payment["_id"], "tenant_id": tenant, "tenant_database": _resolve_db().name})
            if route and route.get("provider_result"):
                await db.order_payments.update_one({"_id": payment["_id"], "status": "created"}, {"$set": {**route["provider_result"], "reconciliation": None}})
        if payment.get("reconciliation") == "cancel_unknown":
            receipt = await platform_db().cancel_operations.find_one({"_id": payment["_id"], "tenant_id": tenant, "tenant_database": _resolve_db().name, "state": "confirmed"})
            if receipt:
                await apply_event(_resolve_db(), platform_db(), payment, {"status": "cancelled", "event_id": "cancel:" + payment["_id"]})
        if payment.get("reconciliation") == "paid_effects_pending":
            await repair_paid(_resolve_db(), platform_db(), payment)
        for refund in payment.get("refunds", []):
            await repair_refund(_resolve_db(), platform_db(), payment, refund["_id"])
    for order in await db.purchases.find({"tenant_id": tenant}).to_list(200):
        for claim in order.get("return_claims", []):
            await project_request(_resolve_db(), claim)
        if order.get("stock_release_pending") and order.get("payment_scope") == "gateway":
            from .orchestrator import release_order
            await release_order(_resolve_db(), order)
        if order.get("status") == "preparing_payment":
            from datetime import datetime, timedelta
            created = datetime.fromisoformat(order["created_at"])
            if created < now() - timedelta(minutes=5) and not await platform_db().payment_routes.find_one({"_id": order["payment_id"]}):
                await db.purchases.update_one({"_id": order["_id"], "status": "preparing_payment"}, {"$set": {"status": "failed", "stock_release_pending": True}})
                from .orchestrator import release_order
                await release_order(_resolve_db(), order)
    for returned in await db.return_requests.find({"tenant_id": tenant, "stock_compensation_pending": True}).to_list(200):
        await repair_stock(_resolve_db(), returned)
    for shipment in await db.integrated_shipments.find({"tenant_id": tenant, "status": {"$in": ["created", "shipped", "delivered"]}}).to_list(200):
        await project(_resolve_db(), shipment)
    for shipment in await db.integrated_shipments.find({"tenant_id": tenant, "status": "create_unknown"}).to_list(200):
        receipt = await platform_db().shipping_routes.find_one({"_id": shipment["_id"], "tenant_id": tenant, "tenant_database": _resolve_db().name})
        if receipt and receipt.get("provider_result"):
            await db.integrated_shipments.update_one({"_id": shipment["_id"], "status": "create_unknown"}, {"$set": receipt["provider_result"]})
            await project(_resolve_db(), await db.integrated_shipments.find_one({"_id": shipment["_id"]}))
    await Ledger(_resolve_db(), tenant).get()
    return await reconciliation()

@hooks.post("/payments/{name}")
async def payment_webhook(name: str, request: Request):
    from .webhook import receive
    raw = await request.body()
    if len(raw) > 65536:
        raise HTTPException(413, "Webhook too large")
    signature = request.headers.get("kasera-signature-v1") or request.headers.get("x-mock-signature", "")
    return await receive(platform_db(), client, name, raw, signature)

@hooks.post("/shipping/mock_courier")
async def shipping_webhook(request: Request):
    from shipping.service import event
    raw = await request.body()
    if len(raw) > 65536:
        raise HTTPException(413, "Webhook too large")
    return await event(platform_db(), client, raw, request.headers.get("x-mock-signature", ""))
