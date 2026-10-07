"""Offline hotfix acceptance tests: order channel is independent of account source."""
import asyncio
import base64
import copy
from unittest.mock import AsyncMock
import pytest
from db import db
import services
import broadcast_composer
import checkout
import direct_checkout
from telegram_identity import purchase_source


@pytest.fixture(autouse=True)
def fixtures(monkeypatch):
    async def reset():
        for name in ("settings", "bot_users", "store_customers", "purchases", "products", "inventory_items", "deposits", "gopay_payments", "counters", "discounts", "promo_coupons"):
            await db[name].delete_many({})
        await db.settings.insert_one({"_id":"main", "transaction_success_channel_enabled":True,
            "broadcast_channel_id":"@offlinechannel", "broadcast_auto_image_enabled":True,
            "qris_enabled":True, "store_qris_enabled":True, "rate_mode":"manual", "manual_rate":16000})
        await db.bot_users.insert_one({"_id":"bot", "telegram_id":123456789, "username":"sheimasyabania",
            "currency":"IDR", "balance_idr":100000, "registration_source":"WEB"})
        await db.store_customers.insert_many([
            {"_id":"unlinked", "email":"unlinked@example.test", "balance_idr":100000, "registration_source":"WEB"},
            {"_id":"linked", "email":"linked@example.test", "telegram_id":123456789, "registration_source":"BOT"},
        ])
        await db.products.insert_one({"_id":"p", "name":"Claude Pro", "active":True, "product_kind":"digital",
            "delivery_type":"inventory", "price_idr":10000})
        await db.inventory_items.insert_many([{"_id":str(i),"product_id":"p","status":"available"} for i in range(10)])
    asyncio.run(reset())
    import stock_monitor
    monkeypatch.setattr(stock_monitor, "schedule_stock_scan", lambda *args:None)


@pytest.mark.parametrize("source,customer,registration", [
    ("WEB","unlinked","WEB"), ("WEB","linked","WEB"), ("BOT","linked","BOT"),
    ("BOT","linked","WEB"), ("WEB","linked","BOT"),
])
def test_five_acceptance_cases(source, customer, registration, monkeypatch):
    async def run():
        order={"_id":"real-order", "invoice_id":"INV-test", "purchase_source":source,
            "customer_id":customer, "registration_source":registration, "source_kind":registration,
            "status":"delivered", "total":10000, "currency":"IDR", "items":[{"name":"Claude Pro","qty":1}]}
        if customer=="linked": order["user_tid"]=123456789
        original=copy.deepcopy(order)
        bot=await db.bot_users.find_one({"_id":"bot"})
        send=AsyncMock(return_value={"ok":True})
        image=object()
        monkeypatch.setattr(broadcast_composer,"send_composed",send)
        monkeypatch.setattr(services,"_transaction_image",lambda *_:image)
        assert (await services.notify_transaction_channel(order))["ok"]
        _, text, actual_image=send.call_args.args
        assert actual_image is image
        assert f"Sumber: {source}" in text
        assert ("🌐 <b>Penjualan Web</b>" if source=="WEB" else "🤖 <b>Penjualan Bot</b>") in text
        assert "Invoice:" in text and "Produk: Claude Pro ×1" in text and "delivered" in text
        assert "User ID: -" not in text and "Username: -" not in text
        if customer=="unlinked":
            assert "Telegram ID:" not in text and "Username:" not in text
        else:
            assert "Telegram ID: 123****89" in text and "Username: @sh***********" in text
        assert "123456789" not in text and "sheimasyabania" not in text and "@example.test" not in text
        assert order==original and await db.bot_users.find_one({"_id":"bot"})==bot
    asyncio.run(run())


@pytest.mark.parametrize("metadata,expected", [
    ({"payment_scope":"store","user_tid":123456789},"WEB"),
    ({"payment_scope":"bot1","customer_id":"linked","source_kind":"WEB"},"BOT"),
    ({"bot2":True,"customer_id":"linked"},"BOT"),
    ({"reseller_bot_id":"r"},"BOT"),
    ({"customer_id":"linked","idempotency_key":"web-checkout"},"WEB"),
    ({"customer_id":"linked","user_tid":123456789,"source_kind":"WEB"},"TIDAK DIKETAHUI"),
    ({"purchase_source":"WEB","payment_scope":"bot1"},"WEB"),
])
def test_legacy_metadata_only(metadata,expected):
    assert purchase_source(metadata)==expected


@pytest.mark.parametrize("source,customer", [("WEB","unlinked"),("WEB","linked"),("BOT","linked")])
def test_balance_creation_persists_checkout_channel(source,customer):
    async def run():
        user=await db.store_customers.find_one({"_id":customer})
        user.update(customer_id=customer,currency="IDR")
        if source=="BOT":
            # A web-registered/linked buyer uses the bot path, not a web wallet inference.
            user={**(await db.bot_users.find_one({"_id":"bot"})),"customer_id":"linked"}
        result=await checkout.execute_checkout(user,[{"pid":"p","qty":1}],purchase_source=source)
        assert result["ok"], result
        persisted=await db.purchases.find_one({"_id":result["order"]["_id"]})
        assert persisted["purchase_source"]==source
        assert await db.inventory_items.count_documents({"status":"sold"})==1
        assert persisted["total"]==10000
    asyncio.run(run())


@pytest.mark.parametrize("source",["WEB","BOT"])
def test_qris_creation_persists_checkout_channel(source,monkeypatch):
    monkeypatch.setenv("GOPAY_ENABLED","true")
    monkeypatch.setenv("STORE_QRIS_ENABLED","true")
    monkeypatch.setattr(direct_checkout,"_run_node",lambda *args:{"image_base64":base64.b64encode(b"offline-qr").decode()})
    async def run():
        if source=="WEB":
            buyer=await db.store_customers.find_one({"_id":"linked"})
            result=await direct_checkout.create_store_qris_order(buyer,[{"pid":"p","qty":1}],idempotency_key="hotfix-web-qr")
        else:
            buyer=await db.bot_users.find_one({"_id":"bot"})
            result=await direct_checkout.create_qris_order(buyer,[{"pid":"p","qty":1}])
        order=await db.purchases.find_one({"_id":result["order"]["_id"]})
        assert order["purchase_source"]==source
        assert order["customer_id"]=="linked"  # linking is deliberately identical on both paths
        assert await db.inventory_items.count_documents({"status":"reserved"})==1
        assert await db.deposits.count_documents({})==0
    asyncio.run(run())
