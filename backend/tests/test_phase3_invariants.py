import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
import httpx
import pytest
from commerce.fulfillment_types import CommerceError
from payments.models import now
from payments.ledger import Ledger, balances
from payments.providers.base import MockProvider
from tests.test_public_tenant_management import management
from tests.test_phase3_payments import phase3, setup, create, paid
from tests.test_phase3_post_purchase import owner_action, delivered, BASE
from tests.test_physical_commerce import ADDRESS

def test_mixed_cart_one_payment_snapshot_and_order_total(phase3):
    async def run():
        tenant, headers, database, variant = await setup(phase3)
        await database.products.insert_many([{"_id": "digital", "name": "Download", "active": True, "price_idr": 1000, "delivery_type": "link", "content": "SYNTHETIC"}, {"_id": "service", "name": "Service", "active": True, "price_idr": 2000, "product_kind": "service", "delivery_type": "service"}])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            await http.post(f"/api/store/t/{tenant['slug']}/login", json={"email": "phase3@example.com", "password": "safe-test-password"})
            result = await http.post(f"/api/store/t/{tenant['slug']}/checkout", json={"items": [{"pid": "physical", "variant_id": variant["_id"], "qty": 1}, {"pid": "digital", "qty": 1}, {"pid": "service", "qty": 1}], "shipping_address": ADDRESS, "payment_method": "gateway:qris", "idempotency_key": "mixed-checkout"})
            assert result.status_code == 200, result.text
            order = result.json(); assert order["payment"]["amount"] == 18000
            assert (await paid(http, order)).status_code == 200
            records = await database.fulfillments.find({"order_id": order["_id"]}).to_list(None)
            assert {r["type"]: r["status"] for r in records} == {"physical": "pending", "digital_auto": "delivered", "service": "queued"}
            saved = await database.purchases.find_one({"_id": order["_id"]})
            assert saved["items_subtotal"] - saved["discount_total"] + saved["shipping_fee"] + saved["tax"] + saved["payment_fee"] == saved["grand_total"]
            assert await database.order_payments.count_documents({}) == 1
    asyncio.run(run())

@pytest.mark.parametrize("mode", ["manual_shipping", "pickup_only", "integrated_shipping"])
def test_balance_checkout_shipping_modes_preserve_wallet(phase3, mode):
    async def run():
        tenant, headers, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            await owner_action(http, headers, "/shipping-settings", {"mode": mode, "manual_shipping_fee": 5000, "origin": ADDRESS, **({"credentials": {"api_key": "mock_ship", "webhook_secret": "mock_secret"}} if mode == "integrated_shipping" else {})}, "PUT")
            await http.post(f"/api/store/t/{tenant['slug']}/login", json={"email": "phase3@example.com", "password": "safe-test-password"})
            rate_id = None
            if mode == "integrated_shipping":
                rate = await http.post(f"/api/store/t/{tenant['slug']}/gateway/rates", json={"items": [{"pid": "physical", "variant_id": variant["_id"], "qty": 1}], "shipping_address": ADDRESS})
                rate_id = rate.json()["rates"][0]["_id"]
            result = await http.post(f"/api/store/t/{tenant['slug']}/checkout", json={"items": [{"pid": "physical", "variant_id": variant["_id"], "qty": 1}], "shipping_address": ADDRESS, "payment_method": "balance", "idempotency_key": "balance-mode-test", "shipping_rate_id": rate_id})
            assert result.status_code == 200, result.text
            expected = {"manual_shipping": 15000, "pickup_only": 10000, "integrated_shipping": 16000}[mode]
            assert result.json()["total"] == expected
            assert (await database.store_customers.find_one({"_id": "same-customer"}))["balance_idr"] == 100000 - expected
            assert await database.order_payments.count_documents({}) == 0
            if mode == "pickup_only":
                record = await database.fulfillments.find_one({"order_id": result.json()["_id"]})
                for status in ("packing", "ready_to_ship", "delivered"):
                    response = await http.post(f"/api/public/tenant/full/physical/orders/{result.json()['_id']}/fulfillments/{record['_id']}", headers=headers, json={"status": status})
                    assert response.status_code == 200, response.text
                saved = await database.fulfillments.find_one({"_id": record["_id"]})
                assert saved["shipment_snapshot"]["mode"] == "pickup_only" and saved["shipment_snapshot"]["tracking_number"] is None
    asyncio.run(run())

def test_rejected_return_releases_quantity_and_c2_orders_eligible(phase3):
    async def run():
        tenant, headers, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant, qty=1)
            assert (await paid(http, order)).status_code == 200
            await delivered(http, headers, order, database)
            # C2 orders predate canonical payment tenant_id snapshots.
            await database.purchases.update_one({"_id": order["_id"]}, {"$unset": {"tenant_id": ""}})
            path = f"/api/store/t/{tenant['slug']}/orders/{order['_id']}/returns"
            body = {"idempotency_key": "return-rejected", "item_lines": [{"line_id": order["items"][0]["line_id"], "quantity": 1}], "reason": "Review"}
            first = await http.post(path, json=body); assert first.status_code == 200, first.text
            rid = first.json()["_id"]
            await owner_action(http, headers, "/returns/" + rid, {"status": "reviewing"})
            await owner_action(http, headers, "/returns/" + rid, {"status": "rejected"})
            assert (await http.post(path, json={**body, "idempotency_key": "return-resubmit"})).status_code == 200
    asyncio.run(run())

def test_settlement_fee_timing_and_refund_does_not_steal_other_pending(phase3):
    async def run():
        tenant, _, database, _ = await setup(phase3)
        ledger = Ledger(database, tenant["_id"])
        p = {"_id": "a", "order_id": "a", "payment_mode": "platform_settlement", "environment": "mock", "amount": 10000, "gateway_fee": 100, "platform_fee": 200, "clearing_at": now() + timedelta(seconds=100), "available_at": now() + timedelta(seconds=200)}
        q = {**p, "_id": "b", "order_id": "b"}
        await ledger.credit(p); await ledger.credit(q)
        assert balances((await ledger.get())["events"])["pending"] == 19400
        with pytest.raises(CommerceError): await ledger.advance(p, "clearing")
        await ledger.reverse(p, {"_id": "refund-a", "amount": 10000})
        values = balances((await ledger.get())["events"])
        assert values["pending"] == 9700 and values["liability"] == 300
        q["clearing_at"] = now() - timedelta(seconds=1); q["available_at"] = now() - timedelta(seconds=1)
        await ledger.advance(q, "clearing"); await ledger.advance(q, "available")
        assert balances((await ledger.get())["events"])["available"] == 9700
    asyncio.run(run())

def test_create_timeout_can_accept_signed_paid_confirmation(phase3, monkeypatch):
    called = AsyncMock(side_effect=TimeoutError("external succeeded response lost"))
    monkeypatch.setattr(MockProvider, "create_payment", called)
    async def run():
        tenant, _, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant)
            assert order["payment"]["reconciliation"] == "create_unknown"
            order["payment"]["provider_payment_id"] = "mock_" + order["payment"]["provider_reference"]
            assert (await paid(http, order)).status_code == 200
            assert called.await_count == 1
            p = await database.order_payments.find_one({"order_id": order["_id"]})
            assert p["status"] == "paid" and p["reconciliation"] is None
            assert (await database.physical_variants.find_one({"_id": variant["_id"]}))["on_hand"] == 8
    asyncio.run(run())


def test_canonical_expiry_worker_disabled_store_without_bot_releases_once(phase3):
    async def run():
        from payments.maintenance import sweep
        tenant, _, database, variant = await setup(phase3)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]), base_url="https://mock") as http:
            order = await create(http, tenant["slug"], variant)
            await database.order_payments.update_one({"order_id": order["_id"]}, {"$set": {"expires_at": now() - timedelta(seconds=1)}})
            await phase3[0].update_status(tenant["slug"], "disabled")
            await sweep(); await sweep()
            assert (await database.purchases.find_one({"_id": order["_id"]}))["status"] == "expired"
            stock = await database.physical_variants.find_one({"_id": variant["_id"]})
            assert stock["reserved"] == 0 and stock["on_hand"] == 10
            assert sum(e["type"] == "RELEASE" for e in stock["stock_events"]) == 1
    asyncio.run(run())
