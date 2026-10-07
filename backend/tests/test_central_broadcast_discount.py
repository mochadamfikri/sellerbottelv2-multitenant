"""Central broadcast templates and visible checkout discount regression tests."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1"
os.environ["DB_NAME"] = "sellerbottel_central_broadcast_test"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret"

import motor.motor_asyncio as motor
from mongomock_motor import AsyncMongoMockClient

motor.AsyncIOMotorClient = AsyncMongoMockClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot
from admin_routes import DiscountBody, create_discount
from broadcast_composer import ComposeBody, build_content
from checkout import execute_checkout
from db import db


def run(coro):
    return asyncio.run(coro)


def test_admin_discount_reduces_cart_and_checkout_total(monkeypatch):
    messages = []

    async def fake_send(chat_id, text, kb=None):
        messages.append(text)
        return {"ok": True}

    monkeypatch.setattr(bot, "send_message", fake_send)

    async def check():
        for collection in (db.products, db.discounts, db.bot_users, db.purchases, db.counters):
            await collection.delete_many({})
        await db.products.insert_one({"_id": "p1", "name": "Produk A", "active": True,
                                      "delivery_type": "link", "price_idr": 10000, "price_usd": 1})
        saved = await create_discount(DiscountBody(name="Promo 20 Persen", active=True,
                                                   product_ids=["p1"], mode="percent", value=20))
        assert await db.discounts.count_documents({"_id": saved["_id"], "active": True}) == 1
        user = {"telegram_id": 1, "username": "buyer", "currency": "IDR",
                "balance_idr": 20000, "cart": [{"pid": "p1", "qty": 2}], "frozen": False}
        await db.bot_users.insert_one(user)
        await bot.show_cart(1, user)
        assert "Promo 20 Persen" in messages[-1]
        assert "Rp 4.000" in messages[-1]
        assert "Rp 16.000" in messages[-1]
        result = await execute_checkout(user, [{"pid": "p1", "qty": 2}])
        assert result["ok"]
        assert result["order"]["total"] == 16000
        assert result["order"]["discount_total"] == 4000
        assert (await db.bot_users.find_one({"telegram_id": 1}))["balance_idr"] == 4000

    run(check())


def test_coupon_replaces_product_discount_without_double_counting():
    async def check():
        for collection in (db.products, db.discounts, db.bot_users, db.purchases,
                           db.counters, db.promo_coupons, db.promo_coupon_redemptions):
            await collection.delete_many({})
        await db.products.insert_one({"_id": "p2", "name": "Produk B", "active": True,
                                      "delivery_type": "link", "price_idr": 10000, "price_usd": 1})
        await db.discounts.insert_one({"_id": "d2", "name": "Promo 20", "active": True,
                                       "product_ids": ["p2"], "mode": "percent", "value": 20,
                                       "min_qty": 1})
        await db.promo_coupons.insert_one({"_id": "c1", "code": "PROMO50", "active": True,
                                           "type": "percent", "value": 50, "currency": "IDR",
                                           "per_user_limit": 1, "min_purchase": 0,
                                           "product_ids": [], "used_count": 0, "quota_total": 10})
        user = {"telegram_id": 2, "username": "buyer", "currency": "IDR",
                "balance_idr": 10000, "cart": [], "frozen": False}
        await db.bot_users.insert_one(user)
        result = await execute_checkout(user, [{"pid": "p2", "qty": 1}], coupon_code="PROMO50")
        assert result["ok"]
        assert result["order"]["total"] == 5000
        assert result["order"]["discount_total"] == 5000
        assert result["order"]["coupon_discount"] == 3000
        assert (await db.bot_users.find_one({"telegram_id": 2}))["balance_idr"] == 5000

    run(check())


def test_live_broadcast_templates_generate_jpeg_and_reseller_tutorial():
    async def check():
        for collection in (db.settings, db.reseller_contests, db.discounts, db.promo_coupons,
                           db.products, db.inventory_items):
            await collection.delete_many({})
        await db.settings.insert_one({"_id": "main", "reseller_enabled": True,
                                      "reseller_bot_price_idr": 15000,
                                      "reseller_admin_fee_idr": 1000,
                                      "reseller_platform_fee_idr": 500,
                                      "reseller_wholesale_reduction_idr": 2000})
        text, image, products = await build_content(
            ComposeBody(kind="system_update", topic="reseller_guide", target="chats"))
        assert "@BotFather" in text and "/newbot" in text
        assert "/id" in text and "@Idse_MarketBot" in text
        assert "Rp 16.500" in text and "14 hari" in text
        assert image[:2] == b"\xff\xd8" and not products
        assert len(text) <= 4000

        await db.discounts.insert_one({"_id": "d3", "name": "Diskon A", "active": True,
                                       "product_ids": [], "mode": "percent", "value": 10,
                                       "min_qty": 1})
        text, image, _ = await build_content(
            ComposeBody(kind="system_update", topic="discount", reference_id="d3"))
        assert "10%" in text and "Diskon A" in text and image[:2] == b"\xff\xd8"

    run(check())


def test_central_templates_use_live_contest_coupon_and_product_data():
    async def check():
        for collection in (db.settings, db.reseller_contests, db.discounts,
                           db.promo_coupons, db.products):
            await collection.delete_many({})
        await db.settings.insert_one({"_id": "main", "qris_enabled": True,
                                      "bank_enabled": False})
        now = datetime.now(timezone.utc)
        await db.reseller_contests.insert_one({"_id": "contest1", "name": "Kontes Oktober",
                                               "status": "active", "starts_at": now.isoformat(),
                                               "ends_at": (now + timedelta(days=7)).isoformat(),
                                               "target_sales_idr": 2000000, "prize_idr": 300000})
        await db.promo_coupons.insert_one({"_id": "coupon1", "code": "HEMAT20",
                                           "active": True, "type": "percent", "value": 20,
                                           "currency": "IDR", "min_purchase": 50000,
                                           "per_user_limit": 1, "used_count": 0, "quota_total": 100})
        await db.products.insert_one({"_id": "product1", "name": "Produk C", "active": True,
                                      "description": "Akun premium", "delivery_type": "link",
                                      "price_idr": 10000, "price_usd": 1, "stock": 5})
        scenarios = [
            ("reseller_contest", "contest1", "Rp 300.000"),
            ("coupon", "coupon1", "HEMAT20"),
            ("product_restock", "product1", "Produk C"),
            ("deposit_guide", "", "QRIS"),
        ]
        for topic, ref, marker in scenarios:
            text, image, _ = await build_content(ComposeBody(
                kind="system_update", topic=topic, reference_id=ref))
            assert marker in text and image[:2] == b"\xff\xd8"
        text, image, _ = await build_content(ComposeBody(
            kind="system_update", topic="announcement", title="Fitur Baru", message="Sekarang tersedia."))
        assert "Fitur Baru" in text and image[:2] == b"\xff\xd8"

    run(check())
