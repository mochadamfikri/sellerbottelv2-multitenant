"""Explicitly isolated live HTTP/Mongo smoke harness; never reads project .env.

Run with the audit venv. Requires the dedicated Mongo container on port 27019.
Secrets are generated in memory and excluded from evidence. No external delivery.
"""
import asyncio
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EVIDENCE = ROOT / "test_reports/live-dev-e2e-20261008"
sys.path.insert(0, str(BACKEND))
from cryptography.fernet import Fernet

ENV = {
    "PATH": os.environ["PATH"], "HOME": os.environ["HOME"],
    "PYTHON_DOTENV_DISABLED": "1", "ENVIRONMENT": "development",
    "MONGO_URL": "mongodb://127.0.0.1:27019/?serverSelectionTimeoutMS=1500",
    "DB_NAME": "sellerbottel_live_e2e_dev", "PLATFORM_DB_NAME": "sellerbottel_live_e2e_dev",
    "JWT_SECRET": secrets.token_urlsafe(48),
    "INVENTORY_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "TELEGRAM_WEBHOOK_SECRET": secrets.token_urlsafe(32),
    "CORS_ORIGINS": "http://127.0.0.1:3002", "TENANT_BASE_DOMAIN": "e2e.invalid",
    "LOCAL_STORAGE_DIR": str(BACKEND / "storage_data/live-dev-e2e"),
    "GOPAY_ENABLED": "false", "BOT2_ENABLED": "false", "PROMOTION_ENABLED": "false",
    "ADMIN_EMAIL": "admin@e2e.invalid", "ADMIN_PASSWORD": secrets.token_urlsafe(24),
}
os.environ.clear()
os.environ.update(ENV)
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from PIL import Image

results = []
tenants = []
proc = None
log_handle = None

def check(name, condition, **safe_details):
    results.append({"test": name, "result": "PASS" if condition else "FAIL", **safe_details})
    if not condition:
        raise AssertionError(name)

def start():
    global proc, log_handle
    log_handle = (EVIDENCE / "runtime.log").open("a")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8002"], cwd=BACKEND, env=ENV, stdout=log_handle, stderr=subprocess.STDOUT)

def stop():
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    if log_handle:
        log_handle.close()

async def ready(http):
    for _ in range(100):
        if proc.poll() is not None:
            raise AssertionError("runtime startup failed; inspect redacted log")
        try:
            if (await http.get("/api/")).status_code == 200:
                return
        except httpx.TransportError:
            pass
        await asyncio.sleep(.2)
    raise AssertionError("runtime readiness timeout")

async def run():
    mongo = AsyncIOMotorClient(ENV["MONGO_URL"])
    platform = mongo[ENV["DB_NAME"]]
    check("real Mongo ping", (await mongo.admin.command("ping"))["ok"] == 1)
    if "--reset-disposable-data" in sys.argv:
        for name in (ENV["DB_NAME"], "sellerbottel_tenant_e2e_tenant_a", "sellerbottel_tenant_e2e_tenant_b", "sellerbottel_tenant_e2e_rollback"):
            await mongo.drop_database(name)
    check("dedicated platform has no existing tenants", await platform.tenants.count_documents({}) == 0)
    password = secrets.token_urlsafe(24)
    start()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8002", timeout=20) as http:
        await ready(http)
        check("backend startup HTTP health", True)
        check("real platform owner unique index", (await platform.tenant_owners.index_information()).get("owner_email_unique", {}).get("unique") is True)
        headers = []
        for label in "ab":
            slug = f"e2e-tenant-{label}"
            email = f"sellerbottel.live.e2e.{label}@gmail.com"
            verify = secrets.token_urlsafe(24)
            from datetime import datetime, timedelta, timezone
            await platform.public_reg_verified.insert_one({"email": email, "verify_token": verify, "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)})
            r = await http.post("/api/public/register", json={"username": slug, "email": email.upper(), "store_name": f"E2E Store {label.upper()}", "password": password, "whatsapp": "081234567890", "verify_token": verify})
            check(f"provision {slug}", r.status_code == 201, status=r.status_code)
            t = await platform.tenants.find_one({"slug": slug})
            check(f"active registry {slug}", t is not None and t["status"] == "active" and t["database_name"] == f"sellerbottel_tenant_e2e_tenant_{label}")
            owner = await platform.tenant_owners.find_one({"email": email})
            check(f"normalized owner {slug}", owner["tenant_id"] == str(t["_id"]) and owner["store_name"] == f"E2E Store {label.upper()}")
            tenants.append({"slug": slug, "id": str(t["_id"]), "database_name": t["database_name"], "status": "active", "bot_configured": False})
            r = await http.post("/api/public/tenant/login", json={"email": email.upper(), "password": password})
            check(f"owner login {slug}", r.status_code == 200)
            token = r.json().get("access_token") or r.json().get("token")
            check(f"tenant JWT {slug}", bool(token))
            headers.append({"Authorization": f"Bearer {token}"})
            for wrong in ({"email": email, "password": "wrong-password"}, {"email": "unknown.e2e@gmail.com", "password": password}):
                check(f"invalid login {slug}", (await http.post("/api/public/tenant/login", json=wrong)).status_code == 401)
        check("distinct tenant IDs", tenants[0]["id"] != tenants[1]["id"])
        dbs = [mongo[t["database_name"]] for t in tenants]
        pids = []
        for i, (db, h) in enumerate(zip(dbs, headers)):
            label = "AB"[i]
            r = await http.post("/api/public/tenant/full/products", headers=h, data={"name": f"Product {label}", "price_usd": "1", "price_idr": "16000", "delivery_type": "inventory"})
            check(f"product create {label}", r.status_code == 200, status=r.status_code)
            pid = (await db.products.find_one({"name": f"Product {label}"}))["_id"]
            pids.append(pid)
            await db.bot_users.insert_one({"telegram_id": 991001, "balance_idr": 100*i, "username": f"user{label}"})
            await db.purchases.insert_one({"_id": f"order-{label}", "status": "failed", "currency": "IDR", "total": 50, "user_tid": 991001, "invoice_id": f"E2E-{label}"})
            await db.coupons.insert_one({"_id": "same-coupon-id", "code": label, "active": True})
            await db.products.insert_one({"_id": "same-product-id", "name": f"Same ID {label}", "active": True, "price_usd": 1, "price_idr": 16000})
            root = f"/api/public/tenant/full/products/{pid}/inventory"
            check(f"inventory schema {label}", (await http.put(root+"/schema", headers=h, json={"fields": ["email", "password"]})).status_code == 200)
            content = f"email|password\n{label.lower()}@example.test|test-password"
            for op in ("validate", "import"):
                r = await http.post(root+"/"+op, headers=h, data={"content": content})
                check(f"inventory {op} {label}", r.status_code == 200, status=r.status_code)
            listing = (await http.get(root, headers=h)).json()
            item = listing["items"][0]
            record = {f: f"edited-{label}-{n}" for n, f in enumerate(listing["schema"])}
            check(f"inventory edit {label}", (await http.put(root+"/"+item["_id"], headers=h, json={"data": record})).status_code == 200)
            check(f"inventory manual {label}", (await http.post(root+"/manual", headers=h, json={"data": {f: f"manual-{label}-{n}" for n,f in enumerate(listing["schema"])}})).status_code == 200)
            check(f"inventory summary {label}", (await http.get(root+"/summary", headers=h)).json()["available"] == 2)
            check(f"inventory template {label}", (await http.get(root+"/template?format=csv", headers=h)).status_code == 200)
            check(f"inventory delete {label}", (await http.delete(root+"/"+item["_id"], headers=h)).status_code == 200)
            for path, payload in (("/catalogs", {"name": f"Catalog {label}"}),):
                check(f"catalog create {label}", (await http.post("/api/public/tenant/full"+path, headers=h, json=payload)).status_code == 200)
            check(f"catalog assign {label}", (await http.put("/api/public/tenant/full/catalogs/assign", headers=h, json={"name": f"Catalog {label}", "product_ids": [pid]})).status_code == 200)
            check(f"catalog rename {label}", (await http.put("/api/public/tenant/full/catalogs/rename", headers=h, json={"old_name": f"Catalog {label}", "name": f"Renamed {label}"})).status_code == 200)
            check(f"order detail {label}", (await http.get(f"/api/public/tenant/full/orders/order-{label}", headers=h)).status_code == 200)
            check(f"refund {label}", (await http.post(f"/api/public/tenant/full/orders/order-{label}/refund", headers=h)).status_code == 200)
            check(f"refund DB balance {label}", (await db.bot_users.find_one({"telegram_id": 991001}))["balance_idr"] == 100*i+50)
            for image_format, mime in (("JPEG","image/jpeg"),("PNG","image/png"),("WEBP","image/webp")):
                buf=io.BytesIO(); Image.new("RGB",(64,64),(40,80,120)).save(buf,format=image_format)
                r = await http.post("/api/public/tenant/full/products", headers=h, data={"name": f"{label} image {image_format}", "price_usd": "1"}, files={"image": ("image."+image_format.lower(), buf.getvalue(), mime)})
                check(f"image upload {image_format} {label}", r.status_code == 200, status=r.status_code)
                image_product = await db.products.find_one({"name": f"{label} image {image_format}"})
                stored = Path(ENV["LOCAL_STORAGE_DIR"]) / image_product["image_path"]
                check(f"stored valid WEBP {image_format} {label}", Image.open(stored).format == "WEBP")
            for kind, data, mime in (("mime", b"test", "text/plain"),("corrupt", b"broken", "image/png"),("oversize", b"x"*(5*1024*1024+1), "image/png")):
                r = await http.post("/api/public/tenant/full/products", headers=h, data={"name":"Invalid", "price_usd":"1"}, files={"image":("bad.png",data,mime)})
                check(f"invalid image {kind} {label}", 400 <= r.status_code < 500 and bool(r.json().get("detail")), status=r.status_code)
        for i, h in enumerate(headers):
            other = 1-i
            before = {c: await dbs[other][c].find().to_list(None) for c in ("products","inventory_items","purchases","bot_users","coupons","product_catalogs")}
            foreign_pid=pids[other]; foreign_order="order-"+"AB"[other]
            for method,path in (("DELETE", f"/products/{foreign_pid}"),("GET",f"/products/{foreign_pid}/inventory"),("GET",f"/orders/{foreign_order}"),("POST",f"/orders/{foreign_order}/refund")):
                r=await http.request(method,"/api/public/tenant/full"+path,headers=h)
                check(f"foreign denial {'AB'[i]}->{ 'AB'[other]} {method} {path}",r.status_code == 404,status=r.status_code)
            after = {c: await dbs[other][c].find().to_list(None) for c in before}
            check(f"foreign DB unchanged {'AB'[i]}->{'AB'[other]}",before==after)
            rows=(await http.get("/api/public/tenant/full/products",headers=h)).json()
            check(f"product read isolation {'AB'[i]}",not any(p["name"]==f"Product {'AB'[other]}" for p in rows))
            same=next(p for p in rows if p["_id"]=="same-product-id")
            check(f"same ID read namespace {'AB'[i]}",same["name"]==f"Same ID {'AB'[i]}")
            check(f"same ID toggle namespace {'AB'[i]}",(await http.patch("/api/public/tenant/full/products/same-product-id/toggle",headers=h)).status_code==200)
            check(f"same ID foreign preserved {'AB'[i]}",(await dbs[other].products.find_one({"_id":"same-product-id"}))["active"] == (other == 1))
            users=(await http.get("/api/public/tenant/full/users",headers=h)).json()
            check(f"tenant users {'AB'[i]}","user"+"AB"[other] not in json.dumps(users))
            check(f"tenant stats {'AB'[i]}",(await http.get("/api/public/tenant/full/stats",headers=h)).status_code==200)
        for state in ("suspended","disabled","provisioning","failed"):
            await platform.tenants.update_one({"slug":tenants[0]["slug"]},{"$set":{"status":state}})
            check(f"old JWT denied {state}",(await http.get("/api/public/tenant/full/products",headers=headers[0])).status_code==403)
            check(f"login denied {state}",(await http.post("/api/public/tenant/login",json={"email":"sellerbottel.live.e2e.a@gmail.com","password":password})).status_code==403)
            check(f"B unaffected by A {state}",(await http.get("/api/public/tenant/full/products",headers=headers[1])).status_code==200)
        await platform.tenants.update_one({"slug":tenants[0]["slug"]},{"$set":{"status":"active"}})
        check("reactivation fresh login",(await http.post("/api/public/tenant/login",json={"email":"sellerbottel.live.e2e.a@gmail.com","password":password})).status_code==200)
        from domain_registry import register_domain, resolve_domain
        domain="claim.e2e.invalid"
        await register_domain(mongo,domain=domain,tenant_id=tenants[0]["id"],purpose="storefront",origin="custom")
        await register_domain(mongo,domain=domain,tenant_id=tenants[0]["id"],purpose="storefront",origin="custom")
        conflict=False
        try:
            await register_domain(mongo,domain=domain,tenant_id=tenants[1]["id"],purpose="storefront",origin="custom")
        except ValueError:
            conflict=True
        check("real domain takeover prevented",conflict and (await resolve_domain(mongo,domain))["tenant_id"]==tenants[0]["id"])
        from pymongo.errors import DuplicateKeyError
        duplicate=False
        try:
            await platform.tenant_owners.insert_one({"email":"sellerbottel.live.e2e.a@gmail.com"})
        except DuplicateKeyError:
            duplicate=True
        check("real duplicate owner rejected",duplicate)
        from tenant_registry import MongoTenantRegistry
        registry=MongoTenantRegistry(environment=ENV,client=mongo)
        collision=False
        try:
            await registry.create_tenant("e2e_tenant_a","Collision","demo")
        except ValueError:
            collision=True
        check("real DB normalized alias rejected",collision)
        from storage import _resolve_path, put_object, get_object, delete_object
        traversal=False
        try:
            _resolve_path("../../outside")
        except ValueError:
            traversal=True
        check("storage traversal rejected",traversal)
        await put_object("smoke/file.txt",b"development-only","text/plain")
        check("storage file read",(await get_object("smoke/file.txt"))[0]==b"development-only")
        check("storage deletion",await delete_object("smoke/file.txt"))
        await supplementary(http, mongo, platform, dbs, headers, password)
        await commerce_and_dispatcher(mongo, platform, dbs)
        await browser_acceptance(password)
        await mongo_outage(http, headers, mongo)
        snapshot=[await db.products.count_documents({}) for db in dbs]
        stop(); start(); await ready(http)
        check("backend restart indexes idempotent",snapshot==[await db.products.count_documents({}) for db in dbs])
        for n in range(30):
            for h in headers:
                check(f"smoke HTTP {n}",(await http.get("/api/public/tenant/full/products",headers=h)).status_code==200)
            await asyncio.sleep(1)
    mongo.close()

async def supplementary(http, mongo, platform, dbs, headers, password):
    for i, (db, h) in enumerate(zip(dbs, headers)):
        label="AB"[i]
        pid=(await db.products.find_one({"name":f"Product {label}"}))["_id"]
        check(f"product edit {label}",(await http.put(f"/api/public/tenant/full/products/{pid}",headers=h,data={"name":f"Edited {label}","price_usd":"2","price_idr":"32000"})).status_code==200)
        check(f"catalog delete {label}",(await http.delete("/api/public/tenant/full/catalogs",headers=h,params={"name":f"Renamed {label}"})).status_code==200)
        await db.products.insert_one({"_id":"session", "name":"Session", "active":True,"product_kind":"digital","inventory_mode":"telegram_session","inventory_schema":["Session File"]})
        root="/api/public/tenant/full/products/session/inventory"
        check(f"session import {label}",(await http.post(root+"/import",headers=h,files={"file":("original.session",b"dev-session","application/octet-stream")})).status_code==200)
        item=(await http.get(root,headers=h)).json()["items"][0]
        check(f"session replacement {label}",(await http.post(root+"/"+item["_id"]+"/file",headers=h,files={"file":("replacement.session",b"dev-replacement","application/octet-stream")})).status_code==200)
        root=f"/api/public/tenant/full/products/{pid}/inventory/transform"
        file=("table.csv",b"email,password\na@old.test,oldpassword\n","text/csv")
        check(f"transform inspect {label}",(await http.post(root+"/inspect",headers=h,files={"file":file})).status_code==200)
        check(f"transform download {label}",(await http.post(root,headers=h,files={"file":file},data={"email_column":"email","new_domain":"new.test","password_column":"password","password_mode":"fixed","fixed_password":"updated"})).status_code==200)
        check(f"product import template {label}",(await http.get("/api/public/tenant/full/products/import-template?format=csv",headers=h)).status_code==200)
        await db.purchases.insert_one({"_id":"service", "status":"service_waiting"})
        check(f"service completion {label}",(await http.post("/api/public/tenant/full/orders/service/complete",headers=h)).status_code==200)
        check(f"service completion persisted {label}",(await db.purchases.find_one({"_id":"service"}))["status"]=="delivered")
        from domain_registry import register_domain
        await register_domain(mongo,domain=f"e2e-{label.lower()}.localhost",tenant_id=tenants[i]["id"],purpose="storefront")
        check(f"host resolution {label}",(await http.get("/api/public/host-config",params={"host":f"e2e-{label.lower()}.localhost"})).json()["tenant_slug"]==tenants[i]["slug"])
    # Controlled injection uses the actual ASGI application and real Motor DB.
    import server
    import tenant_provisioning
    original=tenant_provisioning.provision_tenant_database
    async def fail(slug, client):
        await original(slug,client)
        raise RuntimeError("controlled development provisioning failure")
    from datetime import datetime, timedelta, timezone
    email="sellerbottel.live.rollback@gmail.com"
    verify=secrets.token_urlsafe(24)
    await platform.public_reg_verified.insert_one({"email":email,"verify_token":verify,"expires_at":datetime.now(timezone.utc)+timedelta(minutes=10)})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app,raise_app_exceptions=False),base_url="http://local") as local:
        with patch.object(tenant_provisioning,"provision_tenant_database",fail):
            r=await local.post("/api/public/register",json={"username":"e2e-rollback","email":email,"store_name":"Rollback","password":password,"whatsapp":"081234567890","verify_token":verify})
        check("real provisioning rollback response",r.status_code==503,status=r.status_code)
        check("rollback tenant removed",await platform.tenants.find_one({"slug":"e2e-rollback"}) is None)
        check("rollback owner removed",await platform.tenant_owners.find_one({"email":email}) is None)
        check("rollback domain removed",await platform.domains.find_one({"domain":"e2e-rollback.e2e.invalid"}) is None)
        check("rollback new DB removed","sellerbottel_tenant_e2e_rollback" not in await mongo.list_database_names())
        check("rollback verification retained",await platform.public_reg_verified.find_one({"email":email}) is not None)
        check("rollback existing A DB preserved",await dbs[0].products.count_documents({})>0)
        from domain_registry import register_domain, resolve_domain
        race=await asyncio.gather(*(register_domain(mongo,domain="race.e2e.invalid",tenant_id=t["id"],purpose="storefront") for t in tenants),return_exceptions=True)
        check("real concurrent domain claim one winner",sum(isinstance(v,dict) for v in race)==1 and sum(isinstance(v,ValueError) for v in race)==1)
        await platform.public_reg_verified.insert_one({"email":"sellerbottel.live.e2e.a@gmail.com","verify_token":verify,"expires_at":datetime.now(timezone.utc)+timedelta(minutes=10)})
        r=await local.post("/api/public/register",json={"username":"e2e-duplicate-owner","email":"sellerbottel.live.e2e.a@gmail.com","store_name":"Duplicate","password":password,"whatsapp":"081234567890","verify_token":verify})
        check("duplicate owner public registration rejected",r.status_code==409,status=r.status_code)
        # Fail only the product insert, after the upload has reached disk.
        from motor.motor_asyncio import AsyncIOMotorCollection
        orig_insert=AsyncIOMotorCollection.insert_one
        async def fail_insert(collection,*args,**kwargs):
            if collection.name=="products":
                raise RuntimeError("controlled product DB failure")
            return await orig_insert(collection,*args,**kwargs)
        image=io.BytesIO(); Image.new("RGB",(64,64)).save(image,format="PNG")
        before=set(Path(ENV["LOCAL_STORAGE_DIR"]).rglob("*.webp"))
        with patch.object(AsyncIOMotorCollection,"insert_one",fail_insert):
            r=await local.post("/api/public/tenant/full/products",headers=headers[0],data={"name":"Fail image save","price_usd":"1"},files={"image":("image.png",image.getvalue(),"image/png")})
        check("failed product DB save rejects request",r.status_code==500,status=r.status_code)
        check("failed product DB save removes uploaded image",before==set(Path(ENV["LOCAL_STORAGE_DIR"]).rglob("*.webp")))

async def mongo_outage(http, headers, mongo):
    command=["sudo","-n","docker"]
    subprocess.run(command+["stop","sellerbottelv2-dev-mongo"],check=True,stdout=subprocess.DEVNULL)
    try:
        r=await http.get("/api/public/tenant/full/products",headers=headers[0])
        check("dedicated Mongo outage fails safely",r.status_code>=500,status=r.status_code)
    finally:
        subprocess.run(command+["start","sellerbottelv2-dev-mongo"],check=True,stdout=subprocess.DEVNULL)
    for _ in range(40):
        try:
            await mongo.admin.command("ping")
            break
        except Exception:
            await asyncio.sleep(.5)
    check("Mongo outage recovery",(await http.get("/api/public/tenant/full/products",headers=headers[0])).status_code==200)

async def commerce_and_dispatcher(mongo, platform, dbs):
    import checkout
    import inventory
    import bot
    import bot_dispatcher as dispatcher
    import stock_monitor
    from unittest.mock import AsyncMock
    from bot_tenant_scope import BotTenantScope, use_bot_tenant
    scopes=[BotTenantScope(slug=t["slug"],tenant_id=t["id"],database_name=t["database_name"],db_handle=db,bot_token="development-mock-"+t["slug"],brand_name="E2E Store "+"AB"[i]) for i,(t,db) in enumerate(zip(tenants,dbs))]
    with patch.object(stock_monitor,"schedule_stock_scan",lambda *args:None):
        for scope in scopes:
            async with use_bot_tenant(scope):
                db=scope.db_handle
                await db.settings.update_one({"_id":"main"},{"$set":{"rate_mode":"manual","manual_rate":16000}})
                await db.bot_users.insert_one({"telegram_id":991002,"currency":"IDR","balance_idr":10000,"cart":[{"pid":"checkout-product","qty":1}]})
                await db.products.insert_one({"_id":"checkout-product","name":scope.slug,"active":True,"product_kind":"digital","delivery_type":"inventory","inventory_enabled":True,"price_idr":1000,"inventory_schema":["account"]})
                await inventory.add_records("checkout-product",[{"account":scope.slug+str(n)} for n in range(3)],["account"])
                await db.promo_coupons.insert_one({"_id":"checkout-coupon","code":"E2E-SAME","active":True,"currency":"IDR","type":"percent","value":50,"used_count":0,"quota_total":10})
        for i,scope in enumerate(scopes):
            async with use_bot_tenant(scope):
                db=scope.db_handle; other=dbs[1-i]
                untouched={c:await other[c].find().to_list(None) for c in ("bot_users","purchases","inventory_items","promo_coupons")}
                user=await db.bot_users.find_one({"telegram_id":991002})
                result=await checkout.execute_checkout(user,user["cart"],coupon_code="E2E-SAME")
                check(f"real balance checkout {scope.slug}",result["ok"])
                check(f"checkout balance/cart {scope.slug}",(await db.bot_users.find_one({"telegram_id":991002}))["balance_idr"]==9500 and (await db.bot_users.find_one({"telegram_id":991002}))["cart"]==[])
                check(f"checkout inventory sold {scope.slug}",await db.inventory_items.count_documents({"product_id":"checkout-product","status":"sold"})==1)
                check(f"checkout coupon used {scope.slug}",(await db.promo_coupons.find_one({"_id":"checkout-coupon"}))["used_count"]==1)
                check(f"checkout foreign DB unchanged {scope.slug}",untouched=={c:await other[c].find().to_list(None) for c in untouched})
                await db.bot_users.update_one({"telegram_id":991002},{"$set":{"balance_idr":0}})
                user=await db.bot_users.find_one({"telegram_id":991002})
                result=await checkout.execute_checkout(user,[{"pid":"checkout-product","qty":1}])
                check(f"insufficient balance {scope.slug}",not result["ok"])
                check(f"insufficient leaves stock available {scope.slug}",await db.inventory_items.count_documents({"product_id":"checkout-product","status":"available"})==2)
                await db.bot_users.update_one({"telegram_id":991002},{"$set":{"balance_idr":10000}})
                user=await db.bot_users.find_one({"telegram_id":991002})
                with patch.object(checkout,"commit_items",AsyncMock(side_effect=RuntimeError("controlled delivery failure"))):
                    result=await checkout.execute_checkout(user,[{"pid":"checkout-product","qty":1}],coupon_code="E2E-SAME")
                check(f"checkout delivery failure {scope.slug}",not result["ok"])
                check(f"checkout rollback balance {scope.slug}",(await db.bot_users.find_one({"telegram_id":991002}))["balance_idr"]==10000)
                check(f"checkout rollback inventory {scope.slug}",await db.inventory_items.count_documents({"product_id":"checkout-product","status":"available"})==2)
                check(f"checkout rollback coupon {scope.slug}",(await db.promo_coupons.find_one({"_id":"checkout-coupon"}))["used_count"]==1)
                with patch.object(bot,"send_message",AsyncMock(return_value={"ok":True})),patch.object(bot,"ensure_join_gate",AsyncMock(return_value=True)):
                    await bot.handle_message({"chat":{"id":991003},"from":{"id":991003,"first_name":"Dev","username":"e2euser"},"text":"/start"})
                    text=bot.send_message.await_args.args[1]
                    check(f"real Mongo mocked Telegram start branding {scope.slug}",scope.brand_name in text and "Rp" in text)
                    check(f"vertical menu {scope.slug}",all(len(row)==1 for row in bot.main_menu_kb("id")["inline_keyboard"]))
                    user=await db.bot_users.find_one({"telegram_id":991003})
                check(f"start user initialized {scope.slug}",bool(user.get("first_start_at")) and user.get("username")=="e2euser")
                import direct_checkout
                import storefront_routes
                import services
                import base64
                customer={"_id":"e2e-web-customer","email":"customer@example.test"}
                await db.store_customers.insert_one(customer)
                with patch.object(direct_checkout,"store_qris_ready",AsyncMock(return_value=True)),patch.object(direct_checkout,"_run_node",lambda *args:{"image_base64":base64.b64encode(b"mock-qr-only").decode()}),patch.object(storefront_routes,"send_order_completion_email",AsyncMock(return_value=True)),patch.object(services,"notify_transaction_channel_safely",AsyncMock()):
                    result=await direct_checkout.create_store_qris_order(customer,[{"pid":"checkout-product","qty":1}],idempotency_key="e2e-qris-success")
                    oid=result["order"]["_id"]
                    check(f"QRIS mock pending {scope.slug}",(await db.purchases.find_one({"_id":oid}))["status"]=="pending_payment")
                    check(f"QRIS mock reserve {scope.slug}",await db.inventory_items.count_documents({"product_id":"checkout-product","status":"reserved"})==1)
                    check(f"QRIS mock success {scope.slug}",await direct_checkout.finalize_qris_order(oid,"development-simulated-payment"))
                    check(f"QRIS duplicate signal ignored {scope.slug}",not await direct_checkout.finalize_qris_order(oid,"development-simulated-payment"))
                    result=await direct_checkout.create_store_qris_order(customer,[{"pid":"checkout-product","qty":1}],idempotency_key="e2e-qris-expire")
                    oid=result["order"]["_id"]
                    await db.purchases.update_one({"_id":oid},{"$set":{"expires_at":"2000-01-01T00:00:00+00:00"}})
                    await direct_checkout.expire_qris_orders()
                    check(f"QRIS mock expiration {scope.slug}",(await db.purchases.find_one({"_id":oid}))["status"]=="expired")
                    check(f"QRIS expiration releases inventory {scope.slug}",await db.inventory_items.count_documents({"product_id":"checkout-product","status":"available"})==1)
    async def inert_worker(*args):
        await asyncio.Event().wait()
    supervisor=dispatcher.Dispatcher()
    with patch.object(dispatcher,"_poll_worker",inert_worker),patch.object(dispatcher,"_load_central_bot",AsyncMock(return_value=None)):
        try:
            for t,scope in zip(tenants,scopes):
                await platform.tenants.update_one({"slug":t["slug"]},{"$set":{"metadata.bot_config":{"token_encrypted":Fernet(ENV["INVENTORY_ENCRYPTION_KEY"].encode()).encrypt(scope.bot_token.encode()).decode()}}})
            await supervisor.reconcile(); await asyncio.sleep(0)
            check("real registry dispatcher two mock workers",set(supervisor._workers)=={t["slug"] for t in tenants})
            a,b=(t["slug"] for t in tenants); old_a=supervisor._workers[a][0]; old_b=supervisor._workers[b][0]
            await platform.tenants.update_one({"slug":a},{"$set":{"metadata.bot_config.token_encrypted":Fernet(ENV["INVENTORY_ENCRYPTION_KEY"].encode()).encrypt(b"rotated-development-mock").decode()}})
            await supervisor.reconcile(); await asyncio.sleep(0)
            check("real registry mock token rotation target only",old_a.cancelled() and supervisor._workers[b][0] is old_b)
            await platform.tenants.update_one({"slug":a},{"$set":{"status":"suspended"}})
            await supervisor.reconcile()
            check("real registry suspension stops target only",a not in supervisor._workers and supervisor._workers[b][0] is old_b)
            await platform.tenants.update_one({"slug":a},{"$set":{"status":"active"}})
            await supervisor.reconcile(); await asyncio.sleep(0)
            check("real registry reactivation two workers",len(supervisor._workers)==2)
        finally:
            for task,stop_event,*_ in supervisor._workers.values():
                stop_event.set(); task.cancel()
            await asyncio.gather(*(v[0] for v in supervisor._workers.values()),return_exceptions=True)
            for t in tenants:
                await platform.tenants.update_one({"slug":t["slug"]},{"$unset":{"metadata.bot_config":""}})

async def browser_acceptance(password):
    import http.client
    import http.server
    import threading
    from playwright.async_api import async_playwright
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,directory=str(ROOT/"frontend/build"),**kwargs)
        def log_message(self,*args):
            pass
        def forward(self):
            connection=http.client.HTTPConnection("127.0.0.1",8002,timeout=30)
            body=self.rfile.read(int(self.headers.get("Content-Length","0")))
            connection.request(self.command,self.path,body=body,headers={k:v for k,v in self.headers.items() if k.lower() not in {"host","connection"}})
            response=connection.getresponse()
            content=response.read()
            self.send_response(response.status)
            for k,v in response.getheaders():
                if k.lower() not in {"transfer-encoding","connection","content-length"}:
                    self.send_header(k,v)
            self.send_header("Content-Length",str(len(content))); self.end_headers()
            self.wfile.write(content); connection.close()
        def do_GET(self):
            if self.path.startswith("/api/"):
                return self.forward()
            if not self.path.startswith("/static/") and not (ROOT/"frontend/build"/self.path.split("?")[0].lstrip("/")).is_file():
                self.path="/index.html"
            super().do_GET()
        do_POST=forward
        do_PUT=forward
        do_PATCH=forward
        do_DELETE=forward
    server=http.server.ThreadingHTTPServer(("127.0.0.1",3002),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path="/home/ubuntu/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",headless=True,args=["--no-sandbox","--host-resolver-rules=MAP e2e-a.localhost 127.0.0.1, MAP e2e-b.localhost 127.0.0.1"])
            for label in "ab":
                context=await browser.new_context()
                page=await context.new_page()
                leaks=[]
                def observe(request):
                    if "/api/" in request.url and "/public/tenant/" not in request.url and "authorization" in request.headers:
                        leaks.append(request.url.split("?")[0])
                page.on("request",observe)
                base=f"http://e2e-{label}.localhost:3002"
                await page.goto(base+"/admin")
                await page.get_by_placeholder("Email",exact=True).fill(f"sellerbottel.live.e2e.{label}@gmail.com")
                await page.get_by_placeholder("Password",exact=True).fill(password)
                await page.get_by_role("button",name="Masuk",exact=True).click()
                await page.get_by_role("button",name="Keluar").wait_for()
                check(f"browser TenantAdmin login {label.upper()}",True)
                for tab,name in (("products","Produk"),("catalogs","Katalog"),("inventory","Inventory"),("orders","Order"),("users","Pengguna")):
                    await page.get_by_role("button",name=name,exact=True).click()
                    await page.wait_for_url("**/admin?tab="+tab)
                    check(f"browser tenant navigation {label.upper()} {tab}",True)
                await page.get_by_role("button",name="Keluar").click()
                await page.goto(base+"/admin")
                await page.get_by_placeholder("Email",exact=True).wait_for()
                await page.reload()
                await page.get_by_placeholder("Email",exact=True).wait_for()
                check(f"browser logout reload remains logged out {label.upper()}",True)
                check(f"browser public/platform bearer leak {label.upper()}",not leaks)
                check(f"browser no persisted bearer {label.upper()}",await page.evaluate("Object.keys(localStorage).every(k => !/token|auth/i.test(k))"))
                await context.close()
            await browser.close()
    finally:
        server.shutdown(); server.server_close()

if __name__ == "__main__":
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    try:
        asyncio.run(run())
    except Exception as exc:
        print("Live harness stopped:",type(exc).__name__,str(exc) if isinstance(exc,AssertionError) else "details withheld")
        results.append({"test":"harness completion","result":"FAIL","exception_class":type(exc).__name__})
    finally:
        stop()
        (EVIDENCE/"live-results.json").write_text(json.dumps({"tests":results,"tenants":tenants},indent=2)+"\n")
    if not any(r["result"]=="FAIL" for r in results):
        from dotenv import dotenv_values
        runtime=dict(ENV)
        approved=dotenv_values(BACKEND/".env")
        runtime.update({k:v for k,v in approved.items() if k.startswith("SMTP_") and v})
        private_config=BACKEND/".env.live-e2e"
        descriptor=os.open(private_config,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(descriptor,"w") as output:
            output.write("\n".join(k+"="+json.dumps(v) for k,v in runtime.items())+"\n")
        private_config.chmod(0o600)
    print(json.dumps({"passed":sum(r["result"]=="PASS" for r in results),"failed":sum(r["result"]=="FAIL" for r in results)}))
    sys.exit(any(r["result"]=="FAIL" for r in results))
