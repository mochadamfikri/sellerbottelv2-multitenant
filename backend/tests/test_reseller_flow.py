"""Offline checks for reseller pricing, subscription charges, and payouts."""
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1"
os.environ["DB_NAME"] = "sellerbottel_reseller_test"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret"

import motor.motor_asyncio as motor
from mongomock_motor import AsyncMongoMockClient

motor.AsyncIOMotorClient = AsyncMongoMockClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reseller_bot
import reseller_payout
import reseller_service
import reseller_signup
import reseller_contest
import reseller_routes
import services
from db import db


def run(coro):
    return asyncio.run(coro)


def test_live_prices_and_editable_txt_follow_central_product_price():
    async def check():
        await db.settings.delete_many({})
        await db.products.delete_many({})
        await db.inventory_items.delete_many({})
        await db.settings.insert_one({"_id": "main", "reseller_wholesale_reduction_idr": 2000})
        await db.products.insert_one({"_id": "p1", "name": "Produk A", "active": True,
                                      "product_kind": "digital", "price_idr": 10000})
        await db.inventory_items.insert_one({"_id": "i1", "product_id": "p1", "status": "available"})
        bot = {"_id": "b1", "markups": {}, "default_markup_idr": 0}
        template = (await reseller_service.price_template(bot)).decode()
        assert "p1|Produk A|8000|10000" in template
        edited = template.replace("p1|Produk A|8000|10000", "p1|Produk A|8000|15000")
        parsed = await reseller_service.parse_price_template(bot, edited.encode())
        assert parsed["markups"] == {"p1": 5000}
        product = await db.products.find_one({"_id": "p1"})
        assert (await reseller_bot.current_price({**bot, **parsed}, product))["commission"] == 7000
        await db.products.update_one({"_id": "p1"}, {"$set": {"price_idr": 12000}})
        product = await db.products.find_one({"_id": "p1"})
        updated = await reseller_bot.current_price({**bot, **parsed}, product)
        assert updated == {"public": 12000, "wholesale": 10000, "selling": 17000, "commission": 7000}
        await db.inventory_items.delete_one({"_id": "i1"})
        assert "p1|" not in (await reseller_service.price_template(bot)).decode()
    run(check())


def test_subscription_charges_once_and_renews_monthly(monkeypatch):
    async def fake_webhook(bot):
        return None

    monkeypatch.setattr(reseller_service, "configure_webhook", fake_webhook)

    async def check():
        await db.reseller_bots.delete_many({})
        await db.bot_users.delete_many({})
        await db.reseller_payments.delete_many({})
        await db.settings.delete_many({})
        await db.settings.insert_one({"_id": "main", "reseller_bot_price_idr": 80000,
                                      "reseller_admin_fee_idr": 10000,
                                      "reseller_platform_fee_idr": 10000})
        await db.bot_users.insert_one({"telegram_id": 42, "balance_idr": 250000})
        bot = {"_id": "sub1", "owner_tid": 42, "admin_tid": 42,
               "username": "reseller_bot", "status": "pending_payment", "cycle_id": "cycle1",
               "fees": {"bot_price": 80000, "admin_fee": 10000, "platform_fee": 10000, "total": 100000}}
        await db.reseller_bots.insert_one(bot)
        assert await reseller_service.activate_paid_bot(bot)
        first = await db.reseller_bots.find_one({"_id": "sub1"})
        assert first["status"] == "active" and first["expires_at"]
        assert (await db.bot_users.find_one({"telegram_id": 42}))["balance_idr"] == 150000
        assert not await reseller_service.activate_paid_bot(first)
        assert not await reseller_service.activate_paid_bot(bot)
        renewed = await reseller_service.begin_renewal(first)
        assert await reseller_service.activate_paid_bot(renewed)
        assert not await reseller_service.activate_paid_bot(renewed)
        assert (await db.bot_users.find_one({"telegram_id": 42}))["balance_idr"] == 50000
        assert await db.reseller_payments.count_documents({"bot_id": "sub1"}) == 2
        assert (await db.reseller_bots.find_one({"_id": "sub1"}))["expires_at"] > first["expires_at"]
    run(check())


def test_ewallet_payout_has_fee_and_is_only_requested_once():
    async def check():
        await db.reseller_bots.delete_many({})
        await db.reseller_commissions.delete_many({})
        await db.reseller_payouts.delete_many({})
        bot = {"_id": "pay1", "owner_tid": 42, "username": "reseller_bot",
               "payout_threshold_idr": 50000,
               "payout_destination": {"type": "EWALLET", "provider": "DANA",
                                      "number": "08123456789", "name": "Owner"}}
        await db.reseller_bots.insert_one(bot)
        await db.reseller_commissions.insert_many([
            {"_id": "o1", "bot_id": "pay1", "amount": 30000, "status": "pending_payout"},
            {"_id": "o2", "bot_id": "pay1", "amount": 30000, "status": "pending_payout"},
        ])
        payout = await reseller_payout.maybe_request_payout(bot)
        assert payout["amount"] == 60000 and payout["transfer_fee"] == 2500
        assert payout["net_amount"] == 57500
        assert not await reseller_payout.maybe_request_payout(bot)
        assert await db.reseller_payouts.count_documents({}) == 1
    run(check())


def test_reseller_checkout_charges_sale_price_and_records_margin(monkeypatch):
    sent = []

    async def fake_send(bot, tid, message, keyboard=None, persistent=False):
        sent.append(message)
        return {"ok": True}

    monkeypatch.setattr(reseller_bot, "send", fake_send)
    async def fake_admin(message):
        sent.append(message)
    monkeypatch.setattr(reseller_bot, "notify_admin", fake_admin)

    async def check():
        await db.settings.delete_many({})
        await db.products.delete_many({})
        await db.reseller_bots.delete_many({})
        await db.bot_users.delete_many({})
        await db.purchases.delete_many({})
        await db.reseller_commissions.delete_many({})
        await db.settings.insert_one({"_id": "main", "reseller_wholesale_reduction_idr": 2000})
        await db.products.insert_one({"_id": "sale-p", "name": "Link A", "active": True,
                                      "delivery_type": "link", "content": "https://example.test/a",
                                      "price_idr": 10000, "price_usd": 1})
        bot = {"_id": "sale-bot", "owner_tid": 77, "admin_tid": 77,
               "username": "reseller_bot", "status": "active", "markups": {"sale-p": 5000},
               "expires_at": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()}
        await db.reseller_bots.insert_one(bot)
        await db.bot_users.insert_one({"telegram_id": 88, "username": "buyer", "currency": "IDR",
                                       "balance_idr": 20000, "balance_usd": 0,
                                       "cart": [], "frozen": False})
        await reseller_bot.buy(bot, 88, "sale-p")
        order = await db.purchases.find_one({"reseller_bot_id": "sale-bot"})
        assert order["status"] == "delivered"
        assert order["total"] == 15000 and order["reseller_wholesale"] == 8000
        assert order["reseller_margin"] == 7000
        assert (await db.bot_users.find_one({"telegram_id": 88}))["balance_idr"] == 5000
        assert (await db.reseller_commissions.find_one({"_id": order["_id"]}))["amount"] == 7000
        assert any("berhasil dikirim" in message for message in sent)
        assert any("Penjualan melalui bot reseller" in message for message in sent)
    run(check())


def test_inactive_after_14_days_without_paid_sales_and_no_refund(monkeypatch):
    messages = []

    async def fake_message(tid, message, *args, **kwargs):
        messages.append((tid, message))

    async def fake_admin(message):
        return None

    monkeypatch.setattr(reseller_signup, "send_message", fake_message)
    monkeypatch.setattr(reseller_signup, "notify_admin", fake_admin)

    async def check():
        await db.reseller_bots.delete_many({})
        await db.purchases.delete_many({})
        await db.reseller_payouts.delete_many({})
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=15)).isoformat()
        recent = (now - timedelta(days=2)).isoformat()
        expires = (now + timedelta(days=10)).isoformat()
        await db.reseller_bots.insert_many([
            {"_id": "idle", "owner_tid": 1, "username": "idle_bot", "status": "active",
             "last_cycle_paid_at": old, "expires_at": expires},
            {"_id": "selling", "owner_tid": 2, "username": "selling_bot", "status": "active",
             "last_cycle_paid_at": old, "expires_at": expires},
            {"_id": "renewed", "owner_tid": 3, "username": "renewed_bot", "status": "active",
             "last_cycle_paid_at": recent, "expires_at": expires},
        ])
        await db.purchases.insert_many([
            {"_id": "recent-sale", "reseller_bot_id": "selling", "status": "delivered",
             "created_at": recent},
            {"_id": "unpaid", "reseller_bot_id": "idle", "status": "failed",
             "created_at": recent},
        ])
        await reseller_signup.scan_subscriptions()
        assert (await db.reseller_bots.find_one({"_id": "idle"}))["status"] == "inactive_no_sales"
        assert (await db.reseller_bots.find_one({"_id": "selling"}))["status"] == "active"
        assert (await db.reseller_bots.find_one({"_id": "renewed"}))["status"] == "active"
        assert len(messages) == 1 and "tidak dikembalikan" in messages[0][1]
        await reseller_signup.scan_subscriptions()
        assert len(messages) == 1

    run(check())


def test_contest_combines_owner_sales_and_requires_target(monkeypatch):
    notifications = []

    async def fake_admin(message):
        notifications.append(message)

    async def fake_message(tid, message):
        notifications.append(message)

    monkeypatch.setattr(reseller_contest, "notify_admin", fake_admin)
    monkeypatch.setattr(reseller_contest, "send_message", fake_message)

    async def check():
        await db.reseller_bots.delete_many({})
        await db.purchases.delete_many({})
        await db.reseller_contests.delete_many({})
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=2)).isoformat()
        end = (now - timedelta(days=1)).isoformat()
        inside = (now - timedelta(days=1, hours=12)).isoformat()
        outside = (now - timedelta(hours=12)).isoformat()
        await db.reseller_bots.insert_many([
            {"_id": "b1", "owner_tid": 1, "username": "one", "created_at": start,
             "payout_destination": {"type": "BANK", "provider": "BCA", "number": "12345678", "name": "Owner"}},
            {"_id": "b2", "owner_tid": 1, "username": "two"},
            {"_id": "b3", "owner_tid": 2, "username": "three"},
        ])
        await db.purchases.insert_many([
            {"_id": "c1", "reseller_bot_id": "b1", "status": "delivered", "currency": "IDR", "total": 600000, "paid_at": inside},
            {"_id": "c2", "reseller_bot_id": "b2", "status": "service_waiting", "currency": "IDR", "total": 500000, "paid_at": inside},
            {"_id": "c3", "reseller_bot_id": "b3", "status": "delivered", "currency": "IDR", "total": 900000, "paid_at": inside},
            {"_id": "c4", "reseller_bot_id": "b3", "status": "refunded", "currency": "IDR", "total": 1000000, "paid_at": inside},
            {"_id": "c5", "reseller_bot_id": "b3", "status": "delivered", "currency": "IDR", "total": 1000000, "paid_at": outside},
        ])
        contest = await reseller_contest.create_contest("Kontes September", start, end, 1000000, 250000)
        ranking = await reseller_contest.leaderboard(contest)
        assert ranking[0]["owner_tid"] == 1 and ranking[0]["sales_idr"] == 1100000
        assert ranking[0]["eligible"] and not ranking[1]["eligible"]
        result = await reseller_contest.settle_contest(contest)
        assert result["winner"]["owner_tid"] == 1
        assert result["winner"]["payout_destination"]["number"] == "12345678"
        assert (await db.reseller_contests.find_one({"_id": contest["_id"]}))["status"] == "winner_pending_transfer"
        assert not await reseller_contest.settle_contest(contest)
        assert len(notifications) == 2

    run(check())


def test_reseller_admin_id_receives_quote_and_qris(monkeypatch):
    import bot as central_bot
    sent = []
    qris = []

    async def fake_state(*args):
        return None

    async def fake_send(tid, message, keyboard=None):
        sent.append((tid, message, keyboard))
        return {"ok": True}

    async def fake_qris(tid, user, bot):
        qris.append((tid, bot["_id"]))

    monkeypatch.setattr(central_bot, "set_state", fake_state)
    monkeypatch.setattr(reseller_signup, "send_message", fake_send)
    monkeypatch.setattr(reseller_signup, "send_subscription_qris", fake_qris)

    async def check():
        await db.settings.delete_many({})
        await db.reseller_bots.delete_many({})
        await db.settings.insert_one({"_id": "main", "reseller_enabled": True,
                                      "reseller_bot_price_idr": 15000})
        await db.reseller_bots.insert_one({"_id": "draft", "owner_tid": 1,
                                           "username": "tester_bot", "status": "draft"})
        await reseller_signup.receive_admin(1, {"state_data": {"bot_id": "draft"}, "telegram_id": 1}, "12345")
        assert (await db.reseller_bots.find_one({"_id": "draft"}))["status"] == "pending_payment"
        assert "Rp 15.000" in sent[0][1]
        assert any("reseller:qris:draft" == button["callback_data"]
                   for row in sent[0][2]["inline_keyboard"] for button in row)
        assert qris == [(1, "draft")]

    run(check())


def test_reseller_join_gate_and_message_replacement(monkeypatch):
    calls = []

    async def fake_telegram(token, method, **payload):
        calls.append(method)
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 99}}
        return {"ok": True}

    async def fake_membership(tid, force_refresh=False):
        return False, [{"channel_id": "-1001", "username": "sellerbottel", "title": "SellerBottel"}]

    monkeypatch.setattr(reseller_bot, "telegram_call", fake_telegram)
    monkeypatch.setattr(reseller_bot, "decrypt_token", lambda bot: "test-token")
    monkeypatch.setattr(reseller_bot, "check_user_membership", fake_membership)

    async def check():
        await db.reseller_bot_users.delete_many({})
        await db.reseller_bot_users.insert_one({"bot_id": "gate", "telegram_id": 77})
        bot = {"_id": "gate", "status": "active", "expires_at":
               (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}
        update = {"message": {"from": {"id": 77}, "chat": {"type": "private"}, "text": "/start"}}
        await reseller_bot.process_reseller_update(bot, update)
        await reseller_bot.process_reseller_update(bot, update)
        assert calls == ["sendMessage", "editMessageText"]
        assert (await db.reseller_bot_users.find_one({"bot_id": "gate", "telegram_id": 77}))["last_ui_message_id"] == 99

    run(check())


def test_admin_can_block_bot_and_owner_cannot_renew(monkeypatch):
    import tgapi

    async def fake_message(*args, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(tgapi, "send_message", fake_message)

    async def check():
        await db.reseller_bots.delete_many({})
        await db.reseller_bots.insert_one({"_id": "fraud", "owner_tid": 1,
                                           "status": "active", "username": "fraud_bot",
                                           "expires_at": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()})
        await reseller_routes.block_reseller("fraud", reseller_routes.BlockInput(reason="Pemeriksaan transaksi"))
        blocked = await db.reseller_bots.find_one({"_id": "fraud"})
        assert blocked["status"] == "blocked"
        try:
            await reseller_service.begin_renewal(blocked)
        except ValueError:
            pass
        else:
            assert False, "Blocked bot must not renew"

    run(check())


def test_subscription_qris_is_sent_immediately_after_quote(monkeypatch):
    photos = []

    async def fake_payment(user, amount):
        assert amount == 15000
        return {"deposit": {"_id": "dep-1"}, "image": b"jpeg",
                "payment_amount": 15312, "expires_at": datetime.now(timezone.utc)}

    async def fake_photo(tid, image, filename, caption=None):
        photos.append((tid, caption))
        return {"ok": True}

    monkeypatch.setenv("GOPAY_ENABLED", "true")
    monkeypatch.setattr(reseller_signup, "create_gopay_payment", fake_payment)
    monkeypatch.setattr(reseller_signup, "send_photo_bytes", fake_photo)

    async def check():
        await db.settings.delete_many({})
        await db.reseller_bots.delete_many({})
        await db.settings.insert_one({"_id": "main", "qris_enabled": True})
        await db.reseller_bots.insert_one({"_id": "qris-bot", "owner_tid": 1,
                                           "status": "pending_payment", "username": "tester_bot"})
        bot = {"_id": "qris-bot", "username": "tester_bot", "fees": {"total": 15000}}
        await reseller_signup.send_subscription_qris(1, {"telegram_id": 1}, bot)
        assert (await db.reseller_bots.find_one({"_id": "qris-bot"}))["activation_deposit_id"] == "dep-1"
        assert len(photos) == 1 and "15312" not in photos[0][1]
        assert "15.312" in photos[0][1]

    run(check())


def test_central_sales_send_images_to_admin_and_channel(monkeypatch):
    photos = []

    async def fake_photo(tid, image, filename, caption=None):
        photos.append((tid, image[:2], caption))
        return {"ok": True}

    async def fake_channel():
        return "-1001"

    monkeypatch.setattr(services, "send_photo_bytes", fake_photo)
    monkeypatch.setattr(services, "_broadcast_channel_id", fake_channel)

    async def check():
        await db.settings.delete_many({})
        await db.settings.insert_one({"_id": "main", "admin_telegram_id": 99})
        order = {"invoice_id": "INV-1", "items": [{"name": "Produk A", "qty": 1}],
                 "total": 15000, "currency": "IDR", "status": "delivered"}
        await services.notify_transaction_admin(order, "Pembeli")
        await services.notify_transaction_channel(order)
        assert [row[0] for row in photos] == [99, "-1001"]
        assert all(row[1] == b"\xff\xd8" for row in photos)

    run(check())


def test_admin_reseller_detail_serializes_mongo_object_ids():
    async def check():
        await db.reseller_bots.delete_many({})
        await db.reseller_bot_users.delete_many({})
        await db.reseller_bots.insert_one({"_id": "detail-test", "owner_tid": 1,
                                           "username": "tester_bot", "status": "active",
                                           "created_at": datetime.now(timezone.utc).isoformat()})
        await db.reseller_bot_users.insert_one({"bot_id": "detail-test", "telegram_id": 2,
                                                 "created_at": datetime.now(timezone.utc).isoformat()})
        detail = await reseller_routes.reseller_detail("detail-test")
        assert detail["recent_users"][0]["telegram_id"] == 2
        assert isinstance(detail["recent_users"][0]["_id"], str)
        json.dumps(detail)

    run(check())
