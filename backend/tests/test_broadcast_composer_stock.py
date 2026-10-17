"""Offline checks for the simple broadcast and stock transitions."""
import asyncio
import os
import sys
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1"
os.environ["DB_NAME"] = "sellerbottel_broadcast_test"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret"

import motor.motor_asyncio as motor
from mongomock_motor import AsyncMongoMockClient

motor.AsyncIOMotorClient = AsyncMongoMockClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import broadcast_composer
import stock_monitor
import bot
from broadcast_image import render_product_collection
from db import db
from PIL import Image
from io import BytesIO


def run(coro):
    return asyncio.run(coro)


def test_composer_builds_one_image_for_multiple_products():
    async def check():
        await db.products.delete_many({})
        await db.inventory_items.delete_many({})
        for index in range(5):
            await db.products.insert_one({
                "_id": f"p{index}", "name": f"Produk {index}", "description": "  Deskripsi   produk   bagus. ",
                "active": True, "product_kind": "digital", "price_idr": 10000,
            })
            await db.inventory_items.insert_one({"_id": f"i{index}", "product_id": f"p{index}", "status": "available"})
        body = broadcast_composer.ComposeBody(message="Promo hari ini", product_ids=[f"p{i}" for i in range(5)])
        text, image, products = await broadcast_composer.build_content(body)
        assert len(products) == 5
        assert all(f"Produk {i}" in text for i in range(5))
        assert Image.open(BytesIO(image)).format == "JPEG"
        assert Image.open(BytesIO(image)).height > 1000
        ten = render_product_collection(products * 2)
        assert Image.open(BytesIO(ten)).format == "JPEG"

    run(check())


def test_stock_monitor_announces_only_zero_crossings(monkeypatch):
    async def chats():
        return ["@test_channel"]

    monkeypatch.setattr(stock_monitor, "configured_chats", chats)

    async def check():
        await db.products.delete_many({})
        await db.inventory_items.delete_many({})
        await db.stock_events.delete_many({})
        await db.products.insert_one({"_id": "stock-p", "name": "Produk A", "active": True,
                                      "product_kind": "digital", "price_idr": 10000})
        await stock_monitor.scan_stock()  # establish initial state, no notice
        assert await db.stock_events.count_documents({}) == 0
        await db.inventory_items.insert_one({"_id": "a", "product_id": "stock-p", "status": "available"})
        await stock_monitor.scan_stock()
        assert await db.stock_events.count_documents({"event_type": "restocked", "to_count": 1}) == 1
        await stock_monitor.scan_stock()
        assert await db.stock_events.count_documents({}) == 1
        await db.inventory_items.delete_one({"_id": "a"})
        await stock_monitor.scan_stock()
        assert await db.stock_events.count_documents({"event_type": "sold_out", "to_count": 0}) == 1

    run(check())


def test_bot_catalogs_group_products_and_show_variant_stock(monkeypatch):
    sent = []

    async def fake_send(chat_id, text, kb=None):
        sent.append({"text": text, "kb": kb})
        return {"ok": True}

    monkeypatch.setattr(bot, "send_message", fake_send)

    async def check():
        await db.products.delete_many({})
        await db.inventory_items.delete_many({})
        await db.products.insert_one({"_id": "empty", "name": "Produk Habis", "active": True,
                                      "product_kind": "digital", "price_idr": 10000})
        await db.products.insert_one({"_id": "ready", "name": "Jasa Tersedia", "active": True,
                                      "product_kind": "service", "price_idr": 10000})
        await bot.show_products(1, {"lang": "id", "currency": "IDR"})
        labels = str(sent[-1]["kb"])
        assert "Produk Habis" not in labels
        assert "Jasa Payment" in labels
        assert "Produk Lainnya" in labels
        from product_catalog import catalog_token
        await bot.show_products(1, {"lang": "id", "currency": "IDR"}, catalog=catalog_token({"name": "Produk Habis"}))
        assert "Produk Habis" in sent[-1]["text"]
        assert "Stok 0" in sent[-1]["text"]

    run(check())


def test_stock_notice_sends_one_image_to_each_chat(monkeypatch):
    sent = []

    async def fake_rich(method, **payload):
        sent.append((payload.get("chat_id"), payload))
        return {"ok": True, "result": {"message_id": 1}}

    from rich_table_transport import tg
    monkeypatch.setattr("rich_table_transport.tg", fake_rich)

    async def check():
        await db.products.delete_many({})
        await db.stock_events.delete_many({})
        await db.products.insert_one({"_id": "notify", "name": "Produk A", "description": "Sudah siap.",
                                      "active": True, "product_kind": "digital", "price_idr": 10000})
        await db.stock_events.insert_one({"_id": "event-1", "product_id": "notify", "event_type": "restocked",
                                          "from_count": 0, "to_count": 5, "targets": ["@channel", "-100123"],
                                          "delivered": [], "attempts": 0, "status": "pending", "created_at": "2026-01-01"})
        await stock_monitor.deliver_pending()
        assert len(sent) == 2
        for _, payload in sent:
            html = payload.get("rich_message", {}).get("html", "")
            assert "Katalog" in html
            assert "Product" in html
            assert "Penambahan/pengurangan" in html
            assert "+5" in html
            assert "Total Stock" in html
        assert (await db.stock_events.find_one({"_id": "event-1"}))["status"] == "sent"
        await stock_monitor.deliver_pending()
        assert len(sent) == 2

    run(check())
