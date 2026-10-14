"""C2 acceptance on dedicated dev Mongo: isolated fresh databases, no .env/reset.

HTTP API uses localhost:8004. Delivery/provider/notification transports are mocked;
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
ENV = {"COOKIE_SECURE": "false", "PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "PYTHON_DOTENV_DISABLED": "1",
    "ENVIRONMENT": "development", "MONGO_URL": "mongodb://127.0.0.1:27019/?serverSelectionTimeoutMS=1500",
    "DB_NAME": "sellerbottel_c2_dev_" + nonce, "PLATFORM_DB_NAME": "sellerbottel_c2_dev_" + nonce,
    "JWT_SECRET": secrets.token_urlsafe(48), "INVENTORY_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "TELEGRAM_WEBHOOK_SECRET": secrets.token_urlsafe(32), "CORS_ORIGINS": "http://127.0.0.1:3004",
    "TENANT_BASE_DOMAIN": "c2.invalid", "ADMIN_EMAIL": "admin@c2.invalid", "ADMIN_PASSWORD": secrets.token_urlsafe(24),
    "GOPAY_ENABLED": "false", "BOT2_ENABLED": "false", "PROMOTION_ENABLED": "false",
    "LOCAL_STORAGE_DIR": str(ROOT / "backend/storage_data/c2-dev")}
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

EVIDENCE = ROOT / "test_reports/phase-c2-physical-commerce-20261008"
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
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8004"],
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

async def browser_checks(scope, email, password, buyer_password):
    """Real compiled React UI and live backend. Local proxy supplies registered Host."""
    from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
    import threading,urllib.request,urllib.error,urllib.parse
    from playwright.async_api import async_playwright
    host=scope.slug+".c2.invalid"
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
            request=urllib.request.Request("http://127.0.0.1:8004"+target,data=body,headers=headers,method=self.command)
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
    server=ThreadingHTTPServer(("127.0.0.1",3004),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True,args=["--no-sandbox"])
            ctx=await browser.new_context(viewport={"width":1440,"height":1100})
            page=await ctx.new_page();errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
            await page.goto("http://127.0.0.1:3004/admin")
            await page.get_by_placeholder("Email",exact=True).fill(email)
            await page.get_by_placeholder("Password",exact=True).fill(password)
            await page.get_by_role("button",name="Masuk",exact=True).click()
            await page.get_by_role("button",name="Produk",exact=True).click()
            await page.get_by_role("button",name="Kelola produk fisik / variant / stok").click()
            physical=page.get_by_role("region",name="Produk fisik")
            await physical.get_by_label("Nama produk fisik").fill("Browser physical")
            await physical.get_by_label("Harga IDR",exact=True).fill("15000")
            await physical.get_by_label("Katalog",exact=True).fill("C2 Browser")
            await physical.get_by_role("button",name="Simpan produk fisik",exact=True).click()
            await physical.get_by_label("SKU",exact=True).fill("BROWSER-SKU")
            await physical.get_by_role("button",name="Tambah opsi",exact=True).click()
            await physical.get_by_label("Nama opsi 1").fill("material")
            await physical.get_by_label("Nilai opsi 1").fill("Cotton")
            await physical.get_by_role("button",name="Tambah variant",exact=True).click()
            await physical.get_by_label("Variant stok").select_option(label="BROWSER-SKU")
            await physical.get_by_label("Jumlah stok").fill("4")
            await physical.get_by_label("Alasan stok").fill("Browser receipt")
            await physical.get_by_role("button",name="Catat pergerakan").click()
            await physical.get_by_text("RECEIVE · 4 · Browser receipt",exact=True).wait_for()
            await page.screenshot(path=str(EVIDENCE/"tenant-physical-products.png"),full_page=True)
            check("browser physical product variant options stock authoring",True)
            buyer=await ctx.new_page();buyer.on("pageerror",lambda error:errors.append(str(error)))
            await buyer.goto("http://127.0.0.1:3004/store/login")
            await buyer.get_by_label("Email",exact=True).fill("c2-buyer@gmail.com")
            await buyer.get_by_label("Kata sandi",exact=True).fill(buyer_password)
            await buyer.get_by_role("button",name="Masuk",exact=True).click()
            await buyer.wait_for_url("**/store/profile")
            await buyer.goto("http://127.0.0.1:3004/store/products")
            await buyer.get_by_role("link").filter(has_text="C2 Browser").first.click()
            await buyer.get_by_role("link",name="Browser physical",exact=True).first.click()
            await buyer.get_by_role("button",name="Cotton · 4 tersedia",exact=True).click()
            await buyer.get_by_role("button",name="Tambah ke keranjang",exact=True).click()
            await buyer.get_by_role("button",name="Menambahkan ke keranjang…").wait_for(state="hidden",timeout=15000)
            await buyer.get_by_role("link",name="Lihat keranjang",exact=True).click()
            await buyer.get_by_role("heading",name="Keranjang",exact=True).wait_for()
            await buyer.locator("input[value=balance]").check()
            check("browser physical checkout requires address",await buyer.get_by_role("button",name="Bayar dengan Saldo").is_disabled())
            for label,key in [("Nama penerima","recipient_name"),("Telepon","phone"),("Alamat","address_line_1"),("Kota / Kabupaten","city"),("Provinsi","province"),("Kode pos","postal_code")]:
                await buyer.get_by_label(label,exact=True).fill(ADDRESS[key])
            await buyer.get_by_text("Ongkir manual",exact=True).wait_for()
            await buyer.screenshot(path=str(EVIDENCE/"storefront-physical-checkout.png"),full_page=True)
            await buyer.get_by_role("button",name="Bayar dengan Saldo").click()
            await buyer.wait_for_url("**/store/orders")
            await buyer.get_by_role("button",name="Tutup status checkout",exact=True).click()
            order=await scope.db_handle.purchases.find_one({"items.sku":"BROWSER-SKU"})
            check("browser physical balance checkout",order is not None and order["shipping_fee"]==5000 and order["status"]=="physical_pending")
            await page.get_by_role("button",name="Order",exact=True).click()
            row=page.get_by_role("row").filter(has_text=order["invoice_id"])
            await row.get_by_role("button",name="Detail",exact=True).click()
            for action in ("Tandai dikemas","Tandai siap dikirim"):
                await page.get_by_role("button",name=action,exact=True).click()
            await page.get_by_label("Kurir BROWSER-SKU").fill("Manual Browser Courier")
            await page.get_by_label("Resi BROWSER-SKU").fill("BROWSER-TRACK-1")
            await page.get_by_role("button",name="Tandai dikirim",exact=True).click()
            await page.get_by_role("button",name="Tandai diterima",exact=True).wait_for()
            await page.screenshot(path=str(EVIDENCE/"tenant-physical-tracking.png"),full_page=True)
            await page.get_by_role("button",name="Tandai diterima",exact=True).click()
            await buyer.reload()
            await buyer.get_by_role("button").filter(has_text=order["invoice_id"]).first.click()
            await buyer.get_by_text("BROWSER-TRACK-1",exact=True).wait_for()
            await buyer.screenshot(path=str(EVIDENCE/"customer-physical-tracking.png"),full_page=True)
            check("browser packing shipping delivered customer tracking",True)
            check("browser no unhandled React errors",not errors)
            await browser.close()
    finally:server.shutdown();server.server_close()

async def run():
    limits=subprocess.check_output(["sudo","-n","docker","exec","sellerbottelv2-dev-mongo","cat","/proc/1/limits"],text=True)
    limit=next(row.split()[3] for row in limits.splitlines() if row.startswith("Max open files"))
    check("dedicated Mongo file limit",limit=="unlimited" or int(limit)>=65535)
    platform=client[ENV["DB_NAME"]];retained=client.sellerbottel_live_e2e_dev
    before=await retained.tenants.count_documents({})
    check("real dedicated Mongo ping",(await client.admin.command("ping"))["ok"]==1)
    check("fresh C2 platform",not await platform.list_collection_names())
    start();scopes=[];headers=[];products=[];password=secrets.token_urlsafe(24);buyer_password=secrets.token_urlsafe(24)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8004",timeout=30) as http:
        await ready(http);check("HTTP backend startup",True)
        for label in "ab":
            slug="c2-"+label+"-"+nonce;email=slug+"@gmail.com";verified=secrets.token_urlsafe(24)
            await platform.public_reg_verified.insert_one({"email":email,"verify_token":verified,"expires_at":datetime.now(timezone.utc)+timedelta(minutes=10)})
            response=await http.post("/api/public/register",json={"username":slug,"email":email,"store_name":"C2 "+label,"password":password,"whatsapp":"081234567890","verify_token":verified})
            check("HTTP tenant provisioning "+label,response.status_code==201)
            tenant=await platform.tenants.find_one({"slug":slug});database=client[tenant["database_name"]]
            scope=BotTenantScope(tenant_id=str(tenant["_id"]),slug=slug,database_name=database.name,db_handle=database,bot_token="unused");scopes.append(scope)
            response=await http.post("/api/public/tenant/login",json={"email":email,"password":password});check("HTTP owner login "+label,response.status_code==200)
            headers.append({"Authorization":"Bearer "+response.json()["token"]})
            base="/api/public/tenant/full/physical"
            response=await http.post(base+"/products",headers=headers[-1],json={"name":"Hoodie "+label,"price_idr":10000,"has_variants":True,"default_weight":300})
            check("HTTP physical authoring "+label,response.status_code==200);pid=response.json()["_id"]
            response=await http.post(base+f"/products/{pid}/variants",headers=headers[-1],json={"sku":"same-sku","option_values":{"size":"L","material":"Cotton"},"price_override":12000,"weight":300})
            check("HTTP variant normalized SKU "+label,response.status_code==200 and response.json()["sku"]=="SAME-SKU");vid=response.json()["_id"];products.append((pid,vid))
            response=await http.post(base+f"/variants/{vid}/stock",headers=headers[-1],json={"type":"RECEIVE","quantity":20,"reference_id":"initial-receipt","reason":"Synthetic opening"})
            check("HTTP stock receive "+label,response.status_code==200)
            check("real unique SKU index "+label,(await database.physical_variants.index_information())["physical_sku_unique"]["unique"])
            response=await http.put(base+"/shipping",headers=headers[-1],json={"manual_shipping_fee":5000});check("HTTP manual shipping settings "+label,response.status_code==200)
            await database.store_customers.insert_one({"_id":"same-customer","email":"c2-buyer@gmail.com","password_hash":hash_password(buyer_password),"balance_idr":1000000,"currency":"IDR"})
            await database.settings.update_one({"_id":"main"},{"$set":{"manual_shipping_fee":5000,"store_qris_enabled":True,"require_channel_join":False}})
            await register_domain(client,domain=slug+".c2.invalid",tenant_id=scope.tenant_id,purpose="storefront")
        a,b=scopes;pid,vid=products[0];base="/api/public/tenant/full/physical"
        for path in (f"/products/{products[1][0]}/variants",f"/variants/{products[1][1]}/stock-movements","/orders/foreign-order"):
            check("HTTP cross tenant denied "+path,(await http.get(base+path,headers=headers[0])).status_code==404)
        await http.post("/api/store/t/"+a.slug+"/login",json={"email":"c2-buyer@gmail.com","password":buyer_password})
        check("same-ID customer cookie foreign tenant denied",(await http.get("/api/store/t/"+b.slug+"/me")).status_code==401)
        items=[{"pid":pid,"variant_id":vid,"qty":2}]
        response=await http.post("/api/store/t/"+a.slug+"/quote",json={"items":items});check("HTTP physical quote shipping included",response.status_code==200 and response.json()["total"]==29000)
        response=await http.post("/api/store/t/"+a.slug+"/checkout",json={"items":items,"payment_method":"balance","idempotency_key":"physical-live","shipping_address":ADDRESS})
        check("HTTP physical balance checkout",response.status_code==200 and response.json()["status"]=="physical_pending");order=response.json();oid=order["_id"]
        response2=await http.post("/api/store/t/"+a.slug+"/checkout",json={"items":items,"payment_method":"balance","idempotency_key":"physical-live","shipping_address":ADDRESS})
        check("HTTP repeated checkout no double payment",response2.status_code==200 and response2.json()["_id"]==oid and (await a.db_handle.store_customers.find_one({"_id":"same-customer"}))["balance_idr"]==971000)
        check("address and variant immutable snapshot",order["shipping_address"]["city"]=="Bandung" and order["items"][0]["sku"]=="SAME-SKU")
        async with use_bot_tenant(a):
            stock=PhysicalStock(a.db_handle)
            check("balance reservation consumed once",await a.db_handle.stock_movements.count_documents({"type":"SALE"})==1 and (await stock.get(vid))["reserved"]==0)
            record=await a.db_handle.fulfillments.find_one({"order_id":oid});fid=record["_id"]
            check("foreign shipment fulfillment denied",(await http.post(base+f"/orders/{oid}/fulfillments/{fid}",headers=headers[1],json={"status":"packing"})).status_code==404)
            for state in ("packing","ready_to_ship","shipped","delivered"):
                payload={"status":state,**({"carrier_name":"Manual Carrier","tracking_number":"LIVE-TRACK-1"} if state=="shipped" else {})}
                response=await http.post(base+f"/orders/{oid}/fulfillments/{fid}",headers=headers[0],json=payload)
                check("HTTP shipment "+state,response.status_code==200)
                check("HTTP repeated shipment "+state,(await http.post(base+f"/orders/{oid}/fulfillments/{fid}",headers=headers[0],json=payload)).status_code==200)
            check("shipment collection delivered",(await a.db_handle.shipments.find_one({"fulfillment_id":fid}))["status"]=="delivered")
            await a.db_handle.products.insert_one({"_id":"race-product","fulfillment_type":"physical","active":True})
            race=await create_variant(a.db_handle,"race-product",VariantBody(sku="LAST-UNIT"));await stock.move(race["_id"],"RECEIVE",1,reference_id="opening")
            attempts=await asyncio.gather(*(stock.move(race["_id"],"RESERVATION",1,reference_id=f"race-{i}") for i in range(20)),return_exceptions=True)
            check("real Mongo twenty concurrent buyers last unit one winner",sum(isinstance(x,dict) for x in attempts)==1)
            winner=next(x for x in attempts if isinstance(x,dict));await stock.move(race["_id"],"RELEASE",1,reference_id=winner["reference_id"])
            check("real Mongo release restores availability",(await stock.get(race["_id"]))["reserved"]==0)
            await a.db_handle.products.update_one({"_id":"race-product"},{"$set":{"name":"Last checkout","price_idr":1000}})
            for cid in ("race-buyer-a","race-buyer-b"):
                await a.db_handle.store_customers.insert_one({"_id":cid,"email":cid+"@gmail.com","balance_idr":10000,"currency":"IDR"})
            buyers=[await a.db_handle.store_customers.find_one({"_id":cid}) for cid in ("race-buyer-a","race-buyer-b")]
            outcome=await asyncio.gather(*(checkout.execute_checkout({**buyer,"customer_id":buyer["_id"]},[{"pid":"race-product","variant_id":race["_id"],"qty":1}],purchase_source="WEB",shipping_address=ADDRESS) for buyer in buyers))
            check("real Mongo simultaneous wallet checkouts one winner",sum(result["ok"] for result in outcome)==1)
            check("real Mongo checkout invariant and loser wallet preserved",(await stock.get(race["_id"]))["on_hand"]==0 and (await stock.get(race["_id"]))["reserved"]==0 and sorted([(await a.db_handle.store_customers.find_one({"_id":cid}))["balance_idr"] for cid in ("race-buyer-a","race-buyer-b")])==[4000,10000])
            with patch("direct_checkout.store_qris_ready",AsyncMock(return_value=True)),patch("direct_checkout._run_node",lambda *args:{"image_base64":base64.b64encode(b"mock-qr").decode()}),patch("services.notify_transaction_channel_safely",AsyncMock()),patch("services.notify_admin",AsyncMock()):
                customer=await a.db_handle.store_customers.find_one({"_id":"same-customer"})
                result=await direct_checkout.create_store_qris_order(customer,[{"pid":pid,"variant_id":vid,"qty":1}],shipping_address=ADDRESS)
                check("real Mongo QRIS mock reservation",(await stock.get(vid))["reserved"]==1)
                from commerce.fulfillment.repository import FulfillmentRepository
                with patch.object(FulfillmentRepository,"create",AsyncMock(side_effect=RuntimeError("synthetic fulfillment insert outage"))):
                    check("paid fulfillment insert failure preserved",not await direct_checkout.finalize_qris_order(result["order"]["_id"],"mock-paid"))
                failed=await a.db_handle.purchases.find_one({"_id":result["order"]["_id"]});check("failed paid order recoverable reserved stock",failed["status"]=="delivery_failed" and (await stock.get(vid))["reserved"]==1)
                response=await http.post(base+f"/orders/{failed['_id']}/recover",headers=headers[0]);check("HTTP explicit paid initialization recovery",response.status_code==200 and (await stock.get(vid))["reserved"]==0)
                check("duplicate payment event no double sale",not await direct_checkout.finalize_qris_order(failed["_id"],"mock-paid") and await a.db_handle.stock_movements.count_documents({"type":"SALE","variant_id":vid})==2)
                await a.db_handle.products.insert_one({"_id":"mixed-digital","name":"Synthetic digital","delivery_type":"link","content":"SYNTHETIC-DIGITAL","active":True,"price_idr":1000})
                result=await checkout.execute_checkout({**customer,"customer_id":customer["_id"]},[{"pid":"mixed-digital","qty":1},{"pid":pid,"variant_id":vid,"qty":1}],purchase_source="WEB",shipping_address=ADDRESS)
                check("real Mongo mixed digital physical one order",result["ok"] and len(result["order"]["items"])==2)
                from storefront_routes import _finalize_store_balance_order
                await _finalize_store_balance_order(result["order"]["_id"])
                records=await a.db_handle.fulfillments.find({"order_id":result["order"]["_id"]}).to_list(None)
                check("real Mongo mixed separate durable fulfillments",{r["status"] for r in records}=={"pending","delivered"})
        async with use_bot_tenant(a):
            with patch("direct_checkout.store_qris_ready",AsyncMock(return_value=True)),patch("direct_checkout._run_node",lambda *args:{"image_base64":base64.b64encode(b"mock-qr").decode()}):
                customer=await a.db_handle.store_customers.find_one({"_id":"same-customer"})
                expiry_result=await direct_checkout.create_store_qris_order(customer,[{"pid":pid,"variant_id":vid,"qty":1}],shipping_address=ADDRESS)
                await a.db_handle.purchases.update_one({"_id":expiry_result["order"]["_id"]},{"$set":{"expires_at":(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()}})
        from commerce.physical.expiry import expire_physical_tenants
        await expire_physical_tenants();await expire_physical_tenants()
        check("real Mongo storefront-only provider-free expiry releases once",(await a.db_handle.purchases.find_one({"_id":expiry_result["order"]["_id"]}))["status"]=="expired" and (await a.db_handle.physical_variants.find_one({"_id":vid}))["reserved"]==0)
        await browser_checks(a,a.slug+"@gmail.com",password,buyer_password)
        stop();start();await ready(http)
        check("backend restart preserves stock shipment",(await http.get(base+f"/orders/{oid}",headers=headers[0])).status_code==200 and (await a.db_handle.shipments.find_one({"fulfillment_id":fid}))["status"]=="delivered")
        for scope in scopes:
            await physical_indexes(scope.db_handle);await physical_indexes(scope.db_handle)
        check("repeat index initialization idempotent",True)
        check("retained tenants unchanged",await retained.tenants.count_documents({})==before)
    stop()
    log_text=(EVIDENCE/"runtime.log").read_text()
    check("secret-safe runtime logs",all(ENV[key] not in log_text for key in ("JWT_SECRET","INVENTORY_ENCRYPTION_KEY","ADMIN_PASSWORD","TELEGRAM_WEBHOOK_SECRET")) and password not in log_text and buyer_password not in log_text)
    return {"platform_database":ENV["DB_NAME"],"tenant_databases":[s.database_name for s in scopes],"mongo":"real dedicated localhost:27019","providers":"mocked, no real SMTP/Telegram/payment requests","browser":"compiled React in Chromium"}

if __name__=="__main__":
    details={}
    try:details=asyncio.run(run())
    finally:
        stop();(EVIDENCE/"live-results.json").write_text(json.dumps({**details,"checks":results},indent=2)+"\n");client.close()
    print(json.dumps({"passed":sum(r["result"]=="PASS" for r in results),"failed":sum(r["result"]=="FAIL" for r in results)}))
