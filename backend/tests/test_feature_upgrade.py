import asyncio
import io
from datetime import datetime, timezone, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from openpyxl import load_workbook
from PIL import Image

import admin_routes
import inventory
import post_purchase
import services
import broadcast_composer
from auth import get_current_admin
from db import db, DEFAULT_SETTINGS
from product_artwork import artwork_labels, artwork_urls, image_response, render_product_artwork

app = FastAPI()
app.include_router(admin_routes.router)
app.dependency_overrides[get_current_admin] = lambda: {"_id": "offline-admin"}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("INVENTORY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    import stock_monitor
    monkeypatch.setattr(stock_monitor, "schedule_stock_scan", lambda *args: None)
    async def reset():
        for name in ("products", "inventory_items", "settings", "bot_users", "purchases", "post_purchase_actions", "reseller_bots"):
            await db[name].delete_many({})
        await db.settings.insert_one({**DEFAULT_SETTINGS, "_id": "main", "rate_mode": "manual", "manual_rate": 15000})
        await db.inventory_items.create_index([("product_id", 1), ("fingerprint", 1)], unique=True)
    asyncio.run(reset())


def test_four_column_templates_and_text_import():
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
            for format in ("txt", "csv", "xlsx"):
                response = await client.get(f"/api/admin/products/import-template?format={format}")
                assert response.status_code == 200
                if format == "xlsx":
                    headers = list(next(load_workbook(io.BytesIO(response.content)).active.values))
                else:
                    headers = response.content.decode("utf-8-sig").strip().split("|" if format == "txt" else ",")
                assert headers == ["katalog", "product", "jenis (inventory/jasa)", "Harga"]
            for extension, delimiter in (("txt", "|"), ("csv", ",")):
                text = delimiter.join(headers) + "\n" + delimiter.join(["Claude Pro", f"Claude Pro {extension}", "inventory", "100000"])
                response = await client.post("/api/admin/products/import", files={"file": (f"products.{extension}", text.encode())})
                assert response.status_code == 200, response.text
                assert response.json()["imported"] == 1
            response = await client.post("/api/admin/products/import", data={"content": "katalog|product|jenis (inventory/jasa)|Harga\nLayanan|Jasa Test|jasa|20000"})
            assert response.status_code == 200
            product = await db.products.find_one({"name": "Jasa Test"})
            assert product["product_kind"] == "service"
            assert product["price_idr"] == 20000
            assert product["catalog_name"] == "Layanan"
    asyncio.run(check())


def test_inventory_edit_delete_templates_and_sold_privacy():
    async def check():
        await db.products.insert_one({"_id": "p", "name": "Claude Pro", "product_kind": "digital", "inventory_schema": ["email", "password"]})
        await inventory.add_records("p", [{"email": "before@example.com", "password": "secret"}], ["email", "password"])
        item = await db.inventory_items.find_one({"product_id": "p"})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
            path = f"/api/admin/products/p/inventory/{item['_id']}"
            response = await client.put(path, json={"data": {"email": "after@example.com", "password": "new"}})
            assert response.status_code == 200, response.text
            edited = await db.inventory_items.find_one({"_id": item["_id"]})
            assert "after@example.com" not in edited["secret"]
            assert inventory.decrypt_items([edited])[0]["email"] == "after@example.com"
            # A previous value can be uploaded again after editing, with a new identity.
            result = await inventory.add_records("p", [{"email": "before@example.com", "password": "secret"}], ["email", "password"])
            assert result["created"] == 1
            assert (await client.put(path, json={"data": {"email": "before@example.com", "password": "secret"}})).status_code == 409
            await db.inventory_items.update_one({"_id": item["_id"]}, {"$set": {"status": "sold"}})
            assert (await client.put(path, json={"data": {"email": "x", "password": "y"}})).status_code == 409
            assert (await client.delete(path)).status_code == 400
            response = await client.get("/api/admin/products/p/inventory?status=all")
            assert all("item" not in row for row in response.json()["items"] if row["status"] == "sold")
            response = await client.get("/api/admin/products/p/inventory/template?format=txt")
            assert response.content.decode("utf-8-sig").strip() == "email|password"
            available = await db.inventory_items.find_one({"status": "available"})
            assert (await client.delete(f"/api/admin/products/p/inventory/{available['_id']}")).status_code == 200
    asyncio.run(check())


def test_post_purchase_exceptions_and_one_time_execution(monkeypatch):
    calls = []
    async def fake_tg(method, **kwargs):
        calls.append((method, kwargs))
        return {"ok": True, "result": {"status": "member"} if method == "getChatMember" else True}
    monkeypatch.setattr(post_purchase, "tg", fake_tg)
    async def check():
        now = datetime.now(timezone.utc)
        config = {"mode": "kick_block", "enabled_since": (now - timedelta(hours=1)).isoformat(), "channel_ids": ["@channel"], "exempt_resellers": True}
        settings = {"post_purchase_followup": config}
        await db.bot_users.insert_one({"telegram_id": 123})
        await db.products.insert_one({"_id": "p", "name": "Claude Pro", "catalog_name": "Claude Pro"})
        order = {"_id": "o", "user_tid": 123, "status": "delivered", "delivered_at": now.isoformat(), "items": [{"product_id": "p"}]}
        await post_purchase.process_completed({**order, "status": "paid"}, settings)
        assert not calls
        await post_purchase.process_completed(order, {"post_purchase_followup": {**config, "exempt_catalogs": ["Claude Pro"]}})
        assert not calls
        assert (await db.post_purchase_actions.find_one({"_id": "o"}))["status"] == "skipped"
        order["_id"] = "new-order"
        await post_purchase.process_completed(order, settings)
        await post_purchase.process_completed(order, settings)
        assert len(calls) == 2
        assert (await db.bot_users.find_one({"telegram_id": 123}))["silent_blocked"]
        assert not any(method == "deleteMessages" for method, _ in calls)
        for cfg, reason in (({"exempt_user_ids": [123]}, "Pengecualian pengguna"), ({"exempt_product_ids": ["p"]}, "Pengecualian produk")):
            assert await post_purchase.exemption(order, {**config, **cfg}, settings) == reason
        await db.reseller_bots.insert_one({"owner_tid": 123})
        assert await post_purchase.exemption(order, config, settings) == "Pengecualian reseller"
    asyncio.run(check())


def test_broadcast_destinations_and_disabled_transactions(monkeypatch):
    sent = []
    async def fake_send(chat_id, text, image):
        sent.append(chat_id)
        return {"ok": True}
    monkeypatch.setattr(broadcast_composer, "send_composed", fake_send)
    async def check():
        await db.settings.update_one({"_id": "main"}, {"$set": {"broadcast_channel_id": "@general", "transaction_channel_ids": "@sales", "recap_channel_ids": "@reports"}})
        assert await broadcast_composer.configured_chats("daily_recap") == ["@reports"]
        assert await broadcast_composer.selected_chats(broadcast_composer.ComposeBody(chat_ids=["@custom"])) == ["@custom"]
        await services.notify_transaction_channel({"items": [], "total": 10000})
        assert not sent
        await db.settings.update_one({"_id": "main"}, {"$set": {"transaction_success_channel_enabled": True}})
        await services.notify_transaction_channel({"items": [], "total": 10000})
        assert sent == ["@sales"]
        _, picture, _ = await broadcast_composer.build_content(broadcast_composer.ComposeBody(message="Test", image_mode="none"))
        assert picture is None
    asyncio.run(check())


def test_artwork_plan_duration_and_custom_precedence(monkeypatch):
    assert artwork_labels("Claude Pro 1 bulan")["plan"] == "PRO"
    assert artwork_labels("Claude Pro Trial 3 bulan")["plan"] == "TRIAL"
    assert artwork_labels("ChatGPT Plus 1 bulan (bukan Trial)")["plan"] == "PLUS"
    assert artwork_labels("Claude Pro 6 Bulan")["duration"] == "6 BULAN"
    assert artwork_labels("Claude Pro 6 Bulan", "Claude Pro", True)["duration"] == "PILIH VARIAN"
    assert Image.open(io.BytesIO(render_product_artwork("Claude Pro 1 bulan"))).size == (1200, 1200)
    assert artwork_urls({"_id": "a", "name": "Claude Pro"})["image_source"] == "generated"
    import storage
    async def custom(path):
        return b"custom-image", "image/webp"
    monkeypatch.setattr(storage, "get_object", custom)
    response = asyncio.run(image_response({"name": "Claude Pro", "image_path": "custom"}))
    assert response.body == b"custom-image"
