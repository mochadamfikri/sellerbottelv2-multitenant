"""Phase 3A/3B: financial races, routing, credentials and durable repair."""
import asyncio
import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import AsyncMock
import httpx
import pytest
from cryptography.fernet import Fernet
from mongomock_motor import AsyncMongoMockClient
from commerce.fulfillment_types import CommerceError
from payments.models import now, money
from payments.ledger import Ledger, balances
from payments.credentials import save, load, test_connection as verify_connection
from payments.providers.base import MockProvider
from tests.test_public_tenant_management import management, seed
from tests.test_physical_commerce import ADDRESS

@pytest.fixture
def phase3(management, monkeypatch):
    registry, app = management
    monkeypatch.setenv("INVENTORY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PHASE3_MOCK_ENABLED", "true")
    monkeypatch.setattr("stock_monitor.schedule_stock_scan", lambda *args: None)
    import physical_routes, storefront_routes, payments.router, error_handlers
    from store_tenant_scope import install_store_scope
    app.include_router(physical_routes.router)
    app.include_router(storefront_routes.router)
    app.include_router(payments.router.owner)
    app.include_router(payments.router.hooks)
    install_store_scope(app)
    error_handlers.register_error_handlers(app)
    return registry, app

async def setup(phase3, slug="pay-a", mode="platform_settlement", name="kasera"):
    from db import client, platform_db
    from auth import hash_password
    from commerce.physical.models import VariantBody, create_variant
    from commerce.physical.stock import PhysicalStock
    tenant, headers = await seed(phase3[0], slug)
    database = client[tenant["database_name"]]
    platform = platform_db()
    cred = {"api_key": "mock_api_key", "webhook_secret": "mock_signature_key"} if name == "kasera" else {"server_key": "mock_server", "client_key": "mock_client", "webhook_secret": "mock_signature_key"}
    if mode == "platform_settlement":
        version = await save(platform, "platform-idse", "kasera", "mock", cred)
        caps = await (await load(platform, "platform-idse", version)).connect()
        await platform.platform_payment_settings.replace_one({"_id": "kasera"}, {"_id": "kasera", "credential_id": version, "capabilities": caps}, upsert=True)
    else:
        await save(database, tenant["_id"], name, "mock", cred)
        await verify_connection(database, tenant["_id"])
    await database.payment_settings.update_one({"_id": "main"}, {"$set": {"payment_mode": mode}}, upsert=True)
    await database.settings.update_one({"_id": "main"}, {"$set": {"manual_shipping_fee": 5000, "rate_mode": "manual", "manual_rate": 16000}}, upsert=True)
    await database.products.insert_one({"_id": "physical", "name": "Phase3 coat", "price_idr": 10000, "active": True, "fulfillment_type": "physical", "product_kind": "physical"})
    variant = await create_variant(database, "physical", VariantBody(sku="SAME-SKU", weight=300))
    await PhysicalStock(database).move(variant["_id"], "RECEIVE", 10, reference_id="opening-stock", reason="Opening")
    await database.store_customers.insert_one({"_id": "same-customer", "email": "phase3@example.com", "password_hash": hash_password("safe-test-password"), "balance_idr": 100000})
    return tenant, headers, database, variant

async def create(http, slug, variant, qty=2, key="checkout-stable-123", rate_id=None):
    login = await http.post(f"/api/store/t/{slug}/login", json={"email": "phase3@example.com", "password": "safe-test-password"})
    assert login.status_code == 200, login.text
    result = await http.post(f"/api/store/t/{slug}/checkout", json={"items": [{"pid": "physical", "variant_id": variant["_id"], "qty": qty}], "shipping_address": ADDRESS, "payment_method": "gateway:qris", "idempotency_key": key, "shipping_rate_id": rate_id})
    assert result.status_code == 200, result.text
    return result.json()

async def paid(http, order, *, event_id="paid-event", status="paid", signature=True):
    payment = order["payment"]
    event = {"event_id": event_id, "reference": payment["provider_reference"], "provider_payment_id": payment["provider_payment_id"], "amount": payment["amount"], "currency": "IDR", "status": status}
    raw = json.dumps(event).encode()
    sig = hmac.new(b"mock_signature_key", raw, hashlib.sha256).hexdigest() if signature else "bad"
    return await http.post("/api/commerce/webhooks/payments/" + payment["provider"], content=raw, headers={"x-mock-signature": sig})

@pytest.mark.parametrize("mode,name", [("platform_settlement", "kasera"), ("self_gateway", "kasera"), ("self_gateway", "midtrans")])
def test_payment_route_duplicate_and_financial_effects(phase3, mode, name):
    async def run():
        from db import platform_db
        tenant, headers, database, variant = await setup(phase3, mode=mode, name=name)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant)
            assert order["payment"]["amount"] == 25000
            assert (await paid(http, order, signature=False)).status_code == 422
            assert (await database.order_payments.find_one({"order_id": order["_id"]}))["status"] == "pending"
            responses = await asyncio.gather(*(paid(http, order) for _ in range(8)))
            assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
            payment = await database.order_payments.find_one({"order_id": order["_id"]})
            assert payment["status"] == "paid"
            assert await database.fulfillments.count_documents({"order_id": order["_id"]}) == 1
            variant = await database.physical_variants.find_one({"_id": variant["_id"]})
            assert variant["on_hand"] == 8 and variant["reserved"] == 0
            assert sum(e["type"] == "SALE" for e in variant["stock_events"]) == 1
            assert await platform_db().payment_events.count_documents({"route_id": payment["_id"]}) == 1
            account = await Ledger(database, tenant["_id"]).get()
            assert balances(account["events"])["pending"] == (25000 if mode == "platform_settlement" else 0)
            replay = await create(http, tenant["slug"], variant)
            assert replay["_id"] == order["_id"] and await database.order_payments.count_documents({}) == 1
            assert (await http.get(f"/api/store/t/{tenant['slug']}/orders/{order['_id']}/payment")).json()["status"] == "paid"
    asyncio.run(run())

def test_credential_binding_encryption_revoke_and_no_fallback(phase3):
    async def run():
        tenant, _, database, _ = await setup(phase3, mode="self_gateway")
        other, _, another, _ = await setup(phase3, "pay-b", "self_gateway")
        config = await database.payment_settings.find_one({"_id": "main"})
        doc = await database.gateway_credentials.find_one({"_id": config["credential_id"]})
        assert "mock_api_key" not in json.dumps(doc, default=str)
        await another.gateway_credentials.insert_one({**doc, "tenant_id": other["_id"]})
        with pytest.raises(CommerceError): await load(another, other["_id"], doc["_id"])
        await database.gateway_credentials.update_one({"_id": doc["_id"]}, {"$set": {"revoked": True}})
        with pytest.raises(CommerceError): await load(database, tenant["_id"], doc["_id"])
        assert (await load(database, tenant["_id"], doc["_id"], historical=True)).name == "kasera"
    asyncio.run(run())

@pytest.mark.parametrize("value", [True, -1, 0.5, "nan", "Infinity", "1.001"])
def test_exact_money_rejects_invalid(value):
    with pytest.raises(CommerceError): money(value)

def test_ledger_races_repair_and_liability(phase3):
    async def run():
        tenant, _, database, _ = await setup(phase3)
        ledger = Ledger(database, tenant["_id"])
        payment = {"_id": "payment", "order_id": "order", "payment_mode": "platform_settlement", "amount": 10000, "environment": "mock", "clearing_at": now() - timedelta(seconds=1), "available_at": now() - timedelta(seconds=1)}
        await asyncio.gather(*(ledger.credit(payment) for _ in range(12)))
        assert len((await ledger.get())["events"]) == 4
        await ledger.advance(payment, "clearing"); await ledger.advance(payment, "available")
        bank = {"_id": "bank", "verification_status": "mock_verified"}
        results = await asyncio.gather(*(ledger.request_payout(str(i), 8000, bank) for i in range(10)), return_exceptions=True)
        winners = [r for r in results if not isinstance(r, Exception)]
        assert len(winners) == 1
        key = winners[0][0]["payout_id"]
        for state in ("reviewing", "processing", "paid", "paid"): await ledger.payout_transition(key, state)
        refund = {"_id": "refund", "amount": 5000}
        await asyncio.gather(*(ledger.reverse(payment, refund) for _ in range(8)))
        values = balances((await ledger.get())["events"])
        assert values == {"pending": 0, "clearing": 0, "available": 0, "reserved": 0, "paid_out": 8000, "liability": 3000}
        await database.settlement_entries.delete_many({})
        await ledger.get()
        assert await database.settlement_entries.count_documents({}) == len((await ledger.get())["events"])
    asyncio.run(run())

def test_late_cancelled_payment_and_cross_tenant_access(phase3):
    async def run():
        tenant, ha, database, variant = await setup(phase3)
        other, hb, another, _ = await setup(phase3, "pay-b", "self_gateway")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant)
            assert (await http.post(f"/api/store/t/{tenant['slug']}/orders/{order['_id']}/cancel")).status_code == 200
            assert (await paid(http, order)).status_code == 200
            payment = await database.order_payments.find_one({"order_id": order["_id"]})
            assert payment["status"] == "cancelled" and payment["reconciliation"].startswith("late_paid")
            assert (await database.physical_variants.find_one({"_id": variant["_id"]}))["on_hand"] == 10
            assert balances((await Ledger(database, tenant["_id"]).get())["events"])["pending"] == 0
            path = "/api/public/tenant/full/commerce/transactions/" + payment["_id"] + "/refunds"
            assert (await http.post(path, headers=hb, json={"idempotency_key": "foreign-refund", "amount": 1000})).status_code == 422
            assert await another.order_payments.count_documents({}) == 0
    asyncio.run(run())

@pytest.mark.parametrize("failure", ["timeout", "malformed"])
def test_create_ambiguity_no_blind_retry(phase3, monkeypatch, failure):
    async def fail(*args):
        if failure == "timeout": raise TimeoutError("synthetic timeout")
        return {"status": "pending"}
    called = AsyncMock(side_effect=fail)
    monkeypatch.setattr(MockProvider, "create_payment", called)
    async def run():
        tenant, _, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant)
            assert order["payment"]["reconciliation"] == "create_unknown"
            await create(http, tenant["slug"], variant)
            assert called.await_count == 1
            assert (await database.physical_variants.find_one({"_id": variant["_id"]}))["reserved"] == 2
    asyncio.run(run())
