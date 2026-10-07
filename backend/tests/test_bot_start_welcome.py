"""Focused checks for the Telegram /start acceptance message."""
import asyncio

import pytest

import bot
from db import DEFAULT_SETTINGS, db


@pytest.fixture(autouse=True)
def reset_database():
    async def reset():
        for name in ("bot_users", "purchases", "promo_coupons", "settings"):
            await db[name].delete_many({})
        await db.settings.insert_one({
            **DEFAULT_SETTINGS, "_id": "main", "store_name": "Test Store Market",
        })
    asyncio.run(reset())


def test_start_welcome_renders_dynamic_profile_and_delivered_order_pcs(monkeypatch):
    sent = []

    async def capture(chat_id, text, kb=None):
        sent.append((chat_id, text, kb))

    monkeypatch.setattr(bot, "send_message", capture)

    async def run():
        user = {
            "telegram_id": 67890, "username": "johndoe", "first_name": "John",
            "currency": "USD", "balance_usd": 25.50,
            "created_at": "2023-06-20T08:15:30+00:00", "lang": "id",
        }
        await db.purchases.insert_many([
            {"_id": "delivered", "user_tid": 67890, "status": "delivered", "items": [{"qty": 3}, {"qty": 2}]},
            {"_id": "paid", "user_tid": 67890, "status": "paid", "items": [{"qty": 5}]},
            {"_id": "pending", "user_tid": 67890, "status": "pending_payment", "items": [{"qty": 10}]},
        ])
        await bot.show_start_welcome(67890, user)

    asyncio.run(run())
    _, text, _ = sent[0]
    assert "Test Store Market" in text
    assert "<b>@johndoe</b>" in text
    assert "67890" in text
    assert "<b>$25.50</b>" in text
    assert "<b>20" in text
    assert "<b>10</b> PCS" in text


def test_start_welcome_lists_only_usable_active_coupon_codes(monkeypatch):
    sent = []

    async def capture(chat_id, text, kb=None):
        sent.append((chat_id, text, kb))

    monkeypatch.setattr(bot, "send_message", capture)

    async def run():
        await db.promo_coupons.insert_many([
            {"_id": "usable", "code": "WELCOME50", "active": True, "used_count": 0},
            {"_id": "exhausted", "code": "SOLDOUT", "active": True, "quota_total": 1, "used_count": 1},
            {"_id": "inactive", "code": "EXPIRED", "active": False},
            {"_id": "future", "code": "FUTURE", "active": True, "starts_at": "2999-01-01T00:00:00+00:00"},
        ])
        await bot.show_start_welcome(11111, {
            "telegram_id": 11111, "username": "", "currency": "IDR",
            "balance_idr": 0, "created_at": "2024-01-01T00:00:00+00:00", "lang": "id",
        })

    asyncio.run(run())
    text = sent[0][1]
    assert "<code>WELCOME50</code>" in text
    assert "SOLDOUT" not in text
    assert "EXPIRED" not in text
    assert "FUTURE" not in text
    assert "<b>-</b>" in text


def test_main_menu_is_vertical_and_has_no_balance_button():
    rows = bot.main_menu_kb("id")["inline_keyboard"]
    assert all(len(row) == 1 for row in rows)
    assert all(button["callback_data"] != "menu:balance" for row in rows for button in row)


def test_start_records_first_start_and_sends_welcome_after_join_gate(monkeypatch):
    sent = []

    async def capture(chat_id, text, kb=None):
        sent.append((chat_id, text, kb))

    async def allow_join(chat_id, user):
        return True

    monkeypatch.setattr(bot, "send_message", capture)
    monkeypatch.setattr(bot, "ensure_join_gate", allow_join)

    async def run():
        await bot.handle_message({
            "chat": {"id": 1234},
            "from": {"id": 1234, "username": "newuser", "first_name": "New"},
            "text": "/start",
        })
        user = await db.bot_users.find_one({"telegram_id": 1234})
        assert user["first_start_at"]

    asyncio.run(run())
    assert len(sent) == 1
    assert "@newuser" in sent[0][1]


def test_return_to_main_uses_dynamic_start_welcome(monkeypatch):
    sent = []

    async def capture(chat_id, text, kb=None):
        sent.append((chat_id, text, kb))

    monkeypatch.setattr(bot, "send_message", capture)

    async def run():
        await bot.show_main_menu(222, {
            "telegram_id": 222, "username": "returnuser", "first_name": "Return",
            "currency": "IDR", "balance_idr": 1000,
            "created_at": "2024-01-01T00:00:00+00:00", "lang": "id",
        })

    asyncio.run(run())
    assert "Selamat Datang di Bot Store" in sent[0][1]
    assert "<b>@returnuser</b>" in sent[0][1]
