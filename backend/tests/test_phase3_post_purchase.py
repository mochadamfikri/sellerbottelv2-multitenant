"""3C/3D: rate snapshots, tracking, return quantities and financial refunds."""
import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from commerce.fulfillment_types import CommerceError
from payments.ledger import Ledger, balances
from payments.providers.base import MockProvider
from tests.test_phase3_payments import phase3, setup, create, paid
from tests.test_public_tenant_management import management
from tests.test_physical_commerce import ADDRESS

BASE = "/api/public/tenant/full/commerce"

async def owner_action(http, headers, path, data=None, method="POST"):
    r = await http.request(method, BASE + path, headers=headers, json=data)
    assert r.status_code == 200, r.text
    return r.json()

async def ready(http, headers, order, database):
    record = await database.fulfillments.find_one({"order_id": order["_id"]})
    for status in ("packing", "ready_to_ship"):
        r = await http.post(f"/api/public/tenant/full/physical/orders/{order['_id']}/fulfillments/{record['_id']}", headers=headers, json={"status": status})
        assert r.status_code == 200, r.text
    return record

async def delivered(http, headers, order, database):
    record = await ready(http, headers, order, database)
    for status in ("shipped", "delivered"):
        r = await http.post(f"/api/public/tenant/full/physical/orders/{order['_id']}/fulfillments/{record['_id']}", headers=headers, json={"status": status, "carrier_name": "Manual", "tracking_number": "manual-123"})
        assert r.status_code == 200, r.text
    return record

@pytest.mark.parametrize("resolution", ["restock", "damaged"])
def test_partial_return_quantity_duplicate_compensation_and_refund(phase3, resolution):
    async def run():
        tenant, headers, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant, qty=3)
            assert (await paid(http, order)).status_code == 200
            await delivered(http, headers, order, database)
            path = f"/api/store/t/{tenant['slug']}/orders/{order['_id']}/returns"
            body = {"idempotency_key": "return-request", "item_lines": [{"line_id": order["items"][0]["line_id"], "quantity": 1}], "reason": "Wrong fit"}
            returns = await asyncio.gather(*(http.post(path, json=body) for _ in range(5)))
            assert all(r.status_code == 200 for r in returns), [r.text for r in returns]
            rid = returns[0].json()["_id"]
            assert await database.return_requests.count_documents({}) == 1
            for status in ("reviewing", "approved", "received", "inspected", "inspected", "resolved"):
                await owner_action(http, headers, "/returns/" + rid, {"status": status, "resolution": resolution if status == "inspected" else None})
            stock = await database.physical_variants.find_one({"_id": variant["_id"]})
            assert stock["on_hand"] == (8 if resolution == "restock" else 7)
            assert sum(e["type"] == "RETURN" for e in stock["stock_events"]) == 1
            assert sum(e["type"] == "DAMAGE" for e in stock["stock_events"]) == (1 if resolution == "damaged" else 0)
            assert (await http.post(path, json={**body, "idempotency_key": "over-return", "item_lines": [{"line_id": order["items"][0]["line_id"], "quantity": 3}]})).status_code == 422
            refunded = await owner_action(http, headers, "/transactions/" + order["payment"]["_id"] + "/refunds", {"idempotency_key": "refund-partial", "amount": 10000, "return_id": rid})
            assert refunded["status"] == "succeeded"
            replay = await owner_action(http, headers, "/transactions/" + order["payment"]["_id"] + "/refunds", {"idempotency_key": "refund-partial", "amount": 10000, "return_id": rid})
            assert replay["_id"] == refunded["_id"]
            payment = await database.order_payments.find_one({"order_id": order["_id"]})
            assert payment["refunded_amount"] == 10000 and payment["status"] == "partially_refunded"
            assert balances((await Ledger(database, tenant["_id"]).get())["events"])["pending"] == 25000
    asyncio.run(run())

@pytest.mark.parametrize("mode,name", [("platform_settlement", "kasera"), ("self_gateway", "kasera"), ("self_gateway", "midtrans")])
def test_refund_race_never_exceeds_paid_and_full_state(phase3, mode, name):
    async def run():
        tenant, headers, database, variant = await setup(phase3, mode=mode, name=name)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant, qty=1)
            assert (await paid(http, order)).status_code == 200
            path = BASE + "/transactions/" + order["payment"]["_id"] + "/refunds"
            results = await asyncio.gather(*(http.post(path, headers=headers, json={"idempotency_key": f"race-refund-{i}", "amount": 10000}) for i in range(8)))
            assert sum(r.status_code == 200 for r in results) == 1, [r.text for r in results]
            assert (await http.post(path, headers=headers, json={"idempotency_key": "refund-final", "amount": 5000})).status_code == 200
            payment = await database.order_payments.find_one({"order_id": order["_id"]})
            assert payment["status"] == "refunded" and payment["refunded_amount"] == 15000 and payment["refund_reserved"] == 0
            ledger = (await Ledger(database, tenant["_id"]).get())["events"]
            assert sum(e["type"] == "REFUND_REVERSAL" for e in ledger) == (2 if mode == "platform_settlement" else 0)
    asyncio.run(run())

def test_provider_refund_timeout_no_replay_or_unreserved_overrefund(phase3, monkeypatch):
    called = AsyncMock(side_effect=TimeoutError("synthetic provider timeout"))
    monkeypatch.setattr(MockProvider, "refund", called)
    async def run():
        tenant, headers, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant, qty=1); assert (await paid(http, order)).status_code == 200
            path = "/transactions/" + order["payment"]["_id"] + "/refunds"
            body = {"idempotency_key": "unknown-refund", "amount": 15000}
            assert (await owner_action(http, headers, path, body))["status"] == "external_unknown"
            await owner_action(http, headers, path, body)
            assert called.await_count == 1
            assert (await http.post(BASE + path, headers=headers, json={"idempotency_key": "second-refund", "amount": 1})).status_code == 422
            report = await owner_action(http, headers, "/reconciliation", method="GET")
            assert report["refunds"][0]["state"] == "external_unknown"
    asyncio.run(run())

def test_integrated_shipping_rate_snapshot_event_and_cross_tenant(phase3):
    async def run():
        from db import client, platform_db
        tenant, headers, database, variant = await setup(phase3)
        other, foreign, another, another_variant = await setup(phase3, "ship-b", "self_gateway")
        shipping = {"mode": "integrated_shipping", "manual_shipping_fee": 5000, "origin": ADDRESS, "credentials": {"api_key": "mock_ship_api", "webhook_secret": "mock_shipping_secret"}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            await owner_action(http, headers, "/shipping-settings", shipping, "PUT")
            await http.post(f"/api/store/t/{tenant['slug']}/login", json={"email": "phase3@example.com", "password": "safe-test-password"})
            body = {"items": [{"pid": "physical", "variant_id": variant["_id"], "qty": 2}], "shipping_address": ADDRESS}
            response = await http.post(f"/api/store/t/{tenant['slug']}/gateway/rates", json=body)
            assert response.status_code == 200, response.text
            rate = response.json()["rates"][0]
            order = await create(http, tenant["slug"], variant, rate_id=rate["_id"])
            assert order["shipping_fee"] == 6000 and order["payment"]["amount"] == 26000
            assert "secret" not in json.dumps(order, default=str) and "mock_shipping_secret" not in json.dumps(order)
            assert (await paid(http, order)).status_code == 200
            record = await ready(http, headers, order, database)
            shipment = await owner_action(http, headers, f"/shipments/{order['_id']}/{record['_id']}")
            again = await owner_action(http, headers, f"/shipments/{order['_id']}/{record['_id']}")
            assert again["provider_shipment_id"] == shipment["provider_shipment_id"]
            assert (await http.post(BASE + f"/shipments/{order['_id']}/{record['_id']}", headers=foreign)).status_code == 422
            assert await another.integrated_shipments.count_documents({}) == 0
            event = {"event_id": "tracking-delivered", "provider_shipment_id": shipment["provider_shipment_id"], "status": "delivered"}
            raw = json.dumps(event).encode(); signature = hmac.new(b"mock_shipping_secret", raw, hashlib.sha256).hexdigest()
            for _ in range(3):
                r = await http.post("/api/commerce/webhooks/shipping/mock_courier", content=raw, headers={"x-mock-signature": signature})
                assert r.status_code == 200, r.text
            assert (await database.fulfillments.find_one({"_id": record["_id"]}))["status"] == "delivered"
            assert len((await database.integrated_shipments.find_one({"_id": shipment["_id"]}))["events"]) == 1
            # Later configuration/rate edits never alter purchase-time pricing.
            await database.shipping_rates.update_one({"_id": rate["_id"]}, {"$set": {"amount": 999999}})
            assert (await database.purchases.find_one({"_id": order["_id"]}))["shipping_quote"]["amount"] == 6000
    asyncio.run(run())

def test_refund_confirmed_receipt_repairs_local_failure(phase3, monkeypatch):
    async def run():
        from db import platform_db
        import commerce.aftercare.refunds as refunds
        tenant, headers, database, variant = await setup(phase3)
        original = refunds.repair_refund
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant, qty=1); assert (await paid(http, order)).status_code == 200
            monkeypatch.setattr(refunds, "repair_refund", AsyncMock(side_effect=CommerceError("Injected local persistence failure")))
            r = await http.post(BASE + "/transactions/" + order["payment"]["_id"] + "/refunds", headers=headers, json={"idempotency_key": "durable-refund", "amount": 5000})
            assert r.status_code == 422
            assert (await platform_db().refund_operations.find_one({}))["state"] == "confirmed"
            monkeypatch.setattr(refunds, "repair_refund", original)
            await owner_action(http, headers, "/reconciliation/repair")
            await owner_action(http, headers, "/reconciliation/repair")
            p = await database.order_payments.find_one({"order_id": order["_id"]})
            assert p["refunded_amount"] == 5000 and p["refund_reserved"] == 0
            assert sum(e["type"] == "REFUND_REVERSAL" for e in (await Ledger(database, tenant["_id"]).get())["events"]) == 1
    asyncio.run(run())

def test_manual_refund_required_never_fake_success(phase3):
    async def run():
        tenant, headers, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant, qty=1); assert (await paid(http, order)).status_code == 200
            await database.order_payments.update_one({"order_id": order["_id"]}, {"$set": {"capabilities.refund_support": False}})
            refund = await owner_action(http, headers, "/transactions/" + order["payment"]["_id"] + "/refunds", {"idempotency_key": "manual-refund", "amount": 1000})
            assert refund["status"] == "manual_refund_required"
            p = await database.order_payments.find_one({"order_id": order["_id"]})
            assert p["refunded_amount"] == 0 and p["refund_reserved"] == 1000
    asyncio.run(run())
