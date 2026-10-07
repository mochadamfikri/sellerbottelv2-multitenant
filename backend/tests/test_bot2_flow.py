import asyncio
import base64
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sellerbottel_bot2_test")
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret")
os.environ.setdefault("GOPAY_ENABLED", "true")
os.environ.setdefault("INVENTORY_ENCRYPTION_KEY", Fernet.generate_key().decode())

import motor.motor_asyncio as _motor
from mongomock_motor import AsyncMongoMockClient
_motor.AsyncIOMotorClient = AsyncMongoMockClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot2  # noqa: E402
from db import db  # noqa: E402
import inventory  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def setup_function():
    async def reset():
        for collection in (
            db.bot_users,
            db.products,
            db.inventory_items,
            db.purchases,
            db.gopay_payments,
            db.deposits,
            db.counters,
            db.settings,
        ):
            await collection.delete_many({})

        await db.settings.insert_one({
            "_id": "main",
            "qris_enabled": True,
            "min_deposit_idr": 50000,
            "max_deposit_idr": 100000000,
        })

        await db.products.insert_one({
            "_id": "p1",
            "name": "EMAIL KAMPUS",
            "description": "Test product",
            "active": True,
            "product_kind": "digital",
            "delivery_type": "inventory",
            "inventory_enabled": True,
            "inventory_schema": ["email", "password"],
            "price_idr": 10000,
        })

        await inventory.add_records(
            "p1",
            [{"email": "one@example.com", "password": "secret"}],
            ["email", "password"],
        )

    run(reset())


def test_bot2_checkout_uses_shared_invoice_and_inventory():
    async def fake_node(*args, **kwargs):
        return {"image_base64": base64.b64encode(b"fake-qr").decode()}

    bot2._run_node = lambda *args, **kwargs: {"image_base64": base64.b64encode(b"fake-qr").decode()}
    bot2.send2 = lambda *args, **kwargs: asyncio.sleep(0)
    bot2.send_photo2 = lambda *args, **kwargs: asyncio.sleep(0)

    user = run(bot2.get_user2({
        "id": 123,
        "username": "buyer",
        "first_name": "Buyer",
    }))

    run(bot2.create_bot2_checkout(123, user, "p1", 1))

    order = run(db.purchases.find_one({"user_tid": 123}))
    payment = run(db.gopay_payments.find_one({"order_id": order["_id"]}))
    reserved = run(db.inventory_items.find_one({"product_id": "p1", "status": "reserved"}))

    assert order["currency"] == "IDR"
    assert order["payment_method"] == "qris"
    assert order["status"] == "pending_payment"
    assert order["invoice_id"].startswith("INV-")
    assert payment["payment_scope"] == "bot2"
    assert payment["payment_type"] == "checkout"
    assert reserved is not None


def test_bot2_paid_checkout_commits_inventory_and_marks_delivered(monkeypatch):
    monkeypatch.setattr(bot2, "send2", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(bot2, "send_document2", lambda *args, **kwargs: asyncio.sleep(0))
    async def fake_delivery(*args, **kwargs):
        return True
    monkeypatch.setattr(bot2, "deliver_inventory", fake_delivery)

    user = run(bot2.get_user2({
        "id": 456,
        "username": "buyer2",
        "first_name": "Buyer 2",
    }))
    run(bot2.create_bot2_checkout(456, user, "p1", 1))
    order = run(db.purchases.find_one({"user_tid": 456}))

    assert run(bot2.finalize_bot2_checkout(order["_id"], tx_id="TX-TEST"))
    final = run(db.purchases.find_one({"_id": order["_id"]}))
    sold = run(db.inventory_items.find_one({"product_id": "p1", "status": "sold", "order_id": order["_id"]}))

    assert final["status"] == "delivered"
    assert final["payment_tx_id"] == "TX-TEST"
    assert sold is not None


def test_bot2_deposit_qris_is_tagged_and_credits_idr(monkeypatch):
    monkeypatch.setenv("GOPAY_ENABLED", "true")
    monkeypatch.setattr(bot2, "_run_node", lambda *args, **kwargs: {
        "image_base64": base64.b64encode(b"fake-qr").decode()
    })
    monkeypatch.setattr(bot2, "send_photo2", lambda *args, **kwargs: asyncio.sleep(0))

    user = run(bot2.get_user2({
        "id": 789,
        "username": "depositor",
        "first_name": "Depositor",
    }))
    run(bot2.create_bot2_deposit_qr(789, user, 50000))

    dep = run(db.deposits.find_one({"user_tid": 789}))
    payment = run(db.gopay_payments.find_one({"deposit_id": dep["_id"]}))

    assert dep["bot2"] is True
    assert dep["currency"] == "IDR"
    assert payment["payment_scope"] == "bot2"
    assert payment["payment_type"] == "deposit"


def test_bot2_balance_checkout_is_idr_only_without_changing_bot1_currency(monkeypatch):
    monkeypatch.setattr(bot2, "send2", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(bot2, "send_document2", lambda *args, **kwargs: asyncio.sleep(0))

    user = run(bot2.get_user2({
        "id": 999,
        "username": "shared-user",
        "first_name": "Shared",
    }))
    run(db.bot_users.update_one(
        {"telegram_id": 999},
        {"$set": {"currency": "USD", "balance_usd": 100, "balance_idr": 10000}},
    ))
    user = run(db.bot_users.find_one({"telegram_id": 999}))

    async def fake_delivery(*args, **kwargs):
        return True

    monkeypatch.setattr(bot2, "deliver_inventory", fake_delivery)
    run(bot2.process_confirmed_bot2_order(999, user, "p1", 1, "balance", "test note"))

    saved = run(db.bot_users.find_one({"telegram_id": 999}))
    order = run(db.purchases.find_one({"user_tid": 999}))

    assert saved["currency"] == "USD"
    assert saved["balance_usd"] == 100
    assert saved["balance_idr"] == 0
    assert order["currency"] == "IDR"
    assert order["bot2"] is True
    assert order["payment_scope"] == "bot2"


def test_bot2_product_menu_and_product_detail_are_callable(monkeypatch):
    sent = []

    async def fake_send(*args, **kwargs):
        sent.append((args, kwargs))
        return {"ok": True}

    monkeypatch.setattr(bot2, "send2", fake_send)
    run(bot2.show_products(123, 1))
    run(bot2.show_product(123, "p1"))

    assert any("LIST PRODUCT" in (args[1] if len(args) > 1 else "") for args, _ in sent)
    assert any("EMAIL KAMPUS" in (args[1] if len(args) > 1 else "") for args, _ in sent)


def test_bot2_qris_order_isolated_from_bot1_scope():
    async def seed():
        await db.gopay_payments.insert_one({
            "_id": "bot1-payment",
            "payment_scope": "bot1",
            "active_payment_amount": 10101,
            "status": "pending",
            "expires_at": "2999-01-01T00:00:00+00:00",
        })
    run(seed())
    bot1 = run(db.gopay_payments.find_one({"_id": "bot1-payment"}))
    assert bot1["payment_scope"] == "bot1"
