"""C1 acceptance on dedicated dev Mongo: isolated fresh databases, no .env/reset.

HTTP API uses localhost:8003. Delivery/provider/notification transports are mocked;
Mongo, tenant scopes, orders, reservations, fulfillment claims and indexes are real.
Never sends Telegram messages, mail or real payment requests.
"""
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from cryptography.fernet import Fernet
nonce = secrets.token_hex(4)
ENV = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "PYTHON_DOTENV_DISABLED": "1",
    "ENVIRONMENT": "development", "MONGO_URL": "mongodb://127.0.0.1:27019/?serverSelectionTimeoutMS=1500",
    "DB_NAME": "sellerbottel_c1_dev_" + nonce, "PLATFORM_DB_NAME": "sellerbottel_c1_dev_" + nonce,
    "JWT_SECRET": secrets.token_urlsafe(48), "INVENTORY_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "TELEGRAM_WEBHOOK_SECRET": secrets.token_urlsafe(32), "CORS_ORIGINS": "http://127.0.0.1:3003",
    "TENANT_BASE_DOMAIN": "c1.invalid", "ADMIN_EMAIL": "admin@c1.invalid", "ADMIN_PASSWORD": secrets.token_urlsafe(24),
    "GOPAY_ENABLED": "false", "BOT2_ENABLED": "false", "PROMOTION_ENABLED": "false",
    "LOCAL_STORAGE_DIR": str(ROOT / "backend/storage_data/c1-dev")}
os.environ.clear()
os.environ.update(ENV)
import httpx
from db import client
from bot_tenant_scope import BotTenantScope, use_bot_tenant
from commerce.fulfillment.repository import FulfillmentRepository, ensure_fulfillment_indexes
from commerce.fulfillment.router import ensure_order_fulfillments, route_item
from commerce.fulfillment.adapters import fulfill_bot_line, fulfill_web_order
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from commerce.order_items import normalize_order_items
from commerce.migration import backfill_products
import checkout
import inventory
import direct_checkout

EVIDENCE = ROOT / "test_reports/phase-c1-commerce-foundation-20261008"
EVIDENCE.mkdir(parents=True, exist_ok=True)
results = []
proc = None
log = None

def check(name, condition):
    results.append({"test": name, "result": "PASS" if condition else "FAIL"})
    if not condition:
        raise AssertionError(name)

def start():
    global proc, log
    log = (EVIDENCE / "runtime.log").open("a")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8003"],
        cwd=ROOT / "backend", env=ENV, stdout=log, stderr=subprocess.STDOUT)

def stop():
    if proc and proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
    if log: log.close()

async def ready(http):
    for _ in range(100):
        if proc.poll() is not None: raise AssertionError("Backend startup failed")
        try:
            if (await http.get("/api/")).status_code == 200: return
        except httpx.TransportError: pass
        await asyncio.sleep(.2)
    raise AssertionError("Backend readiness timeout")

async def run():
    # Repeated isolated tenant runs open many WiredTiger files. Fail before
    # writing if the dedicated container inherited Docker's low soft limit.
    limits = subprocess.check_output(["sudo", "-n", "docker", "exec", "sellerbottelv2-dev-mongo", "cat", "/proc/1/limits"], text=True)
    file_limit = next(row.split()[3] for row in limits.splitlines() if row.startswith("Max open files"))
    check("dedicated Mongo file limit sufficient", file_limit == "unlimited" or int(file_limit) >= 65535)
    platform = client[ENV["DB_NAME"]]
    check("dedicated Mongo ping", (await client.admin.command("ping"))["ok"] == 1)
    retained = client.sellerbottel_live_e2e_dev
    before = await retained.tenants.count_documents({})
    check("fresh isolated C1 platform", not await platform.list_collection_names())
    start()
    scopes, headers = [], []
    password = secrets.token_urlsafe(24)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8003", timeout=20) as http:
        await ready(http)
        check("HTTP backend startup", True)
        for label in "ab":
            slug = "c1-" + label + "-" + nonce
            email = slug + "@gmail.com"
            verified = secrets.token_urlsafe(24)
            await platform.public_reg_verified.insert_one({"email": email, "verify_token": verified, "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)})
            response = await http.post("/api/public/register", json={"username": slug, "email": email, "store_name": "C1 " + label,
                "password": password, "whatsapp": "081234567890", "verify_token": verified})
            check("HTTP tenant provisioning " + label, response.status_code == 201)
            tenant = await platform.tenants.find_one({"slug": slug})
            database = client[tenant["database_name"]]
            scopes.append(BotTenantScope(tenant_id=str(tenant["_id"]), slug=slug, database_name=database.name, db_handle=database, bot_token="unused"))
            response = await http.post("/api/public/tenant/login", json={"email": email, "password": password})
            check("HTTP owner login " + label, response.status_code == 200)
            token = response.json().get("access_token") or response.json().get("token")
            headers.append({"Authorization": "Bearer " + token})
            response = await http.post("/api/public/tenant/full/products", headers=headers[-1], data={"name": "Canonical product", "price_usd": "1", "delivery_type": "inventory"})
            check("HTTP canonical product write " + label, response.status_code == 200 and (await database.products.find_one({"name": "Canonical product"}))["fulfillment_type"] == "digital_auto")
            indexes = await database.fulfillments.index_information()
            check("real unique fulfillment index " + label, indexes["fulfillment_order_line_unique"]["unique"])
            await database.settings.update_one({"_id": "main"}, {"$set": {"rate_mode": "manual", "manual_rate": 16000, "store_qris_enabled": True}})
            await database.bot_users.insert_one({"telegram_id": 991127, "currency": "IDR", "balance_idr": 10000, "cart": []})
            await database.products.insert_many([{"_id": "digital", "name": "Digital original", "active": True, "price_idr": 1000,
                "product_kind": "digital", "delivery_type": "inventory", "inventory_schema": ["account"]},
                {"_id": "service", "name": "Service", "active": True, "price_idr": 1000, "product_kind": "service", "delivery_type": "service"}])
            async with use_bot_tenant(scopes[-1]):
                with patch("stock_monitor.schedule_stock_scan", lambda *args: None):
                    await inventory.add_records("digital", [{"account": "private-" + label + str(i)} for i in range(7)], ["account"])
        for i, scope in enumerate(scopes):
            async with use_bot_tenant(scope):
                database = scope.db_handle
                repo = FulfillmentRepository(database, scope.tenant_id)
                user = await database.bot_users.find_one({"telegram_id": 991127})
                with patch("stock_monitor.schedule_stock_scan", lambda *args: None):
                    result = await checkout.execute_checkout(user, [{"pid": "digital", "qty": 1}, {"pid": "service", "qty": 1}])
                check("real legacy digital/service balance checkout " + scope.slug, result["ok"])
                order = result["order"]
                records = await repo.list_order(order["_id"])
                check("mixed paid records complete and unique " + scope.slug, len(records) == 2 and {r["type"] for r in records} == {"digital_auto", "service"})
                send = AsyncMock(return_value=True)
                queue = AsyncMock()
                with patch("bot.deliver_inventory", send):
                    for line in order["items"]:
                        current = await database.products.find_one({"_id": line["product_id"]})
                        await fulfill_bot_line(order, line, current, chat_id=991127, user=user, lang="id", queue_service_fn=queue)
                        await fulfill_bot_line(order, line, current, chat_id=991127, user=user, lang="id", queue_service_fn=queue)
                check("repeated real routing sends once " + scope.slug, send.await_count == 1 and queue.await_count == 1)
                await database.purchases.update_one({"_id": order["_id"]}, {"$set": {"status": "service_waiting"}})
                response = await http.get("/api/public/tenant/full/orders/" + order["_id"] + "/fulfillments", headers=headers[i])
                check("HTTP fulfillment read " + scope.slug, response.status_code == 200 and len(response.json()) == 2)
                response = await http.get("/api/public/tenant/full/orders/" + order["_id"] + "/fulfillments", headers=headers[1-i])
                check("foreign HTTP fulfillment denied " + scope.slug, response.status_code == 404)
                with patch("admin_routes.db", database), patch("bot.send_message", AsyncMock()):
                    from admin_routes import complete_service_order
                    await complete_service_order(order["_id"])
                check("service completion record " + scope.slug, {r["status"] for r in await repo.list_order(order["_id"])} == {"completed", "delivered"})
                # Snapshot remains digital even after live classification changes.
                with patch("stock_monitor.schedule_stock_scan", lambda *args: None):
                    result = await checkout.execute_checkout(user, [{"pid": "digital", "qty": 1}])
                frozen = result["order"]
                await database.products.update_one({"_id": "digital"}, {"$set": {"product_kind": "service", "delivery_type": "service", "name": "Edited"}})
                send = AsyncMock(return_value=True)
                with patch("bot.deliver_inventory", send):
                    state = await fulfill_bot_line(frozen, frozen["items"][0], await database.products.find_one({"_id": "digital"}), chat_id=991127, user=user, lang="id")
                check("historical snapshot routing after edit " + scope.slug, state == "delivered" and send.await_count == 1 and send.call_args.args[1]["name"] == "Digital original")
                await database.products.update_one({"_id": "digital"}, {"$set": {"product_kind": "digital", "delivery_type": "inventory", "name": "Digital original"}})
                # Concurrent claim and identical order IDs across databases.
                mixed = {"_id": "identical-order-id", "status": "paid", "items": normalize_order_items([
                    {"pid": "digital", "fulfillment_type": "digital_auto"}, {"pid": "service", "fulfillment_type": "service"},
                    {"pid": "future", "fulfillment_type": "physical"}], order_id="identical-order-id")}
                await database.purchases.insert_one(mixed.copy())
                await asyncio.gather(*(ensure_order_fulfillments(mixed) for _ in range(8)))
                check("concurrent paid event unique records " + scope.slug, len(await repo.list_order(mixed["_id"])) == 3)
                send = AsyncMock(return_value=True)
                await asyncio.gather(*(route_item(mixed, mixed["items"][0], send) for _ in range(8)), return_exceptions=True)
                check("concurrent real claims one delivery " + scope.slug, send.await_count == 1)
                future = AsyncMock()
                check("physical placeholder pending " + scope.slug, await route_item(mixed, mixed["items"][2], future) == "pending" and future.await_count == 0)
                failure = {"_id": "handler-failure", "status": "paid", "items": normalize_order_items([{"pid": "digital"}], order_id="handler-failure")}
                await database.purchases.insert_one(failure.copy())
                send = AsyncMock(side_effect=RuntimeError("PRIVATE-PAYLOAD"))
                for _ in range(2):
                    try: await route_item(failure, failure["items"][0], send)
                    except FulfillmentUnavailable: pass
                check("handler failure safe and never replayed " + scope.slug, send.await_count == 1 and "PRIVATE" not in str(await repo.list_order(failure["_id"])))
                with patch("checkout.ensure_order_fulfillments", AsyncMock(side_effect=RuntimeError("PRIVATE-INSERT"))), patch("stock_monitor.schedule_stock_scan", lambda *args: None):
                    balance = (await database.bot_users.find_one({"telegram_id": 991127}))["balance_idr"]
                    count = await inventory.available_count("digital")
                    failed = await checkout.execute_checkout(user, [{"pid": "digital", "qty": 1}])
                check("real insert failure compensates wallet and reservation " + scope.slug, not failed["ok"] and balance == (await database.bot_users.find_one({"telegram_id": 991127}))["balance_idr"] and count == await inventory.available_count("digital"))
                with patch("stock_monitor.schedule_stock_scan", lambda *args: None):
                    duplicate = await checkout.execute_checkout(user, [{"pid": "digital", "qty": 1}, {"pid": "digital", "qty": 1}])
                sent_records = []
                async def capture_delivery(chat, product, records, **kwargs):
                    sent_records.extend(row["account"] for row in records)
                    return True
                with patch("bot.deliver_inventory", capture_delivery):
                    for line in duplicate["order"]["items"]:
                        await fulfill_bot_line(duplicate["order"], line, await database.products.find_one({"_id": "digital"}), chat_id=991127, user=user, lang="id",
                            inventory_items=duplicate["allocations"][-1]["items"])
                check("same-product distinct lines deliver distinct inventory " + scope.slug, len(sent_records) == 2 and len(set(sent_records)) == 2)
                customer = {"_id": "qris-customer", "currency": "IDR", "email": ""}
                await database.store_customers.insert_one(customer.copy())
                with patch.dict(os.environ, {"GOPAY_ENABLED": "true"}), patch("direct_checkout._run_node", lambda *args: {"image_base64": base64.b64encode(b"mock-qr").decode()}), patch("stock_monitor.schedule_stock_scan", lambda *args: None):
                    qris = await direct_checkout.create_store_qris_order(customer, [{"pid": "digital", "qty": 1}], idempotency_key="c1-qris")
                check("real QRIS reservation before payment " + scope.slug, "error" not in qris and await database.inventory_items.count_documents({"reservation_id": "qris:" + qris["order"]["_id"], "status": "reserved"}) == 1)
                with patch("storefront_routes.send_order_completion_email", AsyncMock(return_value=False)), patch("direct_checkout.notify_transaction_admin", AsyncMock()), patch("direct_checkout.notify_transaction_channel", AsyncMock()), patch("stock_monitor.schedule_stock_scan", lambda *args: None):
                    first = await direct_checkout.finalize_qris_order(qris["order"]["_id"], "mock-tx")
                    second = await direct_checkout.finalize_qris_order(qris["order"]["_id"], "mock-tx")
                check("duplicate real QRIS success no consumption or fulfillment duplication " + scope.slug, first and not second and await database.inventory_items.count_documents({"order_id": qris["order"]["_id"], "status": "sold"}) == 1 and len(await repo.list_order(qris["order"]["_id"])) == 1)
                before_products = await database.products.find().to_list(None)
                dry = await backfill_products(database, tenant_id=scope.tenant_id)
                check("real migration dry-run preserves data " + scope.slug, dry["dry_run"] and before_products == await database.products.find().to_list(None))
                await ensure_fulfillment_indexes(database)
        a, b = scopes
        central = BotTenantScope(tenant_id="platform:central", slug="central", database_name=a.database_name, db_handle=a.db_handle, bot_token="unused")
        central_send = AsyncMock(return_value=True)
        async with use_bot_tenant(central):
            shared = await a.db_handle.purchases.find_one({"_id": "identical-order-id"})
            check("central bot shares owner fulfillment idempotency", await route_item(shared, shared["items"][0], central_send) == "delivered" and central_send.await_count == 0 and await a.db_handle.fulfillments.count_documents({"order_id": shared["_id"]}) == 3)
        repo_a, repo_b = FulfillmentRepository(a.db_handle, a.tenant_id), FulfillmentRepository(b.db_handle, b.tenant_id)
        foreign = (await repo_b.list_order("identical-order-id"))[0]
        check("foreign record ID invisible", await repo_a.collection.find_one(repo_a.query(_id=foreign["_id"])) is None)
        try: await repo_a.transition(foreign["_id"], "completed")
        except CommerceError: check("foreign mutation rejected", True)
        else: check("foreign mutation rejected", False)
        async with use_bot_tenant(a):
            await platform.tenants.update_one({"_id": a.tenant_id}, {"$set": {"status": "suspended"}})
            try: await ensure_order_fulfillments({"_id": "identical-order-id"})
            except CommerceError: check("suspended tenant routing blocked", True)
            else: check("suspended tenant routing blocked", False)
            await platform.tenants.update_one({"_id": a.tenant_id}, {"$set": {"status": "active"}})
        stop(); start(); await ready(http)
        check("backend restart health", True)
        for i, scope in enumerate(scopes):
            response = await http.get("/api/public/tenant/full/orders/identical-order-id/fulfillments", headers=headers[i])
            check("restart reads tenant records " + scope.slug, response.status_code == 200 and len(response.json()) == 3)
        check("retained audit tenants preserved", await retained.tenants.count_documents({}) == before)
    stop()
    runtime = (EVIDENCE / "runtime.log").read_text()
    check("secret-safe runtime log", all(value not in runtime for key, value in ENV.items() if key in {"JWT_SECRET", "INVENTORY_ENCRYPTION_KEY", "ADMIN_PASSWORD", "TELEGRAM_WEBHOOK_SECRET"}) and "PRIVATE-PAYLOAD" not in runtime)
    return {"platform_database": ENV["DB_NAME"], "tenant_databases": [s.database_name for s in scopes], "delivery_transport": "mocked", "mongo": "real dedicated localhost:27019"}

if __name__ == "__main__":
    details = {}
    try:
        details = asyncio.run(run())
    finally:
        stop()
        (EVIDENCE / "live-results.json").write_text(json.dumps({**details, "checks": results}, indent=2) + "\n")
        client.close()
    print(json.dumps({"passed": sum(r["result"] == "PASS" for r in results), "failed": sum(r["result"] == "FAIL" for r in results)}))
