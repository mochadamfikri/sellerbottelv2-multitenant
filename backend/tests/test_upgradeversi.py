import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from db import db
from auth import get_current_admin
import balance_admin as balance
import marketing_campaigns as marketing
import services
import telegram_identity as identity
from checkout import stock_for
from inventory import reserve_items, commit_items

ADMIN = {"_id": "admin-test"}


@pytest.fixture(autouse=True)
def fixtures(monkeypatch):
    async def reset():
        for name in ("bot_users", "store_customers", "balance_adjustments", "broadcasts", "products", "inventory_items", "stock_events", "purchases", "deposits", "settings"):
            await db[name].delete_many({})
        await db.settings.insert_one({"_id": "main", "transaction_success_channel_enabled": True, "broadcast_channel_id": "@testchannel", "cached_rate": 16000})
        await db.bot_users.insert_one({"_id": "bot1", "telegram_id": 123456789, "username": "sheimasyabania", "balance_idr": 200000, "balance_usd": 20})
        await db.store_customers.insert_many([
            {"_id": "web1", "email": "web@example.test", "balance_idr": 200000, "balance_usd": 20},
            {"_id": "linked", "telegram_id": 123456789, "balance_idr": 0, "balance_usd": 0},
        ])
        await db.products.insert_many([{"_id": p, "name": p, "catalog_name": "Claude", "active": True,
            "product_kind": "digital", "delivery_type": "inventory", "price_idr": 10000, "stock_mode": "auto"} for p in ("p1", "p2")])
        for p in ("p1", "p2"):
            await db.inventory_items.insert_many([{"_id": p+str(i), "product_id": p, "status": "available"} for i in range(10)])
    asyncio.run(reset())
    monkeypatch.setattr(marketing, "send_composed", AsyncMock(return_value={"ok": True, "result": {"message_id": 101}}))


def adjustment(direction="ADD", amount=100000, request_id="request-one", **kw):
    return balance.Adjustment(direction=direction, amount=amount, reason="Manual correction", request_id=request_id, **kw)


@pytest.mark.parametrize("target,collection,uid", [("store:web1", "store_customers", "web1"), ("bot:bot1", "bot_users", "bot1"), ("store:linked", "bot_users", "bot1")])
def test_balance_add_subtract_replay_history(target, collection, uid):
    async def run():
        results = await asyncio.gather(*[balance.adjust(target, adjustment(), ADMIN) for _ in range(8)])
        assert all(r["balance"] == 300000 for r in results)
        assert (await db[collection].find_one({"_id": uid}))["balance_idr"] == 300000
        assert await db.balance_adjustments.count_documents({}) == 1
        result = await balance.adjust(target, adjustment("SUBTRACT", 50000, "request-two"), ADMIN)
        assert result["balance"] == 250000
        history = await balance.history(target, 50)
        assert len(history) == 2
        assert history[0]["balance_before"] == 300000 and history[0]["balance_after"] == 250000
        assert history[0]["admin_id"] == "admin-test"
        assert await db.purchases.count_documents({}) == await db.deposits.count_documents({}) == 0
        if target == "store:web1":
            assert not (await db.store_customers.find_one({"_id": uid})).get("telegram_id")
        if target == "store:linked":
            assert (await db.store_customers.find_one({"_id": "linked"}))["balance_idr"] == 0
    asyncio.run(run())


def test_balance_projection_failure_and_repair(monkeypatch):
    async def run():
        original = balance.project
        monkeypatch.setattr(balance, "project", AsyncMock(side_effect=RuntimeError("projection offline")))
        result = await balance.adjust("store:web1", adjustment(), ADMIN)
        assert result["balance"] == 300000
        assert len(await balance.history("store:web1", 50)) == 1
        assert (await balance.adjust("store:web1", adjustment(), ADMIN))["replayed"]
        monkeypatch.setattr(balance, "project", original)
        await balance.repair_audits()
        assert await db.balance_adjustments.count_documents({}) == 1
    asyncio.run(run())


def test_balance_insufficient_invalid_conflict_usd():
    async def run():
        with pytest.raises(HTTPException):
            await balance.adjust("store:web1", adjustment("SUBTRACT", 999999), ADMIN)
        assert not (await db.store_customers.find_one({"_id": "web1"})).get("admin_balance_audit")
        result = await balance.adjust("store:web1", adjustment(amount=0.25, currency="USD"), ADMIN)
        assert result["balance"] == 20.25
        with pytest.raises(HTTPException):
            await balance.adjust("store:web1", adjustment(amount=1, currency="USD"), ADMIN)
        with pytest.raises(HTTPException):
            await balance.adjust("store:web1", adjustment(amount=0.2, request_id="fractional-idr"), ADMIN)
    asyncio.run(run())
    for values in ({"amount": -1}, {"amount": float("nan")}, {"currency": "EUR"}, {"reason": " "}):
        with pytest.raises(ValidationError):
            balance.Adjustment(**{"direction": "ADD", "amount": 1, "reason": "test", "request_id": "request-one", **values})


def test_auth_routes():
    async def run():
        app = FastAPI(); app.include_router(balance.router); app.include_router(marketing.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as c:
            assert (await c.get("/api/admin/wallets/store:web1/history")).status_code == 401
            assert (await c.get("/api/admin/broadcasts/campaigns")).status_code == 401
            assert (await c.post("/api/admin/wallets/store:web1/adjust", json=adjustment().model_dump())).status_code == 401
            app.dependency_overrides[get_current_admin] = lambda: ADMIN
            assert (await c.post("/api/admin/wallets/store:web1/adjust", json=adjustment().model_dump())).status_code == 200
    asyncio.run(run())


@pytest.mark.parametrize("value,expected", [(123456789,"123****89"),(1234567890,"123*****90"),("123","-"),(None,"-"),("<123456>","-"),(-123456789,"-")])
def test_mask_ids(value, expected):
    assert identity.mask_telegram_id(value) == expected


def test_identity_actual_mapping_and_failure_safe(monkeypatch):
    import broadcast_composer
    async def run():
        send = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(broadcast_composer, "send_composed", send)
        order = {"_id": "order-real", "customer_id": "linked", "invoice_id": "INV-real", "status": "delivered", "items": [{"name": "Claude", "qty": 1}], "total": 10000}
        assert (await services.notify_transaction_channel(order))["ok"]
        message = send.call_args.args[1]
        assert "123****89" in message and "@sh***********" in message
        assert "123456789" not in message and "sheimasyabania" not in message
        assert (await db.bot_users.find_one({"_id": "bot1"}))["username"] == "sheimasyabania"
        assert await identity.purchase_identity({"customer_id": "web1"}) == ("-", "-")
        monkeypatch.setattr(broadcast_composer, "send_composed", AsyncMock(side_effect=RuntimeError("offline")))
        assert not (await services.notify_transaction_channel_safely(order))["ok"]
        assert order["status"] == "delivered"
    asyncio.run(run())


async def create_campaign(count=3):
    return await marketing.create(marketing.CampaignBody(name="Promo", channel="@testchannel", minimum_interval=5, maximum_interval=70, count=count, request_id="campaign-one"), ADMIN)


async def due(cid):
    await db.broadcasts.update_one({"_id": cid}, {"$set": {"next_scheduled_at": "2000-01-01T00:00:00+00:00"}})


def test_campaign_persistence_variation_pause_resume_stop_restore():
    async def run():
        campaign = await create_campaign(); cid = campaign["_id"]
        assert (await create_campaign())["_id"] == cid
        await due(cid)
        await asyncio.gather(marketing.process(cid), marketing.process(cid))
        current = await marketing.detail(cid)
        assert current["sent"] == 1
        assert marketing.send_composed.await_count == 1
        text = marketing.send_composed.call_args.args[1]
        assert "PROMO IDSE" in text and "Bukan pemberitahuan pembelian" in text
        first = current["events"][0]
        assert await db.inventory_items.count_documents({"product_id": first["product_id"], "status": "available"}) == 9
        assert await db.inventory_items.count_documents({"status": "sold"}) == 0
        await marketing.action(cid, marketing.Action(action="pause"), ADMIN)
        await due(cid); await marketing.process(cid)
        assert marketing.send_composed.await_count == 1
        await marketing.action(cid, marketing.Action(action="resume"), ADMIN)
        assert (await marketing.detail(cid))["next_scheduled_at"] > datetime.now(timezone.utc).isoformat()
        await due(cid); await marketing.process(cid)
        current = await marketing.detail(cid)
        assert current["events"][1]["product_id"] != first["product_id"]
        await marketing.action(cid, marketing.Action(action="stop"), ADMIN)
        await due(cid); await marketing.process(cid)
        assert marketing.send_composed.await_count == 2
        assert (await marketing.restore(cid, marketing.RestoreBody(), ADMIN))["restored"] == 2
        assert (await marketing.restore(cid, marketing.RestoreBody(), ADMIN))["restored"] == 0
        assert await db.inventory_items.count_documents({"status": "available"}) == 20
        assert await db.stock_events.count_documents({"event_type": "OWNER_MARKETING_ALLOCATION"}) == 2
        assert await db.stock_events.count_documents({"event_type": "OWNER_MARKETING_RESTORE"}) == 2
        assert await db.purchases.count_documents({}) == await db.deposits.count_documents({}) == 0
    asyncio.run(run())


def test_random_delays_and_validation(monkeypatch):
    clock = datetime.now(timezone.utc)
    choices = iter([5, 13, 7, 41, 18, 63])
    monkeypatch.setattr(marketing.random, "randint", lambda a,b: next(choices))
    config = {"minimum_interval": 5, "maximum_interval": 70}
    assert [int((datetime.fromisoformat(marketing.next_time(config, clock))-clock).total_seconds()/60) for _ in range(6)] == [5,13,7,41,18,63]
    for values in ({"minimum_interval": 0}, {"minimum_interval": 10,"maximum_interval": 5}, {"count": 0}):
        with pytest.raises(ValidationError):
            marketing.CampaignBody(**{"name":"test","channel":"@testchannel","request_id":"request-one",**values})


def test_failed_send_retry_reuses_inventory_and_unknown_is_not_resent(monkeypatch):
    async def run():
        cid = (await create_campaign())["_id"]
        monkeypatch.setattr(marketing, "send_composed", AsyncMock(return_value={"ok":False,"error_code":429,"parameters":{"retry_after":120}}))
        await due(cid); await marketing.process(cid)
        current = await marketing.detail(cid)
        assert current["status"] == "failed"
        allocated = (await marketing.allocations(cid))[0]["_id"]
        assert (await marketing.restore(cid, marketing.RestoreBody(), ADMIN))["restored"] == 0
        await marketing.action(cid, marketing.Action(action="resume"), ADMIN)
        monkeypatch.setattr(marketing, "send_composed", AsyncMock(side_effect=TimeoutError()))
        await due(cid); await marketing.process(cid)
        assert (await marketing.allocations(cid))[0]["_id"] == allocated
        assert len(await marketing.allocations(cid)) == 1
        assert (await marketing.detail(cid))["events"][0]["status"] == "unknown"
        with pytest.raises(HTTPException):
            await marketing.action(cid, marketing.Action(action="resume"), ADMIN)
        await due(cid); await marketing.process(cid)
        assert marketing.send_composed.await_count == 1
        await marketing.action(cid, marketing.Action(action="confirm_sent",message_id=789), ADMIN)
        assert (await marketing.detail(cid))["sent"] == 1
    asyncio.run(run())


def test_restart_recovery_and_no_stock(monkeypatch):
    async def run():
        cid = (await create_campaign(count=1))["_id"]
        c = await db.broadcasts.find_one({"_id":cid})
        item = await marketing.allocate(c, c["events"][0])
        # Simulate process loss after allocation but before event write.
        await due(cid); await marketing.process(cid)
        assert (await marketing.detail(cid))["status"] == "completed"
        assert len(await marketing.allocations(cid)) == 1
        assert (await marketing.allocations(cid))[0]["_id"] == item["_id"]
        await db.broadcasts.delete_many({})
        cid = (await create_campaign())["_id"]
        await db.inventory_items.update_many({"status":"available"},{"$set":{"status":"reserved","reservation_id":"real-checkout"}})
        await due(cid); await marketing.process(cid)
        assert (await marketing.detail(cid))["status"] == "paused"
        assert marketing.send_composed.await_count == 1
        assert await db.inventory_items.count_documents({"reservation_id":"real-checkout","status":"reserved"}) == 19
    asyncio.run(run())


def test_customer_stock_priority_manual_cap_and_recovery_of_unknown(monkeypatch):
    async def run():
        await db.products.update_one({"_id":"p1"},{"$set":{"stock_mode":"manual","manual_stock":5}})
        body = marketing.CampaignBody(name="Manual",channel="@testchannel",count=2,product_ids=["p1"],request_id="manual-cap-test")
        cid = (await marketing.create(body,ADMIN))["_id"]
        await due(cid); await marketing.process(cid)
        product = await db.products.find_one({"_id":"p1"})
        assert await stock_for(product) == 4
        records = await reserve_items("p1", 2, "real-order")
        assert len(records) == 2
        assert not any(r.get("marketing",{}).get("event_id") for r in records)
        assert await db.inventory_items.count_documents({"status":"marketing_allocated"}) == 1
        await marketing.restore(cid,marketing.RestoreBody(),ADMIN)
        assert await stock_for(product) == 5
        assert await db.inventory_items.count_documents({"status":"reserved","reservation_id":"real-order"}) == 2
        # A stale worker marked sending before dying: new worker must not resend.
        await db.broadcasts.update_one({"_id":cid},{"$set":{"events.1.status":"sending", "lease_until":"2000-01-01T00:00:00+00:00"}})
        await due(cid); await marketing.process(cid)
        assert (await marketing.detail(cid))["events"][1]["status"] == "unknown"
        assert marketing.send_composed.await_count == 1
    asyncio.run(run())
