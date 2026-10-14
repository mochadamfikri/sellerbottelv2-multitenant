import asyncio
from unittest.mock import AsyncMock
import pytest
from cryptography.fernet import Fernet
from mongomock_motor import AsyncMongoMockClient
import bot_dispatcher as dispatcher
from bot_tenant_scope import BotTenantScope, use_bot_tenant, TenantScopedDict


def test_flow_state_and_join_gate_cache_are_isolated_by_bot():
    import bot
    import join_gate
    scopes = [BotTenantScope(slug=s, tenant_id=s, database_name=s, bot_token=s) for s in ("a", "b")]
    with use_bot_tenant(scopes[0]):
        bot._EDIT_TARGETS[123] = 1
        join_gate._CACHE["channel:123"] = (1, True)
        lock_a = bot._checkout_lock(123)
    with use_bot_tenant(scopes[1]):
        assert bot._EDIT_TARGETS.get(123) is None
        assert join_gate._CACHE.get("channel:123") is None
        assert bot._checkout_lock(123) is not lock_a
    with use_bot_tenant(scopes[0]):
        assert bot._EDIT_TARGETS.pop(123) == 1
        assert join_gate._CACHE["channel:123"] == (1, True)
        join_gate.clear_cache_for_user(123)


def test_suspend_and_token_rotation_restart_only_affected_worker(monkeypatch):
    desired = [({"_id": "a", "slug": "a"}, "123:begin-middle-one-end", "db-a"),
               ({"_id": "b", "slug": "b"}, "456:other", "db-b")]
    async def load():
        return list(desired)
    async def worker(*args):
        await asyncio.Event().wait()
    monkeypatch.setattr(dispatcher, "_load_active_bot_tenants", load)
    monkeypatch.setattr(dispatcher, "_load_central_bot", AsyncMock(return_value=None))
    monkeypatch.setattr(dispatcher, "_poll_worker", worker)
    monkeypatch.setattr(dispatcher, "_mark_provisioning_running", AsyncMock())
    async def run():
        supervisor = dispatcher.Dispatcher()
        await supervisor.reconcile()
        old_a, old_b = supervisor._workers["a"][0], supervisor._workers["b"][0]
        await asyncio.sleep(0)
        # Same prefix/suffix must still detect rotation in the middle.
        desired[0] = (desired[0][0], "123:begin-middle-two-end", "db-a")
        await supervisor.reconcile()
        assert old_a.cancelled()
        assert supervisor._workers["b"][0] is old_b
        rotated = supervisor._workers["a"][0]
        await asyncio.sleep(0)
        desired.pop(0)
        await supervisor.reconcile()
        assert rotated.cancelled()
        assert supervisor._workers["b"][0] is old_b
        desired.clear()
        await supervisor.reconcile()
        assert old_b.cancelled()
    asyncio.run(run())


def test_poll_worker_scopes_and_deduplicates_each_bot(monkeypatch):
    import db
    import bot
    mock = AsyncMongoMockClient()
    monkeypatch.setattr(db, "client", mock)
    seen = []
    stops = []
    class FakeHTTP:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            if url.endswith("getMe"):
                body = {"ok": True, "result": {"first_name": "Scoped Shop"}}
            else:
                stops[-1].set()
                update = {"update_id": 10, "message": {"text": "/start"}}
                body = {"ok": True, "result": [update, update]}
            class Response:
                def json(self): return body
            return Response()
    async def process(update):
        from db import db as proxy
        from bot_tenant_scope import get_current_scope
        scope = get_current_scope()
        seen.append((scope.slug, scope.bot_token, scope.database_name, scope.brand_name))
        await proxy.products.insert_one({"_id": "record", "name": scope.brand_name})
    monkeypatch.setattr(dispatcher, "_http_client", FakeHTTP)
    monkeypatch.setattr(bot, "process_update", process)
    async def run():
        for slug, token in (("a", "123:fake"), ("b", "456:fake")):
            stop = asyncio.Event()
            stops.append(stop)
            await dispatcher._poll_worker(slug, slug, "db-" + slug, token, slug.upper(), {}, [], False, stop)
        assert seen == [("a", "123:fake", "db-a", "A"), ("b", "456:fake", "db-b", "B")]
        assert (await mock["db-a"].products.find_one({"_id": "record"}))["name"] == "A"
        assert (await mock["db-b"].products.find_one({"_id": "record"}))["name"] == "B"
    asyncio.run(run())


def test_first_start_keeps_v2_idr_fallback_and_reseller_opt_in(monkeypatch):
    import bot
    from db import client
    monkeypatch.setattr(bot, "send_message", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(bot, "ensure_join_gate", AsyncMock(return_value=True))
    async def run():
        database = client["bot_start_isolation"]
        scope = BotTenantScope(slug="shop", tenant_id="shop", database_name="bot_start_isolation", db_handle=database, bot_token="123:fake", brand_name="Tenant Brand", reseller_enabled=False)
        async with use_bot_tenant(scope):
            await bot.handle_message({"chat": {"id": 123}, "from": {"id": 123, "first_name": "Customer"}, "text": "/start"})
            user = await database.bot_users.find_one({"telegram_id": 123})
            assert user.get("currency") in (None, "IDR")
            text = bot.send_message.await_args.args[1]
            assert "Rp" in text and "Tenant Brand" in text
            rows = bot.main_menu_kb("id")["inline_keyboard"]
            assert all(len(row) == 1 for row in rows)
            assert not any(row[0]["callback_data"] == "reseller:entry" for row in rows)
            scope.reseller_enabled = True
            assert any(row[0]["callback_data"] == "reseller:entry" for row in bot.main_menu_kb("id")["inline_keyboard"])
    asyncio.run(run())


def test_balance_checkout_cart_coupon_inventory_and_purchase_stay_in_one_tenant(monkeypatch):
    import inventory
    import checkout
    import stock_monitor
    from db import client
    monkeypatch.setenv("INVENTORY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(stock_monitor, "schedule_stock_scan", lambda *args: None)
    async def run():
        scopes = [BotTenantScope(slug=slug, tenant_id=slug, database_name="commerce_" + slug, db_handle=client["commerce_" + slug], bot_token=slug) for slug in ("a", "b")]
        for scope in scopes:
            async with use_bot_tenant(scope):
                database = scope.db_handle
                await database.settings.insert_one({"_id": "main", "rate_mode": "manual", "manual_rate": 16000})
                await database.bot_users.insert_one({"telegram_id": 42, "currency": "IDR", "balance_idr": 10000, "cart": [{"pid": "product", "qty": 1}]})
                await database.products.insert_one({"_id": "product", "name": scope.slug, "active": True, "product_kind": "digital", "delivery_type": "inventory", "inventory_enabled": True, "price_idr": 1000, "inventory_schema": ["account"]})
                await inventory.add_records("product", [{"account": scope.slug + "-secret"}], ["account"])
                await database.promo_coupons.insert_one({"_id": "coupon", "code": "SAMECODE", "active": True, "currency": "IDR", "type": "percent", "value": 50, "used_count": 0, "quota_total": 10})
        async with use_bot_tenant(scopes[0]):
            user = await scopes[0].db_handle.bot_users.find_one({"telegram_id": 42})
            result = await checkout.execute_checkout(user, user["cart"], coupon_code="SAMECODE")
            assert result["ok"], result
        a, b = (scope.db_handle for scope in scopes)
        assert (await a.bot_users.find_one({"telegram_id": 42}))["balance_idr"] == 9500
        assert (await b.bot_users.find_one({"telegram_id": 42}))["balance_idr"] == 10000
        assert (await a.bot_users.find_one({"telegram_id": 42}))["cart"] == []
        assert (await b.bot_users.find_one({"telegram_id": 42}))["cart"] == [{"pid": "product", "qty": 1}]
        assert (await a.promo_coupons.find_one({"_id": "coupon"}))["used_count"] == 1
        assert (await b.promo_coupons.find_one({"_id": "coupon"}))["used_count"] == 0
        assert await a.purchases.count_documents({}) == 1
        assert await b.purchases.count_documents({}) == 0
        assert await a.inventory_items.count_documents({"status": "sold"}) == 1
        assert await b.inventory_items.count_documents({"status": "available"}) == 1
    asyncio.run(run())


def test_tenant_background_jobs_inherit_database_token_and_stop_event(monkeypatch):
    from bot_tenant_scope import get_current_scope
    seen = []
    async def monitor(stop):
        scope = get_current_scope()
        seen.append((scope.slug, scope.database_name, scope.bot_token))
        await stop.wait()
    for module, name in (("gopay_provider", "run_gopay_monitor"), ("post_purchase", "run_followup"),
                         ("stock_monitor", "run_stock_monitor"), ("daily_recap", "run_daily_recap"),
                         ("marketing_campaigns", "run_marketing")):
        monkeypatch.setattr(f"{module}.{name}", monitor)
    async def run():
        stop = asyncio.Event()
        scope = BotTenantScope(slug="runtime-a", tenant_id="a", database_name="db-a", bot_token="123:tenant-a")
        tasks = await dispatcher._start_tenant_background_tasks(scope, stop)
        await asyncio.sleep(0)
        assert seen == [("runtime-a", "db-a", "123:tenant-a")] * 5
        stop.set()
        await asyncio.gather(*tasks)
        assert all(task.done() for task in tasks)
        assert get_current_scope() is None
    asyncio.run(run())
