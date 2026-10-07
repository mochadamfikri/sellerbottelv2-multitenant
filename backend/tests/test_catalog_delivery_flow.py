"""Offline checks: never contact Telegram, payments or the live database."""
import asyncio
import base64

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

import bot
import bot2
import inventory
import storefront_routes
import catalog_routes
from db import db, DEFAULT_SETTINGS
from product_catalog import catalog_token, catalog_slice


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("INVENTORY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    import stock_monitor
    monkeypatch.setattr(stock_monitor, "schedule_stock_scan", lambda *args: None)
    async def reset():
        for name in ("products", "inventory_items", "purchases", "settings", "product_catalogs"):
            await db[name].delete_many({})
        await db.settings.insert_one({**DEFAULT_SETTINGS, "_id": "main", "rate_mode": "manual", "manual_rate": 15000})
    asyncio.run(reset())


@pytest.mark.parametrize("second", [False, True])
def test_bot_catalog_pagination_and_stable_product_buttons(monkeypatch, second):
    sent = []
    async def send(chat, text, kb=None):
        sent.append((text, kb))
    monkeypatch.setattr(bot2 if second else bot, "send2" if second else "send_message", send)
    async def run():
        products = [{"_id": f"p{i}", "name": f"Claude Pro {i} bulan", "catalog_name": "Claude Pro", "active": True, "product_kind": "service", "delivery_type": "service", "price_idr": 10000} for i in range(1, 301)]
        await db.products.insert_many(products)
        await db.products.insert_one({"_id": "inactive", "active": False, "catalog_name": "Hidden"})
        user = {"lang": "id", "currency": "IDR"}
        async def show(**kwargs):
            if second:
                await bot2.show_products(123, **kwargs)
            else:
                await bot.show_products(123, user, **kwargs)
        await show()
        assert "Katalog produk" in sent[-1][0]
        assert "300 pilihan" in str(sent[-1][1])
        assert "Hidden" not in str(sent[-1])
        token = catalog_token(products[0])
        await show(catalog=token)
        assert "Halaman 1/38" in sent[-1][0]
        callbacks = [button["callback_data"] for row in sent[-1][1]["inline_keyboard"] for button in row]
        prefix = "b2:product:" if second else "prod:"
        assert [value for value in callbacks if value.startswith(prefix)] == [f"{prefix}p{i}" for i in range(1, 9)]
        assert all(len(value.encode()) <= 64 for value in callbacks)
        await db.products.delete_one({"_id": "p1"})
        assert await db.products.find_one({"_id": callbacks[1].split(":")[-1]})
        await show(catalog=token, page=999)
        assert "Halaman 38/38" in sent[-1][0]
        await show(catalog="deleted")
        assert "tidak tersedia" in sent[-1][0]
    asyncio.run(run())


def test_catalog_exclusion_survives_rename_and_delete():
    async def run():
        await db.products.insert_one({"_id": "p", "name": "Claude Pro", "catalog_name": "Claude Pro"})
        await db.settings.update_one({"_id": "main"}, {"$set": {"post_purchase_followup.exempt_catalogs": ["Claude Pro"]}})
        await catalog_routes.rename_catalog(catalog_routes.RenameBody(old_name="Claude Pro", name="Claude"))
        assert (await db.settings.find_one({"_id": "main"}))["post_purchase_followup"]["exempt_catalogs"] == ["Claude"]
        await catalog_routes.delete_catalog("Claude")
        config = (await db.settings.find_one({"_id": "main"}))["post_purchase_followup"]
        assert config["exempt_catalogs"] == []
        assert config["exempt_product_ids"] == ["p"]
    asyncio.run(run())


def test_order_details_download_authorization_and_pending_privacy():
    app = FastAPI()
    app.include_router(storefront_routes.router)
    customer = {"_id": "owner", "telegram_id": 123}
    app.dependency_overrides[storefront_routes.current_customer] = lambda: customer
    async def run():
        await db.products.insert_one({"_id": "p", "name": "Claude", "inventory_enabled": True})
        await inventory.add_records("p", [{"email": "owned@example.test", "password": "private-account"}], ["email", "password"])
        record = await db.inventory_items.find_one({"product_id": "p"})
        await db.inventory_items.update_one({"_id": record["_id"]}, {"$set": {"status": "sold", "order_id": "owned"}})
        order = {"_id": "owned", "customer_id": "owner", "status": "delivered", "invoice_id": "INV-1", "items": [{"product_id": "p", "name": "Claude", "delivery_type": "inventory", "qty": 1}]}
        await db.purchases.insert_one(order)
        await db.purchases.insert_one({**order, "_id": "other", "customer_id": "stranger"})
        await db.purchases.insert_one({**order, "_id": "pending", "status": "paid"})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
            response = await client.get("/api/store/orders/owned/delivery")
            assert response.status_code == 200, response.text
            assert "no-store" in response.headers["cache-control"]
            assert response.json()["products"][0]["accounts"][0]["password"] == "private-account"
            text = await client.get("/api/store/orders/owned/download")
            assert "private-account" in text.text
            assert "attachment" in text.headers["content-disposition"]
            assert (await client.get("/api/store/orders/other/delivery")).status_code == 404
            assert (await client.get("/api/store/orders/other/download")).status_code == 404
            response = await client.get("/api/store/orders/pending/delivery")
            assert response.json()["products"] == []
            assert (await client.get("/api/store/orders/pending/download")).status_code == 409
            customer["_id"] = "other-owner"
            assert (await client.get("/api/store/orders/owned/download")).status_code == 404
    asyncio.run(run())


def test_session_file_bound_to_order():
    from order_fulfillment import delivered_file, fulfillment
    from fastapi import HTTPException
    async def run():
        await inventory.add_records("file", [{"Session File": "account.session", "__file_name": "account.session", "__file_data_b64": base64.b64encode(b"session-bytes").decode()}], ["Session File"])
        record = await db.inventory_items.find_one({"product_id": "file"})
        await db.inventory_items.update_one({"_id": record["_id"]}, {"$set": {"status": "sold", "order_id": "o"}})
        order = {"_id": "o", "status": "delivered", "items": [{"product_id": "file", "qty": 1}]}
        assert (await delivered_file(order, record["_id"])) == (b"session-bytes", "account.session")
        data = await fulfillment(order)
        assert "session-bytes" not in str(data) and "__file_data_b64" not in str(data)
        with pytest.raises(HTTPException):
            await delivered_file({**order, "_id": "different"}, record["_id"])
        with pytest.raises(HTTPException):
            await delivered_file({**order, "status": "paid"}, record["_id"])
    asyncio.run(run())


def test_bot2_service_is_not_delivered_or_processed_twice(monkeypatch):
    calls = []
    async def fake_notify(order):
        calls.append(order["status"])
    async def noop(*args, **kwargs):
        return {"ok": True}
    monkeypatch.setattr(bot2, "notify_transaction_channel_safely", fake_notify)
    monkeypatch.setattr(bot2, "notify_service_waiting", noop)
    monkeypatch.setattr(bot2, "send2", noop)
    async def run():
        await db.products.insert_one({"_id": "service", "product_kind": "service", "delivery_type": "service"})
        await db.purchases.insert_one({"_id": "o", "invoice_id": "INV", "user_tid": 123, "status": "pending_payment", "items": [{"product_id": "service", "qty": 1}]})
        await asyncio.gather(bot2.finalize_bot2_checkout("o"), bot2.finalize_bot2_checkout("o"))
        order = await db.purchases.find_one({"_id": "o"})
        assert order["status"] == "service_waiting"
        assert order["delivered_at"] is None
        assert calls == ["service_waiting"]
    asyncio.run(run())
