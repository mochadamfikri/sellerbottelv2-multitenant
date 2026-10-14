"""Phase 4 acceptance on dedicated dev Mongo: isolated fresh databases, no .env/reset.

HTTP API uses localhost:8006. Delivery/provider/notification transports are mocked;
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
ENV = {"COOKIE_SECURE": "false", "PHASE3_MOCK_ENABLED":"true", "PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "PYTHON_DOTENV_DISABLED": "1",
    "ENVIRONMENT": "development", "MONGO_URL": "mongodb://127.0.0.1:27019/?serverSelectionTimeoutMS=1500",
    "DB_NAME": "sellerbottel_phase4_dev_" + nonce, "PLATFORM_DB_NAME": "sellerbottel_phase4_dev_" + nonce,
    "JWT_SECRET": secrets.token_urlsafe(48), "INVENTORY_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "TELEGRAM_WEBHOOK_SECRET": secrets.token_urlsafe(32), "CORS_ORIGINS": "http://127.0.0.1:3006",
    "TENANT_BASE_DOMAIN": "phase4.invalid", "ADMIN_EMAIL": "admin@phase4.invalid", "ADMIN_PASSWORD": secrets.token_urlsafe(24),
    "GOPAY_ENABLED": "false", "BOT2_ENABLED": "false", "PROMOTION_ENABLED": "false",
    "LOCAL_STORAGE_DIR": str(ROOT / "backend/storage_data/phase4-dev")}
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

EVIDENCE = ROOT / "test_reports/phase-4-final-hardening-20261008"
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
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8006"],
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

from commerce.physical.stock import PhysicalStock, ensure_indexes as physical_indexes
from commerce.physical.models import VariantBody, create_variant
from commerce.physical.workflow import transition
from auth import hash_password
from domain_registry import register_domain
ADDRESS = {"recipient_name":"Synthetic Buyer", "phone":"081234567890", "address_line_1":"Jalan Uji 12", "city":"Bandung", "province":"Jawa Barat", "postal_code":"40111"}


BASE = "/api/public/tenant/full/commerce"
MOCK_SECRET = "mock_phase4_webhook"
SHIP_SECRET = "mock_phase4_shipping"

async def action(http, name, path, *, headers=None, data=None, method="POST", expected=200):
    result = await http.request(method, path, headers=headers, json=data)
    check(name, result.status_code == expected)
    if result.status_code != expected: raise AssertionError(result.text)
    return result.json()

async def confirm(http, order, *, event_id="live-paid", signature=True):
    import hashlib, hmac
    p = order["payment"]
    event = {"event_id": event_id, "reference": p["provider_reference"], "provider_payment_id": p["provider_payment_id"], "amount": p["amount"], "currency": "IDR", "status": "paid"}
    raw = json.dumps(event).encode()
    sig = hmac.new(MOCK_SECRET.encode(), raw, hashlib.sha256).hexdigest() if signature else "invalid"
    return await http.post("/api/commerce/webhooks/payments/" + p["provider"], content=raw, headers={"x-mock-signature": sig})

async def tracking(http, shipment, event_id="tracking-final", status="delivered"):
    import hashlib, hmac
    raw=json.dumps({"event_id":event_id,"provider_shipment_id":shipment["provider_shipment_id"],"status":status}).encode()
    return await http.post("/api/commerce/webhooks/shipping/mock_courier",content=raw,headers={"x-mock-signature":hmac.new(SHIP_SECRET.encode(),raw,hashlib.sha256).hexdigest()})

async def run():
    from payments.credentials import save, load
    from payments.models import ensure_indexes
    from payments.ledger import Ledger, balances
    from payments.orchestrator import checkout as gateway_checkout
    from storefront_routes import CheckoutBody
    platform=client[ENV["DB_NAME"]]
    retained=client.sellerbottel_live_e2e_dev
    before=await retained.tenants.count_documents({})
    check("real dedicated Mongo ping",(await client.admin.command("ping"))["ok"]==1)
    check("fresh isolated platform",not await platform.list_collection_names())
    version=await save(platform,"platform-idse","kasera","mock",{"api_key":"mock_platform_api","webhook_secret":MOCK_SECRET})
    caps=await (await load(platform,"platform-idse",version)).connect()
    await platform.platform_payment_settings.insert_one({"_id":"kasera","credential_id":version,"capabilities":caps})
    start(); scopes=[]; headers=[]; products=[]
    password=secrets.token_urlsafe(24);buyer_password=secrets.token_urlsafe(24)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8006",timeout=30) as http:
        await ready(http);check("real HTTP backend ready",True)
        for label in "ab":
            slug="phase4-"+label+"-"+nonce; email=slug+"@gmail.com";verified=secrets.token_urlsafe(24)
            await platform.public_reg_verified.insert_one({"email":email,"verify_token":verified,"expires_at":datetime.now(timezone.utc)+timedelta(minutes=10)})
            await action(http,"tenant registration "+label,"/api/public/register",data={"username":slug,"email":email,"store_name":"Phase3 "+label,"password":password,"whatsapp":"081234567890","verify_token":verified},expected=201)
            tenant=await platform.tenants.find_one({"slug":slug});database=client[tenant["database_name"]]
            scope=BotTenantScope(tenant_id=str(tenant["_id"]),slug=slug,database_name=database.name,db_handle=database);scopes.append(scope)
            login=await action(http,"owner login "+label,"/api/public/tenant/login",data={"email":email,"password":password})
            headers.append({"Authorization":"Bearer "+login["token"]})
            prod=await action(http,"physical authoring "+label,"/api/public/tenant/full/physical/products",headers=headers[-1],data={"name":"Phase3 Coat "+label,"price_idr":10000,"catalog_name":"Phase3","has_variants":True})
            variant=await action(http,"same SKU isolated "+label,"/api/public/tenant/full/physical/products/"+prod["_id"]+"/variants",headers=headers[-1],data={"sku":"PHASE3-SKU","option_values":{"size":"L"},"weight":300})
            await action(http,"opening stock "+label,"/api/public/tenant/full/physical/variants/"+variant["_id"]+"/stock",headers=headers[-1],data={"type":"RECEIVE","quantity":30,"reference_id":"opening-stock","reason":"Synthetic stock"})
            products.append((prod["_id"],variant["_id"]))
            await database.store_customers.insert_one({"_id":"same-customer","email":"phase4-buyer@gmail.com","password_hash":hash_password(buyer_password),"balance_idr":1000000,"currency":"IDR","shipping_address":ADDRESS})
            await database.settings.update_one({"_id":"main"},{"$set":{"manual_shipping_fee":5000,"require_channel_join":False}})
            await register_domain(client,domain=slug+".phase4.invalid",tenant_id=scope.tenant_id,purpose="storefront")
            await action(http,"payment mode "+label,BASE+"/payment-settings",method="PUT",headers=headers[-1],data={"payment_mode":"platform_settlement" if label=="a" else "self_gateway","provider":"kasera","environment":"mock",**({"credentials":{"api_key":"mock_tenant_api","webhook_secret":MOCK_SECRET}} if label=="b" else {})})
            result=await action(http,"Test Connection "+label,BASE+"/payment-settings/test",headers=headers[-1])
            check("explicit mock capability "+label,result["coverage"]=="MOCKED")
        a,b=scopes;ha,hb=headers;pid,vid=products[0]
        store="/api/store/t/"+a.slug
        await action(http,"customer login a",store+"/login",data={"email":"phase4-buyer@gmail.com","password":buyer_password})
        await action(http,"foreign same-ID cookie denied","/api/store/t/"+b.slug+"/me",method="GET",expected=401)
        order=await action(http,"gateway payment create",store+"/checkout",data={"items":[{"pid":pid,"variant_id":vid,"qty":2}],"payment_method":"gateway:qris","idempotency_key":"real-mongo-order","shipping_address":ADDRESS})
        check("single order total invariant",order["payment"]["amount"]==25000)
        route=await platform.payment_routes.find_one({"_id":order["payment"]["_id"]})
        check("route correct tenant/database",route["tenant_id"]==a.tenant_id and route["tenant_database"]==a.database_name)
        check("invalid signature rejected",(await confirm(http,order,signature=False)).status_code==422)
        callbacks=await asyncio.gather(*(confirm(http,order) for _ in range(12)))
        check("real Mongo concurrent duplicate webhooks",all(r.status_code==200 for r in callbacks))
        variant=await a.db_handle.physical_variants.find_one({"_id":vid})
        check("exactly one stock sale",variant["on_hand"]==28 and variant["reserved"]==0 and sum(e["type"]=="SALE" for e in variant["stock_events"])==1)
        check("one fulfillment",await a.db_handle.fulfillments.count_documents({"order_id":order["_id"]})==1)
        check("one settlement credit",sum(e["type"]=="PAYMENT_GROSS" for e in (await Ledger(a.db_handle,a.tenant_id).get())["events"])==1)
        await action(http,"foreign refund denied",BASE+"/transactions/"+order["payment"]["_id"]+"/refunds",headers=hb,data={"idempotency_key":"foreign-refund","amount":1000},expected=422)
        for stage in ("clearing","available"):
            await action(http,"settlement "+stage,BASE+"/settlement/"+order["payment"]["_id"]+"/advance",headers=ha,data={"stage":stage})
        await action(http,"masked bank",BASE+"/payout-bank",method="PUT",headers=ha,data={"bank_name":"Mock BCA","account_number":"1234567890","account_holder":"Synthetic Tenant"})
        payout_results=await asyncio.gather(*(http.post(BASE+"/payouts",headers=ha,json={"idempotency_key":"payout-race-"+str(i),"amount":20000}) for i in range(10)))
        check("real Mongo payout reserve race one winner",sum(r.status_code==200 for r in payout_results)==1)
        payout_key=next(r.json()[0]["payout_id"] for r in payout_results if r.status_code==200)
        for state in ("reviewing","processing","paid","paid"):
            await action(http,"simulated payout "+state,BASE+"/payouts/"+payout_key+"/simulate",headers=ha,data={"status":state})
        refundbody={"idempotency_key":"after-payout-refund","amount":10000}
        for _ in range(2): await action(http,"partial refund idempotent",BASE+"/transactions/"+order["payment"]["_id"]+"/refunds",headers=ha,data=refundbody)
        values=balances((await Ledger(a.db_handle,a.tenant_id).get())["events"])
        check("refund after payout liability",values["liability"]==5000 and values["paid_out"]==20000)
        # Own gateways in the second tenant use identical customer IDs but no settlement.
        await action(http,"customer login b","/api/store/t/"+b.slug+"/login",data={"email":"phase4-buyer@gmail.com","password":buyer_password})
        own_orders=[]
        for name in ("kasera","midtrans"):
            fields={"api_key":"mock_tenant_api","webhook_secret":MOCK_SECRET} if name=="kasera" else {"server_key":"mock_server","client_key":"mock_client","webhook_secret":MOCK_SECRET}
            await action(http,"tenant "+name+" credentials",BASE+"/payment-settings",method="PUT",headers=hb,data={"payment_mode":"self_gateway","provider":name,"environment":"mock","credentials":fields})
            await action(http,"tenant "+name+" connection",BASE+"/payment-settings/test",headers=hb)
            own=await action(http,"tenant "+name+" checkout","/api/store/t/"+b.slug+"/checkout",data={"items":[{"pid":products[1][0],"variant_id":products[1][1],"qty":1}],"payment_method":"gateway:qris","idempotency_key":"own-order-"+name,"shipping_address":ADDRESS})
            check("tenant "+name+" paid",(await confirm(http,own,event_id=name+"-paid")).status_code==200)
            await action(http,"tenant "+name+" full refund",BASE+"/transactions/"+own["payment"]["_id"]+"/refunds",headers=hb,data={"idempotency_key":"own-refund-"+name,"amount":own["payment"]["amount"]})
            own_orders.append(own)
        check("own gateway zero settlement",balances((await Ledger(b.db_handle,b.tenant_id).get())["events"])["pending"]==0)
        shipping={"mode":"integrated_shipping","manual_shipping_fee":5000,"origin":ADDRESS,"credentials":{"api_key":"mock_shipping_api","webhook_secret":SHIP_SECRET}}
        await action(http,"integrated mock shipping setup",BASE+"/shipping-settings",method="PUT",headers=ha,data=shipping)
        await action(http,"customer login a again",store+"/login",data={"email":"phase4-buyer@gmail.com","password":buyer_password})
        cart=[{"pid":pid,"variant_id":vid,"qty":2}]
        rates=await action(http,"real persisted rate snapshot",store+"/gateway/rates",data={"items":cart,"shipping_address":ADDRESS})
        chosen=rates["rates"][0]
        integrated=await action(http,"integrated order snapshot",store+"/checkout",data={"items":cart,"shipping_address":ADDRESS,"shipping_rate_id":chosen["_id"],"payment_method":"gateway:qris","idempotency_key":"integrated-live"})
        check("integrated total correct",integrated["shipping_fee"]==6000 and integrated["payment"]["amount"]==26000)
        check("integrated paid",(await confirm(http,integrated,event_id="integrated-paid")).status_code==200)
        record=await a.db_handle.fulfillments.find_one({"order_id":integrated["_id"]})
        for status in ("packing","ready_to_ship"):
            await action(http,"integrated "+status,"/api/public/tenant/full/physical/orders/"+integrated["_id"]+"/fulfillments/"+record["_id"],headers=ha,data={"status":status})
        shipment=await action(http,"shipment create",BASE+"/shipments/"+integrated["_id"]+"/"+record["_id"],headers=ha)
        again=await action(http,"shipment create duplicate",BASE+"/shipments/"+integrated["_id"]+"/"+record["_id"],headers=ha)
        check("same shipment identity",again["provider_shipment_id"]==shipment["provider_shipment_id"])
        for _ in range(3): check("tracking delivery idempotent",(await tracking(http,shipment)).status_code==200)
        retbody={"idempotency_key":"return-live","item_lines":[{"line_id":integrated["items"][0]["line_id"],"quantity":1}],"reason":"Synthetic return"}
        returned=await action(http,"customer return request",store+"/orders/"+integrated["_id"]+"/returns",data=retbody)
        await action(http,"duplicate return request",store+"/orders/"+integrated["_id"]+"/returns",data=retbody)
        for status in ("reviewing","approved","received","inspected","inspected","resolved"):
            await action(http,"return "+status,BASE+"/returns/"+returned["_id"],headers=ha,data={"status":status,**({"resolution":"damaged"} if status=="inspected" else {})})
        check("damaged return no available increase",(await a.db_handle.physical_variants.find_one({"_id":vid}))["on_hand"]==26)
        await action(http,"return-linked partial refund",BASE+"/transactions/"+integrated["payment"]["_id"]+"/refunds",headers=ha,data={"idempotency_key":"return-refund","amount":10000,"return_id":returned["_id"]})
        await a.db_handle.settlement_entries.delete_many({})
        await action(http,"reconciliation repairs missing projection",BASE+"/reconciliation/repair",headers=ha)
        check("journal projection repaired",await a.db_handle.settlement_entries.count_documents({})==len((await Ledger(a.db_handle,a.tenant_id).get())["events"]))
        # Failure injection uses real receipt storage but a synthetic local DB
        # outage, with the provider/HTTP transports still explicitly mocked.
        outage_order=await action(http,"outage payment prepare",store+"/checkout",data={"items":cart,"shipping_address":ADDRESS,"shipping_rate_id":chosen["_id"],"payment_method":"gateway:qris","idempotency_key":"outage-live"})
        import payments.webhook as webhook_module
        import hashlib,hmac
        from pymongo.errors import AutoReconnect
        payment=outage_order["payment"]
        raw=json.dumps({"event_id":"outage-receipt","reference":payment["provider_reference"],"provider_payment_id":payment["provider_payment_id"],"amount":payment["amount"],"currency":"IDR","status":"paid"}).encode()
        signature=hmac.new(MOCK_SECRET.encode(),raw,hashlib.sha256).hexdigest()
        with patch.object(webhook_module,"_process_claim",AsyncMock(side_effect=AutoReconnect("synthetic local DB outage"))):
            try: await webhook_module.receive(platform,client,"kasera",raw,signature)
            except AutoReconnect: pass
        receipt=await platform.payment_events.find_one({"route_id":payment["_id"],"event_id":"outage-receipt"})
        check("real durable receipt survives injected local outage",receipt is not None and receipt["state"]=="accepted")
        await action(http,"real receipt reconciliation after outage",BASE+"/reconciliation/repair",headers=ha)
        check("outage recovery payment paid once",(await a.db_handle.order_payments.find_one({"_id":payment["_id"]}))["status"]=="paid")
        # Copying ciphertext to another tenant cannot change its binding.
        from shipping.service import config as shipping_config,shipping_adapter
        private=await shipping_config(a.db_handle,a.tenant_id)
        denied=False
        try: shipping_adapter(b.db_handle,b.tenant_id,private)
        except CommerceError: denied=True
        check("real shipping credential binding isolation",denied)
        await browser_checks(a,ha,password,buyer_password,products[0],http)
        from phase4_commerce import commerce
        commerce_perf = await commerce(a,check)
        (EVIDENCE/"commerce-smoke.json").write_text(json.dumps(commerce_perf,indent=2))
        from phase4_operations import operations
        await operations(client,platform,scopes,http,headers,EVIDENCE,check,stop,start,ready)
        core_collections = ["purchases","physical_variants","order_fulfillments","order_payments","settlement_accounts","integrated_shipments","return_requests","refund_requests","stock_journal_archive","settlement_journal_archive"]
        saved_counts = {name: await a.db_handle[name].count_documents({}) for name in core_collections}
        stop();start();await ready(http)
        check("restart preserves commerce journals and recovery records", all([await a.db_handle[name].count_documents({}) == count for name,count in saved_counts.items()]))
        (EVIDENCE/"restart-recovery.json").write_text(json.dumps({"backend_restart":True,"counts":saved_counts,"duplicate_callback_checked":True,"external_actions_retried":False},indent=2))
        check("restart callback idempotency",(await confirm(http,integrated,event_id="integrated-paid")).status_code==200)
        for scope in scopes:
            await ensure_indexes(scope.db_handle,platform);await ensure_indexes(scope.db_handle,platform)
        check("real unique route indexes",(await platform.payment_routes.index_information())["payment_route_reference"]["unique"])
        check("retained baseline tenants unchanged",await retained.tenants.count_documents({})==before)
    stop()
    log_text=(EVIDENCE/"runtime.log").read_text()
    check("secret-safe runtime logs",all(ENV[k] not in log_text for k in ("JWT_SECRET","INVENTORY_ENCRYPTION_KEY","ADMIN_PASSWORD","TELEGRAM_WEBHOOK_SECRET")) and MOCK_SECRET not in log_text and SHIP_SECRET not in log_text and password not in log_text and buyer_password not in log_text)
    return {"platform_database":ENV["DB_NAME"],"tenant_databases":[s.database_name for s in scopes],"mongo":"REAL dedicated localhost:27019","providers":"MOCKED Kasera platform/tenant, Midtrans tenant, shipping; no real charge/payout/SMTP/Telegram","browser":"REAL compiled React / Chromium"}

async def browser_checks(scope, owner_headers, password, buyer_password, product, http):
    """Real compiled React UI and live backend. Local proxy supplies registered Host."""
    from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
    import threading,urllib.request,urllib.error,urllib.parse
    from playwright.async_api import async_playwright
    host=scope.slug+".phase4.invalid"
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/"frontend/build"),**kwargs)
        def log_message(self,*args):pass
        def proxy(self):
            target=self.path
            if target.startswith("/api/public/host-config"):
                target="/api/public/host-config?host="+host
            headers={k:v for k,v in self.headers.items() if k.lower() not in {"host","content-length","connection"}}
            headers["X-Forwarded-Host"]=host
            body=self.rfile.read(int(self.headers.get("content-length",0))) or None
            request=urllib.request.Request("http://127.0.0.1:8006"+target,data=body,headers=headers,method=self.command)
            try:response=urllib.request.urlopen(request,timeout=20)
            except urllib.error.HTTPError as error:response=error
            with response:
                payload=response.read();self.send_response(response.status)
                for key,value in response.headers.items():
                    if key.lower() not in {"content-length","connection","transfer-encoding"}:self.send_header(key,value)
                self.send_header("Content-Length",str(len(payload)));self.end_headers()
                try:self.wfile.write(payload)
                except BrokenPipeError:pass
        def do_GET(self):
            if self.path.startswith("/api/"):return self.proxy()
            if not (ROOT/"frontend/build"/self.path.lstrip("/").split("?")[0]).is_file():self.path="/index.html"
            super().do_GET()
        def do_POST(self):self.proxy()
        def do_PUT(self):self.proxy()
        def do_DELETE(self):self.proxy()
    server=ThreadingHTTPServer(("127.0.0.1",3006),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(headless=True,args=["--no-sandbox"])
            ctx=await browser.new_context(viewport={"width":1440,"height":1100})
            page=await ctx.new_page();errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
            await page.goto("http://127.0.0.1:3006/admin")
            await page.get_by_placeholder("Email",exact=True).fill(scope.slug+"@gmail.com")
            await page.get_by_placeholder("Password",exact=True).fill(password)
            await page.get_by_role("button",name="Masuk",exact=True).click()
            await page.get_by_role("button",name="Branding",exact=True).click()
            await page.get_by_label("brand_name",exact=True).fill("Phase4 Brand A")
            await page.get_by_label("receipt_footer",exact=True).fill("Terima kasih dari Brand A")
            await page.get_by_role("button",name="Simpan branding",exact=True).click()
            await page.get_by_text("Branding tersimpan.",exact=True).wait_for()
            await page.get_by_role("button",name="Preview receipt",exact=True).click()
            await page.frame_locator('iframe[title="Preview receipt"]').get_by_role("heading",name="Phase4 Brand A",exact=True).wait_for()
            check("browser owner branding save preview",True)
            await page.screenshot(path=str(EVIDENCE/"branding-owner.png"),full_page=True)
            await page.get_by_role("button",name="Payments",exact=True).click()
            await page.get_by_role("heading",name="Payments — Pengaturan pembayaran").wait_for()
            await page.get_by_role("button",name="Test Connection",exact=True).click()
            await page.get_by_text("Test Connection selesai; lihat capability snapshot.",exact=True).wait_for()
            check("browser Payment Settings Test Connection capabilities",await page.get_by_text("Metode: qris, va_bca, va_bni",exact=True).is_visible())
            await page.screenshot(path=str(EVIDENCE/"payment-settings-settlement.png"),full_page=True)
            for stage in ("clearing","available"):
                buttons=page.get_by_role("button",name=stage,exact=True)
                for i in range(await buttons.count()):
                    await buttons.nth(i).click()
                    await page.get_by_text("Settlement "+stage+" dicatat.",exact=True).wait_for()
            await page.get_by_label("Jumlah payout",exact=True).fill("1000")
            await page.get_by_role("button",name="Ajukan payout simulasi",exact=True).click()
            await page.get_by_text("Dana payout dicadangkan; belum dikirim ke bank.",exact=True).wait_for()
            check("browser settlement payout reservation",True)
            await page.get_by_role("button",name="Shipping",exact=True).click()
            await page.get_by_role("heading",name="Shipping — Pengaturan / Providers / Shipments").wait_for()
            await page.get_by_text("Provider Mock Courier (MOCKED). Kredensial mock harus diawali mock_.",exact=True).wait_for()
            check("browser shipping provider settings",await page.get_by_text("Provider Mock Courier (MOCKED). Kredensial mock harus diawali mock_.",exact=True).is_visible())
            await page.screenshot(path=str(EVIDENCE/"shipping-settings.png"),full_page=True)
            buyerctx=await browser.new_context(viewport={"width":1280,"height":1000})
            buyer=await buyerctx.new_page();buyer.on("pageerror",lambda e:errors.append(str(e)))
            await buyer.goto("http://127.0.0.1:3006/store/login")
            await buyer.get_by_label("Email",exact=True).fill("phase4-buyer@gmail.com")
            await buyer.get_by_label("Kata sandi",exact=True).fill(buyer_password)
            await buyer.get_by_role("button",name="Masuk",exact=True).click()
            await buyer.wait_for_url("**/store/profile")
            # A fixture seeds a cart; checkout itself is completed through React.
            await buyer.evaluate("items => localStorage.setItem('store_cart:127.0.0.1', JSON.stringify(items))",[{"pid":product[0],"variant_id":product[1],"qty":2}])
            await buyer.goto("http://127.0.0.1:3006/store/cart")
            await buyer.get_by_role("heading",name="Keranjang",exact=True).wait_for()
            for label,key in [("Nama penerima","recipient_name"),("Telepon","phone"),("Alamat","address_line_1"),("Kota / Kabupaten","city"),("Provinsi","province"),("Kode pos","postal_code")]:
                await buyer.get_by_label(label,exact=True).fill(ADDRESS[key])
            await buyer.get_by_role("radio",name="QRIS",exact=True).check()
            await buyer.get_by_role("radio",name="Mock Regular",exact=False).check()
            check("browser valid payment and shipping choices",True)
            await buyer.screenshot(path=str(EVIDENCE/"customer-method-shipping.png"),full_page=True)
            async with buyer.expect_response(lambda r:r.url.endswith('/api/store/checkout') and r.request.method=='POST') as response:
                await buyer.get_by_role("button",name="Bayar dengan QRIS",exact=True).click()
            order=await (await response.value).json()
            check("browser gateway checkout amount",order.get("payment",{}).get("amount")==26000)
            await buyer.get_by_role("button",name="Tutup status checkout",exact=True).click()
            await buyer.get_by_role("button").filter(has_text=order["invoice_id"]).first.click()
            await buyer.get_by_role("heading",name="Status pembayaran",exact=True).wait_for()
            check("browser pending payment expiry",await buyer.get_by_text("Berlaku sampai",exact=False).is_visible())
            check("browser payment confirmation",(await confirm(http,order,event_id="browser-paid")).status_code==200)
            await page.get_by_label("Order untuk shipment",exact=True).fill(order["_id"])
            await page.get_by_role("button",name="Muat order shipment",exact=True).click()
            await page.get_by_role("button",name="Packing",exact=True).click()
            await page.get_by_role("button",name="Ready to ship",exact=True).click()
            await page.get_by_role("button",name="Buat shipment",exact=True).click()
            await page.get_by_text("Shipment dibuat (MOCKED).",exact=True).wait_for()
            shipment=await scope.db_handle.integrated_shipments.find_one({"order_id":order["_id"]})
            check("browser shipment creation",shipment is not None)
            check("browser shipment tracking event",(await tracking(http,shipment,event_id="browser-delivered")).status_code==200)
            await buyer.reload();await buyer.get_by_role("button").filter(has_text=order["invoice_id"]).first.click()
            await buyer.get_by_text(shipment["tracking_number"],exact=True).wait_for()
            check("browser customer tracking",True)
            await buyer.get_by_label("Jumlah return PHASE3-SKU",exact=True).fill("1")
            await buyer.get_by_label("Alasan return",exact=True).fill("Browser inspected return")
            await buyer.get_by_role("button",name="Ajukan return",exact=True).click()
            await buyer.get_by_text("Return: return_requested",exact=False).wait_for()
            check("browser customer return request",True)
            await page.get_by_role("button",name="Returns / Refunds",exact=True).click()
            row=page.locator('div.rounded.border').filter(has_text="Browser inspected return").first
            for state in ("reviewing","approved","received","Inspect restock","resolved"):
                await row.get_by_role("button",name=state,exact=True).click()
                await page.get_by_role("button",name=state,exact=True).wait_for(state="hidden")
            check("browser owner review receive inspect restock",True)
            returned=await scope.db_handle.return_requests.find_one({"order_id":order["_id"]})
            await page.get_by_label("Jumlah refund (Rupiah)",exact=True).fill("10000")
            await page.get_by_label("Return ID (opsional, harus sudah inspected)",exact=True).fill(returned["_id"])
            await page.get_by_role("button",name="Ajukan refund "+order["_id"][:8],exact=True).click()
            await page.get_by_text("Permintaan refund dicatat. Periksa status hasilnya.",exact=True).wait_for()
            payment=await scope.db_handle.order_payments.find_one({"order_id":order["_id"]})
            check("browser approved partial refund",payment["refunded_amount"]==10000 and payment["status"]=="partially_refunded")
            await page.screenshot(path=str(EVIDENCE/"owner-return-refund.png"),full_page=True)
            await buyer.screenshot(path=str(EVIDENCE/"customer-tracking-return.png"),full_page=True)
            receipt = await http.get(f"/api/store/t/{scope.slug}/orders/{order['_id']}/receipt")
            # Customer browser request carries its tenant cookie.
            receipt = await buyer.request.get(f"http://127.0.0.1:3006/api/store/orders/{order['_id']}/receipt")
            check("browser customer branded receipt",receipt.status==200 and "Phase4 Brand A" in await receipt.text())
            for mode,name in [("platform","SellerBottel"),("co_branded","Phase4 Brand A"),("tenant_only","Phase4 Brand A")]:
                if mode=="tenant_only":
                    await client[ENV['DB_NAME']].tenants.update_one({'_id':scope.tenant_id},{'$set':{'metadata.capabilities.can_white_label':True}})
                changed=await http.put('/api/public/tenant/full/branding',headers=owner_headers,json={'mode':mode,'brand_name':'Phase4 Brand A'})
                check('branding mode API '+mode,changed.status_code==200)
                await buyer.goto('http://127.0.0.1:3006/store/cart')
                await buyer.wait_for_function('(name) => document.title === name',arg=name)
                check('browser branding checkout '+mode,await buyer.title()==name)
                check('browser attribution '+mode,await buyer.get_by_text('Powered by SellerBottel',exact=True).count()==(1 if mode=='co_branded' else 0))
                await buyer.screenshot(path=str(EVIDENCE/('branding-'+mode+'.png')),full_page=True)
                mode_receipt = await buyer.request.get(f"http://127.0.0.1:3006/api/store/orders/{order['_id']}/receipt")
                check('browser receipt branding '+mode,mode_receipt.status==200 and '<h1>'+name+'</h1>' in await mode_receipt.text())
                await buyer.goto('http://127.0.0.1:3006/store/orders')
                await buyer.get_by_role('button').filter(has_text=order['invoice_id']).first.click()
                await buyer.get_by_text(shipment['tracking_number'],exact=True).wait_for()
                check('browser tracking branding '+mode,await buyer.title()==name)
            check("browser no React errors",not errors)
            await browser.close()
    finally:
        server.shutdown();server.server_close()

if __name__ == "__main__":
    details={}
    try: details=asyncio.run(run())
    finally:
        stop(); (EVIDENCE/"live-results.json").write_text(json.dumps({**details,"checks":results},indent=2)+"\n");client.close()
    print(json.dumps({"passed":sum(r["result"]=="PASS" for r in results),"failed":sum(r["result"]=="FAIL" for r in results)}))
