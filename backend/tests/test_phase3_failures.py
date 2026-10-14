import asyncio
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock
import httpx
import pytest
from pymongo.errors import AutoReconnect
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from payments.ledger import Ledger
from shipping.providers import MockShipping
from tests.test_public_tenant_management import management
from tests.test_phase3_payments import phase3, setup, create, paid
from tests.test_phase3_post_purchase import ready, delivered, owner_action, BASE
from tests.test_physical_commerce import ADDRESS

def test_paid_webhook_local_outage_retains_receipt_and_recovers(phase3, monkeypatch):
    original = Ledger.project
    async def outage(self, account):
        if account["events"]:
            raise AutoReconnect("synthetic journal projection outage")
        return await original(self, account)
    async def run():
        from db import platform_db
        tenant, headers, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant)
            monkeypatch.setattr(Ledger, "project", outage)
            assert (await paid(http, order)).status_code == 503
            receipt = await platform_db().payment_events.find_one({})
            assert receipt["state"] == "accepted" and receipt["error_code"] == "AutoReconnect"
            p = await database.order_payments.find_one({"order_id": order["_id"]})
            assert p["status"] == "paid" and p["reconciliation"] == "paid_effects_pending"
            assert (await database.physical_variants.find_one({"_id": variant["_id"]}))["reserved"] == 2
            monkeypatch.setattr(Ledger, "project", original)
            await owner_action(http, headers, "/reconciliation/repair")
            assert (await paid(http, order)).status_code == 200
            assert sum(e["type"] == "PAYMENT_GROSS" for e in (await Ledger(database, tenant["_id"]).get())["events"]) == 1
            assert (await database.physical_variants.find_one({"_id": variant["_id"]}))["on_hand"] == 8
    asyncio.run(run())

def test_duplicate_refund_webhook_repairs_ambiguous_external_result(phase3, monkeypatch):
    from payments.providers.base import MockProvider
    monkeypatch.setattr(MockProvider, "refund", AsyncMock(side_effect=TimeoutError("response lost after external success")))
    async def run():
        tenant, headers, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant)
            assert (await paid(http, order)).status_code == 200
            refund = await owner_action(http, headers, "/transactions/" + order["payment"]["_id"] + "/refunds", {"idempotency_key": "refund-webhook", "amount": 10000})
            assert refund["status"] == "external_unknown"
            p = order["payment"]
            event = {"event_id": "refund-confirmed", "reference": p["provider_reference"], "provider_payment_id": p["provider_payment_id"], "currency": "IDR", "amount": p["amount"], "status": "refund_succeeded", "refund_id": refund["_id"], "refund_amount": 10000, "provider_refund_id": "mock_refund_" + refund["_id"]}
            raw = json.dumps(event).encode(); signature = hmac.new(b"mock_signature_key", raw, hashlib.sha256).hexdigest()
            for _ in range(4):
                result = await http.post("/api/commerce/webhooks/payments/kasera", content=raw, headers={"x-mock-signature": signature})
                assert result.status_code == 200, result.text
            payment = await database.order_payments.find_one({"order_id": order["_id"]})
            assert payment["refunded_amount"] == 10000 and payment["refund_reserved"] == 0
            assert sum(e["type"] == "REFUND_REVERSAL" for e in (await Ledger(database, tenant["_id"]).get())["events"]) == 1
    asyncio.run(run())

def test_shipping_rate_failure_and_create_timeout_safe(phase3, monkeypatch):
    async def run():
        tenant, headers, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            await owner_action(http, headers, "/shipping-settings", {"mode": "integrated_shipping", "manual_shipping_fee": 5000, "origin": ADDRESS, "credentials": {"api_key": "mock_api", "webhook_secret": "mock_secret"}}, "PUT")
            await http.post(f"/api/store/t/{tenant['slug']}/login", json={"email": "phase3@example.com", "password": "safe-test-password"})
            body = {"items": [{"pid": "physical", "variant_id": variant["_id"], "qty": 2}], "shipping_address": ADDRESS}
            original = MockShipping.get_rates
            monkeypatch.setattr(MockShipping, "get_rates", AsyncMock(side_effect=FulfillmentUnavailable("rate outage")))
            assert (await http.post(f"/api/store/t/{tenant['slug']}/gateway/rates", json=body)).status_code == 503
            assert await database.purchases.count_documents({}) == 0
            monkeypatch.setattr(MockShipping, "get_rates", original)
            rate = (await http.post(f"/api/store/t/{tenant['slug']}/gateway/rates", json=body)).json()["rates"][0]
            order = await create(http, tenant["slug"], variant, rate_id=rate["_id"])
            assert (await paid(http, order)).status_code == 200
            record = await ready(http, headers, order, database)
            called = AsyncMock(side_effect=TimeoutError("provider timeout"))
            monkeypatch.setattr(MockShipping, "create_shipment", called)
            for _ in range(2):
                result = await http.post(BASE + f"/shipments/{order['_id']}/{record['_id']}", headers=headers)
                assert result.status_code == 503, result.text
            assert called.await_count == 1
            assert (await database.integrated_shipments.find_one({}))["status"] == "create_unknown"
            assert (await database.fulfillments.find_one({"_id": record["_id"]}))["status"] == "ready_to_ship"
    asyncio.run(run())

def test_return_journal_projection_failure_and_retry(phase3, monkeypatch):
    from commerce.physical.stock import PhysicalStock
    original = PhysicalStock.project
    async def fail(self, doc):
        if any(e["type"] == "RETURN" for e in doc["stock_events"]):
            raise AutoReconnect("synthetic return projection outage")
        return await original(self, doc)
    async def run():
        tenant, headers, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant)
            assert (await paid(http, order)).status_code == 200
            await delivered(http, headers, order, database)
            ret = await http.post(f"/api/store/t/{tenant['slug']}/orders/{order['_id']}/returns", json={"idempotency_key": "return-outage", "item_lines": [{"line_id": order["items"][0]["line_id"], "quantity": 1}], "reason": "Damaged"})
            rid = ret.json()["_id"]
            for state in ("reviewing", "approved", "received"): await owner_action(http, headers, "/returns/" + rid, {"status": state})
            monkeypatch.setattr(PhysicalStock, "project", fail)
            result = await http.post(BASE + "/returns/" + rid, headers=headers, json={"status": "inspected", "resolution": "damaged"})
            assert result.status_code == 503
            assert (await database.return_requests.find_one({"_id": rid}))["stock_compensation_pending"]
            stock = await database.physical_variants.find_one({"_id": variant["_id"]})
            assert stock["on_hand"] == 8 and sum(e["type"] == "RETURN" for e in stock["stock_events"]) == 1
            monkeypatch.setattr(PhysicalStock, "project", original)
            await owner_action(http, headers, "/reconciliation/repair")
            assert not (await database.return_requests.find_one({"_id": rid}))["stock_compensation_pending"]
            assert (await database.physical_variants.find_one({"_id": variant["_id"]}))["on_hand"] == 8
    asyncio.run(run())

@pytest.mark.parametrize("offset", [0, -301, 301])
def test_kasera_timestamped_signature_and_live_rejection(monkeypatch, offset):
    from payments.providers.kasera import KaseraSandbox
    monkeypatch.setenv("PHASE3_SANDBOX_ENABLED", "true")
    provider = KaseraSandbox("kasera", "sandbox", {"api_key": "kp_test_synthetic", "webhook_secret": "test-signing-key"})
    value = {"id": "evt", "type": "payment.paid", "livemode": False, "data": {"external_id": "reference", "payment_request_id": "payreq", "amount": 1000, "currency": "IDR", "status": "succeeded"}}
    raw = json.dumps(value).encode(); stamp = str(int(time.time()) + offset)
    sig = "t=" + stamp + ",v1=" + hmac.new(b"test-signing-key", stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    if offset:
        with pytest.raises(CommerceError): provider.verify_webhook(raw, sig)
    else:
        assert provider.verify_webhook(raw, sig)["status"] == "paid"
        with pytest.raises(CommerceError): provider.verify_webhook(raw + b" ", sig)

def test_midtrans_signature_and_reference(monkeypatch):
    from payments.providers.midtrans import MidtransSandbox
    monkeypatch.setenv("PHASE3_SANDBOX_ENABLED", "true")
    provider = MidtransSandbox("midtrans", "sandbox", {"server_key": "SB-Mid-server-synthetic"})
    value = {"order_id": "ref", "status_code": "200", "gross_amount": "10000.00", "transaction_id": "tx", "transaction_status": "settlement"}
    value["signature_key"] = hashlib.sha512(b"ref20010000.00SB-Mid-server-synthetic").hexdigest()
    assert provider.verify_webhook(json.dumps(value).encode(), "")["amount"] == 10000
    with pytest.raises(CommerceError): provider.verify_webhook(json.dumps({**value, "gross_amount": "20000.00"}).encode(), "")
