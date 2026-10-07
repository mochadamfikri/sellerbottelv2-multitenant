"""Offline checks for broadcast sales totals and daily deduplication."""
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1"
os.environ["DB_NAME"] = "sellerbottel_broadcast_reports_test"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret"

import motor.motor_asyncio as motor
from mongomock_motor import AsyncMongoMockClient

motor.AsyncIOMotorClient = AsyncMongoMockClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import broadcast_reports
import broadcast_composer
import daily_recap
from db import db
from PIL import Image
from io import BytesIO


def run(coro):
    return asyncio.run(coro)


def test_best_sellers_exclude_unfinished_and_allocate_discount():
    async def check():
        await db.purchases.delete_many({})
        await db.purchases.insert_many([
            {"_id": "one", "status": "delivered", "currency": "IDR", "total": 15000,
             "created_at": "2026-09-23T03:00:00+00:00", "items": [
                 {"product_id": "a", "name": "Produk A", "qty": 2, "subtotal": 10000},
                 {"product_id": "b", "name": "Produk B", "qty": 1, "subtotal": 10000}]},
            {"_id": "two", "status": "delivered", "currency": "USD", "total": 2.5,
             "created_at": "2026-09-23T05:00:00+00:00", "items": [
                 {"product_id": "a", "name": "Produk A", "qty": 1, "subtotal": 2.5}]},
            {"_id": "pending", "status": "pending", "currency": "IDR", "total": 90000,
             "created_at": "2026-09-23T06:00:00+00:00", "items": [
                 {"product_id": "b", "name": "Produk B", "qty": 99, "subtotal": 90000}]},
            {"_id": "refunded", "status": "refunded", "currency": "IDR", "total": 10000,
             "created_at": "2026-09-23T06:00:00+00:00", "items": [
                 {"product_id": "b", "name": "Produk B", "qty": 1, "subtotal": 10000}]},
        ])
        data = await broadcast_reports.sales_summary("daily_recap", day="2026-09-23")
        assert data["units"] == 4
        assert data["totals"] == {"IDR": 15000, "USD": 2.5}
        assert data["products"][0] == {"name": "Produk A", "qty": 3, "sales": {"IDR": 7500, "USD": 2.5}}
        assert "Produk A" in broadcast_reports.format_report("daily_recap", data)
        assert "Rp 15.000 + $2.50" in broadcast_reports.format_report("daily_recap", data)
        assert "Terjual: <b>3 unit</b>" in broadcast_reports.format_report("best_sellers", data)
        assert "<blockquote>" in broadcast_reports.format_report("daily_recap", data)
        for kind in ("daily_recap", "best_sellers"):
            text, image, _ = await broadcast_composer.build_content(
                broadcast_composer.ComposeBody(kind=kind, day="2026-09-23", period="all")
            )
            assert "<blockquote>" in text
            assert Image.open(BytesIO(image)).format == "JPEG"
    run(check())


def test_text_broadcast_also_gets_generated_image():
    async def check():
        text, image, _ = await broadcast_composer.build_content(
            broadcast_composer.ComposeBody(message="Promo pilihan hari ini")
        )
        assert "<blockquote>Promo pilihan hari ini</blockquote>" in text
        assert Image.open(BytesIO(image)).format == "JPEG"
    run(check())


def test_daily_recap_sends_once_per_day(monkeypatch):
    sent = []

    async def fake_chats(kind="message"):
        return ["@channel"]

    async def fake_send(body):
        sent.append(body.day)
        return {"id": "broadcast-1"}

    monkeypatch.setattr(daily_recap, "configured_chats", fake_chats)
    monkeypatch.setattr(daily_recap, "send", fake_send)

    async def check():
        await db.settings.delete_many({})
        await db.daily_recaps.delete_many({})
        await db.settings.insert_one({"_id": "main", "daily_recap_enabled": True,
                                      "daily_recap_time": "00:05", "daily_recap_target": "chats"})
        before = datetime(2026, 9, 24, 0, 4, tzinfo=ZoneInfo("Asia/Jakarta"))
        after = datetime(2026, 9, 24, 0, 5, tzinfo=ZoneInfo("Asia/Jakarta"))
        assert not await daily_recap.send_due_recap(before)
        assert await daily_recap.send_due_recap(after)
        assert not await daily_recap.send_due_recap(after)
        assert not await daily_recap.send_due_recap(datetime(2026, 9, 24, 17, 0, tzinfo=ZoneInfo("Asia/Jakarta")))
        assert sent == ["2026-09-23"]
    run(check())
