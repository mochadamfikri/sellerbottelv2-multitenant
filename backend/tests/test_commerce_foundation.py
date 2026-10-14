"""C1 domain, durable routing, isolation and crash-boundary regressions."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import pytest
from mongomock_motor import AsyncMongoMockClient
from commerce.fulfillment_types import FulfillmentType, CommerceError, FulfillmentUnavailable, resolve_fulfillment_type, canonical_product
from commerce.order_items import normalize_order_items, product_for_line
from commerce.fulfillment.repository import FulfillmentRepository, ensure_fulfillment_indexes
from commerce.fulfillment.registry import registry
from commerce.fulfillment.base import FulfillmentContext


@pytest.mark.parametrize("kind", list(FulfillmentType))
def test_explicit_type_is_authoritative(kind):
    assert resolve_fulfillment_type({"fulfillment_type": kind.value, "product_kind": "service"}) == kind


@pytest.mark.parametrize("product,kind", [({}, "digital_auto"), ({"product_kind":"digital","delivery_type":"inventory"},"digital_auto"),
    ({"inventory_mode":"telegram_session","delivery_type":"inventory"},"digital_auto"), ({"delivery_type":"link"},"digital_auto"),
    ({"product_kind":"service","inventory_enabled":True},"service"), ({"delivery_type":"service"},"service")])
def test_legacy_mapping(product,kind):
    assert resolve_fulfillment_type(product)==kind


@pytest.mark.parametrize("product", [{"fulfillment_type":"bad"},{"fulfillment_type":""},{"delivery_type":"mystery"},{"product_kind":"unknown"}])
def test_unknown_classification_is_explicit_error(product):
    with pytest.raises(CommerceError): resolve_fulfillment_type(product)


@pytest.mark.parametrize("kind", ["physical","subscription","digital_manual"])
def test_future_types_are_persistable_but_not_activatable(kind):
    assert canonical_product({"fulfillment_type":kind,"active":False})["fulfillment_type"]==kind
    with pytest.raises(CommerceError): canonical_product({"fulfillment_type":kind,"active":True})


def test_snapshots_stable_after_product_edits_and_repeated_normalization():
    product={"_id":"p","name":"Original","delivery_type":"inventory","product_kind":"digital"}
    items=normalize_order_items([{"pid":"p","qty":2,"unit_price":100,"subtotal":200,"name":"Original"}],order_id="o",products={"p":product})
    product.update(product_kind="service",delivery_type="service",name="Edited",price_idr=9999)
    assert normalize_order_items(items,order_id="o",products={"p":product})==items
    historical=product_for_line(items[0],product)
    assert historical["fulfillment_type"]=="digital_auto" and historical["delivery_type"]=="inventory"
    assert historical["name"]=="Original" and items[0]["unit_price"]==100


def test_mixed_grouping_is_complete_unique_even_same_product_twice():
    rows=[{"product_id":"same","qty":1,"fulfillment_type":kind.value} for kind in FulfillmentType]
    lines=normalize_order_items(rows,order_id="mixed")
    assert len(lines)==5 and len({x["fulfillment_group_key"] for x in lines})==5
    assert {x["fulfillment_type"] for x in lines}=={k.value for k in FulfillmentType}
    with pytest.raises(CommerceError): normalize_order_items([lines[0],lines[0]],order_id="mixed")


@pytest.mark.parametrize("qty", [0,-1,1.5,True,"invalid"])
def test_invalid_quantity_rejected(qty):
    with pytest.raises(CommerceError): normalize_order_items([{"pid":"p","qty":qty}],order_id="o")


def test_record_creation_concurrency_is_local_and_idempotent():
    async def run():
        mongo=AsyncMongoMockClient()
        for name in ("a","b"):
            repo=FulfillmentRepository(mongo[name],name)
            await ensure_fulfillment_indexes(mongo[name]); await ensure_fulfillment_indexes(mongo[name])
            order={"_id":"same","tenant_id":name}
            item=normalize_order_items([{"pid":"p","qty":1}],order_id="same")[0]
            records=await asyncio.gather(*(repo.create(order,item) for _ in range(5)))
            assert len({r["_id"] for r in records})==1
            assert await mongo[name].fulfillments.count_documents({})==1
        a=FulfillmentRepository(mongo.a,"a"); b=FulfillmentRepository(mongo.b,"b")
        record=(await b.list_order("same"))[0]
        with pytest.raises(CommerceError): await a.transition(record["_id"],"delivered")
        assert (await b.list_order("same"))[0]["status"]=="reserved"
        with pytest.raises(CommerceError): await a.create({"_id":"foreign","tenant_id":"b"},item)
    asyncio.run(run())


def test_claim_concurrency_and_ambiguous_send_are_not_replayed():
    async def run():
        mongo=AsyncMongoMockClient(); repo=FulfillmentRepository(mongo.a,"a")
        item=normalize_order_items([{"pid":"p"}],order_id="o")[0]
        record=await repo.create({"_id":"o"},item)
        claims=await asyncio.gather(*(repo.claim(record) for _ in range(10)))
        assert sum(c is not None for c in claims)==1
        await repo.mark_ambiguous_claims(datetime.now(timezone.utc)+timedelta(minutes=10))
        assert await repo.claim(record) is None
        assert (await repo.list_order("o"))[0]["execution_status"]=="ambiguous"
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["physical","subscription","digital_manual"])
def test_placeholder_never_runs_digital_adapter(kind):
    async def run():
        execute=AsyncMock(return_value=True)
        context=FulfillmentContext("a",None,{"_id":"o"},{"fulfillment_type":kind},execute)
        assert await registry.get(kind).process(context)=="pending"
        execute.assert_not_awaited()
    asyncio.run(run())


def test_router_delivers_once_and_safe_failure_does_not_replay(monkeypatch):
    import commerce.fulfillment.router as router
    async def run():
        mongo=AsyncMongoMockClient(); repo=FulfillmentRepository(mongo.a,"a")
        monkeypatch.setattr(router,"current_repository",lambda:repo)
        monkeypatch.setattr(router,"require_active_context",AsyncMock())
        order={"_id":"o","status":"paid","tenant_id":"a","items":normalize_order_items([{"pid":"p"}],order_id="o")}
        await mongo.a.purchases.insert_one(order.copy())
        execute=AsyncMock(return_value=True)
        await router.ensure_order_fulfillments(order)
        assert await router.route_item(order,order["items"][0],execute)=="delivered"
        assert await router.route_item(order,order["items"][0],execute)=="delivered"
        execute.assert_awaited_once()
        order={"_id":"failure","status":"paid","items":normalize_order_items([{"pid":"p"}],order_id="failure")}
        await mongo.a.purchases.insert_one(order.copy())
        execute=AsyncMock(side_effect=RuntimeError("private inventory password should never be persisted"))
        with pytest.raises(FulfillmentUnavailable): await router.route_item(order,order["items"][0],execute)
        with pytest.raises(FulfillmentUnavailable): await router.route_item(order,order["items"][0],execute)
        execute.assert_awaited_once()
        record=(await repo.list_order("failure"))[0]
        assert record["error_detail_safe"]=="RuntimeError" and "password" not in str(record)
    asyncio.run(run())


def test_service_completion_transition_and_illegal_transition():
    async def run():
        mongo=AsyncMongoMockClient(); repo=FulfillmentRepository(mongo.a,"a")
        item=normalize_order_items([{"pid":"p","fulfillment_type":"service"}],order_id="o")[0]
        record=await repo.create({"_id":"o"},item)
        result=await repo.transition(record["_id"],"completed")
        assert result["status"]=="completed"
        assert (await repo.transition(record["_id"],"completed"))["status"]=="completed"
        with pytest.raises(CommerceError): await repo.transition(record["_id"],"queued")
    asyncio.run(run())


@pytest.mark.parametrize("price", ["bad", -1, float("nan"), float("inf")])
def test_invalid_price_is_controlled(price):
    with pytest.raises(CommerceError):
        normalize_order_items([{"pid": "p", "unit_price": price}], order_id="o")


def test_price_strings_normalize_without_string_repetition():
    line = normalize_order_items([{"pid": "p", "qty": 2, "unit_price": "100"}], order_id="o")[0]
    assert line["subtotal"] == 200


def test_backfill_dry_run_is_additive_idempotent_and_leaves_ambiguity():
    from commerce.migration import backfill_products
    async def run():
        database = AsyncMongoMockClient().migration
        await database.products.insert_many([{"_id": "legacy", "product_kind": "digital"},
            {"_id": "explicit", "fulfillment_type": "service", "product_kind": "digital"},
            {"_id": "ambiguous", "delivery_type": "unknown"}])
        original = await database.products.find().to_list(None)
        dry = await backfill_products(database, tenant_id="a")
        assert dry["candidates"] == 1 and dry["ambiguous"] == 1 and dry["changed"] == 0
        assert await database.products.find().to_list(None) == original
        assert (await backfill_products(database, tenant_id="a", apply=True))["changed"] == 1
        assert (await backfill_products(database, tenant_id="a", apply=True))["changed"] == 0
        assert (await database.products.find_one({"_id": "explicit"}))["fulfillment_type"] == "service"
        assert "fulfillment_type" not in await database.products.find_one({"_id": "ambiguous"})
    asyncio.run(run())


def test_terminal_historical_order_cannot_send_again(monkeypatch):
    import commerce.fulfillment.router as router
    async def run():
        database = AsyncMongoMockClient().a
        repo = FulfillmentRepository(database, "a")
        monkeypatch.setattr(router, "current_repository", lambda: repo)
        monkeypatch.setattr(router, "require_active_context", AsyncMock())
        order = {"_id": "history", "status": "delivered", "items": [{"pid": "p", "qty": 1}]}
        await database.purchases.insert_one(order.copy())
        await router.ensure_order_fulfillments(order)
        send = AsyncMock(return_value=True)
        assert await router.route_item(order, order["items"][0], send) == "delivered"
        send.assert_not_awaited()
    asyncio.run(run())


def test_insert_failure_refunds_wallet_and_releases_reserved_inventory(monkeypatch):
    import checkout
    import stock_monitor
    import inventory
    from db import db
    from cryptography.fernet import Fernet
    monkeypatch.setenv("INVENTORY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(stock_monitor, "schedule_stock_scan", lambda *args: None)
    monkeypatch.setattr(checkout, "ensure_order_fulfillments", AsyncMock(side_effect=RuntimeError("PRIVATE-ERROR")))
    async def run():
        await db.settings.insert_one({"_id": "main", "rate_mode": "manual", "manual_rate": 16000})
        await db.bot_users.insert_one({"telegram_id": 98127, "currency": "IDR", "balance_idr": 10000})
        await db.products.insert_one({"_id": "insert-failure", "name": "Digital", "active": True,
            "price_idr": 1000, "product_kind": "digital", "delivery_type": "inventory", "inventory_schema": ["account"]})
        await inventory.add_records("insert-failure", [{"account": "private-payload"}], ["account"])
        user = await db.bot_users.find_one({"telegram_id": 98127})
        result = await checkout.execute_checkout(user, [{"pid": "insert-failure", "qty": 1}])
        assert not result["ok"] and "PRIVATE" not in str(result)
        assert (await db.bot_users.find_one({"telegram_id": 98127}))["balance_idr"] == 10000
        assert await db.inventory_items.count_documents({"product_id": "insert-failure", "status": "available"}) == 1
        assert (await db.purchases.find_one({"items.product_id": "insert-failure"}))["status"] == "failed"
    asyncio.run(run())


def test_wrong_or_suspended_handler_context_is_rejected(monkeypatch):
    import commerce.fulfillment.router as router
    from bot_tenant_scope import BotTenantScope, use_bot_tenant
    import dependencies
    async def run():
        mongo = AsyncMongoMockClient()
        repo = FulfillmentRepository(mongo.a, "a")
        scope = BotTenantScope(tenant_id="a", slug="a", database_name="b", db_handle=mongo.b, bot_token="unused")
        async with use_bot_tenant(scope):
            with pytest.raises(CommerceError): await router.require_active_context(repo)
        scope = BotTenantScope(tenant_id="a", slug="a", database_name="a", db_handle=mongo.a, bot_token="unused")
        monkeypatch.setattr(dependencies, "get_tenant_registry", lambda: type("Registry", (), {"get_tenant": AsyncMock(return_value={"_id": "a", "database_name": "a", "status": "suspended"})})())
        async with use_bot_tenant(scope):
            with pytest.raises(CommerceError): await router.require_active_context(repo)
    asyncio.run(run())


def test_mongo_outage_returns_retryable_safe_response():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pymongo.errors import ServerSelectionTimeoutError
    from error_handlers import register_error_handlers
    app = FastAPI()
    register_error_handlers(app)
    @app.get("/fulfillment")
    async def endpoint():
        raise ServerSelectionTimeoutError("private connection material")
    with TestClient(app) as client:
        response = client.get("/fulfillment")
    assert response.status_code == 503
    assert "private" not in response.text


def test_duplicate_product_lines_receive_distinct_inventory(monkeypatch):
    import db as database_module
    import inventory
    import bot
    from cryptography.fernet import Fernet
    from commerce.fulfillment.adapters import fulfill_bot_line
    monkeypatch.setenv("INVENTORY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    database = AsyncMongoMockClient().duplicate_lines
    monkeypatch.setattr(database_module, "_default_db", database)
    monkeypatch.setattr("stock_monitor.schedule_stock_scan", lambda *args: None)
    async def run():
        product = {"_id": "p", "name": "P", "product_kind": "digital", "delivery_type": "inventory", "inventory_schema": ["account"]}
        await database.products.insert_one(product.copy())
        await inventory.add_records("p", [{"account": "first"}, {"account": "second"}], ["account"])
        reserved = await inventory.reserve_items("p", 2, "r")
        await inventory.commit_items("r", "o", 1)
        order = {"_id": "o", "status": "paid", "items": normalize_order_items([{"pid": "p"}, {"pid": "p"}], order_id="o", products={"p": product})}
        await database.purchases.insert_one(order.copy())
        send = AsyncMock(return_value=True)
        monkeypatch.setattr(bot, "deliver_inventory", send)
        for line in order["items"]:
            assert await fulfill_bot_line(order, line, product, chat_id=1, user={}, lang="id", inventory_items=reserved[-1:]) == "delivered"
        delivered = [call.args[2][0]["account"] for call in send.call_args_list]
        assert len(delivered) == 2 and len(set(delivered)) == 2
        assert await database.fulfillments.count_documents({"status": "delivered"}) == 2
    asyncio.run(run())


def test_caller_cannot_override_persisted_handler_snapshot(monkeypatch):
    import commerce.fulfillment.router as router
    async def run():
        database = AsyncMongoMockClient().a
        repo = FulfillmentRepository(database, "a")
        monkeypatch.setattr(router, "current_repository", lambda: repo)
        monkeypatch.setattr(router, "require_active_context", AsyncMock())
        order = {"_id": "o", "status": "paid", "items": normalize_order_items([{"pid": "p"}], order_id="o")}
        await database.purchases.insert_one(order.copy())
        line = {**order["items"][0], "fulfillment_type": "service"}
        send = AsyncMock(return_value=True)
        with pytest.raises(CommerceError): await router.route_item(order, line, send)
        send.assert_not_awaited()
    asyncio.run(run())


def test_service_completion_updates_record_and_legacy_order(monkeypatch):
    import db as database_module
    import admin_routes
    import bot
    database = AsyncMongoMockClient().service_completion
    monkeypatch.setattr(database_module, "_default_db", database)
    monkeypatch.setattr(bot, "send_message", AsyncMock())
    async def run():
        order = {"_id": "service-order", "status": "service_waiting", "user_tid": 7,
            "items": normalize_order_items([{"pid": "service", "fulfillment_type": "service"}], order_id="service-order")}
        await database.purchases.insert_one(order.copy())
        repo = FulfillmentRepository(database, "legacy:" + database.name)
        await repo.create(order, order["items"][0])
        assert (await admin_routes.complete_service_order(order["_id"]))["ok"]
        assert (await database.purchases.find_one({"_id": order["_id"]}))["status"] == "delivered"
        assert (await repo.list_order(order["_id"]))[0]["status"] == "completed"
    asyncio.run(run())


def test_legacy_pending_line_delivery_fact_beats_edited_product(monkeypatch):
    import commerce.fulfillment.router as router
    async def run():
        database = AsyncMongoMockClient().a
        repo = FulfillmentRepository(database, "a")
        monkeypatch.setattr(router, "current_repository", lambda: repo)
        monkeypatch.setattr(router, "require_active_context", AsyncMock())
        await database.products.insert_one({"_id": "p", "name": "Edited", "product_kind": "service", "fulfillment_type": "service"})
        order = {"_id": "old-paid", "status": "paid", "items": [{"product_id": "p", "name": "Purchased", "qty": 1, "unit_price": 100, "delivery_type": "inventory"}]}
        await database.purchases.insert_one(order.copy())
        record = (await router.ensure_order_fulfillments(order))[0]
        assert record["type"] == "digital_auto"
        assert order["items"][0]["name"] == "Purchased"
        assert (await database.purchases.find_one({"_id": order["_id"]}))["commerce_snapshot_origin"] == "legacy_reconstructed"
    asyncio.run(run())


def test_central_bot_and_owner_share_fulfillment_idempotency(monkeypatch):
    import commerce.fulfillment.router as router
    import db as database_module
    import dependencies
    from bot_tenant_scope import BotTenantScope, use_bot_tenant
    from tenant_db import resolve_platform_database_name
    import os
    async def run():
        mongo = AsyncMongoMockClient()
        monkeypatch.setattr(database_module, "client", mongo)
        database = mongo.owner
        tenant = {"_id": "owner-uuid", "slug": "owner", "database_name": database.name, "status": "active"}
        await mongo[resolve_platform_database_name(os.environ)].tenants.insert_one(tenant.copy())
        class Registry:
            async def get_tenant(self, slug):
                return tenant if slug == "owner" else None
        monkeypatch.setattr(dependencies, "get_tenant_registry", lambda: Registry())
        order = {"_id": "shared-order", "status": "paid", "items": normalize_order_items([{"pid": "p"}], order_id="shared-order")}
        await database.purchases.insert_one(order.copy())
        execute = AsyncMock(return_value=True)
        central = BotTenantScope(tenant_id="platform:central", slug="central", database_name=database.name, db_handle=database, bot_token="unused")
        owner = BotTenantScope(tenant_id="owner-uuid", slug="owner", database_name=database.name, db_handle=database, bot_token="unused")
        async with use_bot_tenant(central):
            assert await router.route_item(order, order["items"][0], execute) == "delivered"
        async with use_bot_tenant(owner):
            assert await router.route_item(order, order["items"][0], execute) == "delivered"
        execute.assert_awaited_once()
        records = await database.fulfillments.find().to_list(None)
        assert len(records) == 1 and records[0]["tenant_id"] == "owner-uuid"
    asyncio.run(run())
