"""Offline tests for central-bot direct QRIS orders and live inventory counts."""
import asyncio
import base64
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sellerbottel_direct_checkout_test")
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret")
os.environ["GOPAY_ENABLED"] = "true"
os.environ["INVENTORY_ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import motor.motor_asyncio as motor
from mongomock_motor import AsyncMongoMockClient
motor.AsyncIOMotorClient = AsyncMongoMockClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import admin_routes  # noqa: E402
import bot  # noqa: E402
import direct_checkout  # noqa: E402
import gopay_provider  # noqa: E402
import inventory  # noqa: E402
from db import db  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def setup_function():
    async def reset():
        for collection in (db.bot_users, db.products, db.inventory_items, db.purchases,
                           db.gopay_payments, db.deposits, db.counters, db.settings):
            await collection.delete_many({})
        await db.settings.insert_one({"_id": "main", "qris_enabled": True})
        await db.bot_users.insert_one({"_id": "buyer", "telegram_id": 123, "first_name": "Buyer",
            "username": "buyer", "currency": "IDR", "lang": "id", "balance_idr": 0,
            "cart": [{"pid": "p1", "qty": 1}], "state": None, "state_data": {}})
        await db.products.insert_one({"_id": "p1", "name": "Produk A", "active": True,
            "product_kind": "digital", "delivery_type": "inventory", "inventory_enabled": True,
            "inventory_schema": ["email", "password"], "price_idr": 10000})
        await inventory.add_records("p1", [{"email": "a@example.com", "password": "secret"}],
                                    ["email", "password"])
    run(reset())


def _mock_gateway(monkeypatch):
    monkeypatch.setattr(direct_checkout, "_run_node", lambda *args: {
        "image_base64": base64.b64encode(b"fake-qr").decode()})
    async def inline_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(direct_checkout.asyncio, "to_thread", inline_thread)


def test_direct_qris_reserves_then_delivers_without_deposit(monkeypatch):
    _mock_gateway(monkeypatch)
    sent = []
    async def fake_send(chat_id, text, **kwargs):
        sent.append(text)
        return {"ok": True}
    monkeypatch.setattr(bot, "send_message", fake_send)
    monkeypatch.setattr(bot, "deliver_inventory", lambda *args: asyncio.sleep(0, result=True))
    monkeypatch.setattr(direct_checkout, "notify_transaction_admin", lambda *args: asyncio.sleep(0))
    monkeypatch.setattr(direct_checkout, "notify_transaction_channel", lambda *args: asyncio.sleep(0))
    user = run(db.bot_users.find_one({"telegram_id": 123}))

    result = run(direct_checkout.create_qris_order(user, [{"pid": "p1", "qty": 1}]))
    assert result["image"] == b"fake-qr"
    order = result["order"]
    assert order["status"] == "pending_payment"
    assert order["payment_method"] == "qris"
    assert run(inventory.available_count("p1")) == 0
    assert run(db.inventory_items.count_documents({"status": "reserved"})) == 1
    assert run(db.deposits.count_documents({})) == 0

    assert run(direct_checkout.finalize_qris_order(order["_id"], "tx-1"))
    final = run(db.purchases.find_one({"_id": order["_id"]}))
    assert final["status"] == "delivered"
    assert run(db.inventory_items.count_documents({"status": "sold", "order_id": order["_id"]})) == 1
    assert run(db.bot_users.find_one({"telegram_id": 123}))["balance_idr"] == 0
    assert run(db.deposits.count_documents({})) == 0
    assert len(sent) >= 2
    assert not run(direct_checkout.finalize_qris_order(order["_id"], "tx-1"))


def test_expired_qris_releases_stock(monkeypatch):
    _mock_gateway(monkeypatch)
    monkeypatch.setattr("tgapi.send_message", lambda *args: asyncio.sleep(0, result={"ok": True}))
    user = run(db.bot_users.find_one({"telegram_id": 123}))
    result = run(direct_checkout.create_qris_order(user, [{"pid": "p1", "qty": 1}]))
    order = result["order"]
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    run(db.purchases.update_one({"_id": order["_id"]}, {"$set": {"expires_at": past}}))
    run(db.gopay_payments.update_one({"_id": order["payment_id"]}, {"$set": {"expires_at": past}}))

    run(direct_checkout.expire_qris_orders())
    assert run(db.purchases.find_one({"_id": order["_id"]}))["status"] == "expired"
    assert run(db.gopay_payments.find_one({"_id": order["payment_id"]}))["status"] == "expired"
    assert run(inventory.available_count("p1")) == 1


def test_inventory_admin_stock_never_exceeds_real_available():
    product = run(db.products.find_one({"_id": "p1"}))
    product["stock_mode"] = "manual"
    product["manual_stock"] = 20
    assert admin_routes._effective_admin_stock(product, 1) == 1
    assert admin_routes._effective_admin_stock(product, 0) == 0


def test_history_time_parsing_for_qris_match():
    assert gopay_provider._transaction_time("2026-09-24T12:00:00Z") is not None
    assert gopay_provider._transaction_time("invalid") is None


def test_old_history_transaction_cannot_pay_new_qris_order(monkeypatch):
    _mock_gateway(monkeypatch)
    user = run(db.bot_users.find_one({"telegram_id": 123}))
    result = run(direct_checkout.create_qris_order(user, [{"pid": "p1", "qty": 1}]))
    payment = result["payment"]
    old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    monkeypatch.setattr(gopay_provider, "_history", lambda: asyncio.sleep(0, result=[{
        "tx_id": "old-tx", "amount": payment["payment_amount"],
        "type": "payin", "status": "settlement", "transaction_time": old_time,
    }]))
    assert run(gopay_provider.poll_gopay_once())["matched"] == 0
    assert run(db.gopay_payments.find_one({"_id": payment["_id"]}))["status"] == "pending"


def test_payment_made_before_expiry_is_recognized_after_poll_delay(monkeypatch):
    _mock_gateway(monkeypatch)
    user = run(db.bot_users.find_one({"telegram_id": 123}))
    result = run(direct_checkout.create_qris_order(user, [{"pid": "p1", "qty": 1}]))
    order, payment = result["order"], result["payment"]
    created = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    paid = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    expired = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    run(db.purchases.update_one({"_id": order["_id"]},
                                {"$set": {"created_at": created, "expires_at": expired}}))
    run(db.gopay_payments.update_one({"_id": payment["_id"]},
                                     {"$set": {"created_at": created, "expires_at": expired}}))
    monkeypatch.setattr(gopay_provider, "_history", lambda: asyncio.sleep(0, result=[{
        "tx_id": "on-time-tx", "amount": payment["payment_amount"],
        "type": "payin", "status": "settlement", "transaction_time": paid,
    }]))
    async def fake_finalize(order_id, tx_id):
        await db.purchases.update_one({"_id": order_id}, {"$set": {"status": "delivered"}})
        return True
    monkeypatch.setattr(direct_checkout, "finalize_qris_order", fake_finalize)
    assert run(gopay_provider.poll_gopay_once())["matched"] == 1
    assert run(db.gopay_payments.find_one({"_id": payment["_id"]}))["status"] == "confirmed"
    assert run(db.purchases.find_one({"_id": order["_id"]}))["status"] == "delivered"


def test_late_qris_payment_is_flagged_for_manual_review(monkeypatch):
    _mock_gateway(monkeypatch)
    monkeypatch.setattr("tgapi.send_message", lambda *args: asyncio.sleep(0, result={"ok": True}))
    user = run(db.bot_users.find_one({"telegram_id": 123}))
    result = run(direct_checkout.create_qris_order(user, [{"pid": "p1", "qty": 1}]))
    order, payment = result["order"], result["payment"]
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    run(db.purchases.update_one({"_id": order["_id"]}, {"$set": {"expires_at": past}}))
    run(db.gopay_payments.update_one({"_id": payment["_id"]}, {"$set": {"expires_at": past}}))
    run(direct_checkout.expire_qris_orders())
    notices = []
    async def fake_notice(text):
        notices.append(text)
    monkeypatch.setattr(gopay_provider, "notify_admin", fake_notice)
    monkeypatch.setattr(gopay_provider, "_history", lambda: asyncio.sleep(0, result=[{
        "tx_id": "late-tx", "amount": payment["payment_amount"],
        "type": "payin", "status": "settlement", "transaction_time": datetime.now(timezone.utc).isoformat(),
    }]))
    assert run(gopay_provider.poll_gopay_once())["matched"] == 0
    assert len(notices) == 1
    assert run(db.gopay_late_payments.find_one({"_id": "late-tx"})) is not None


def test_bot_checkout_shows_balance_and_direct_qris(monkeypatch):
    sent = []
    async def fake_send(chat_id, text, kb=None):
        sent.append((text, kb))
        return {"ok": True}
    monkeypatch.setattr(bot, "send_message", fake_send)
    user = run(db.bot_users.find_one({"telegram_id": 123}))
    run(bot.show_payment_methods(123, user, [{"pid": "p1", "qty": 1}]))
    callbacks = [button["callback_data"] for row in sent[-1][1]["inline_keyboard"] for button in row]
    assert "pay:balance" in callbacks
    assert "pay:qris" in callbacks
    assert run(db.bot_users.find_one({"telegram_id": 123}))["state"] == "checkout_method"
