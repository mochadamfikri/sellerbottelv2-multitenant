"""Additional live HTTP import/deletion and real-Mongo mocked SMTP retry checks."""
import asyncio
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1]
config=dotenv_values(ROOT/"backend/.env.live-e2e")
if not config.get("MONGO_URL", "").startswith("mongodb://127.0.0.1:27019/"):
    raise SystemExit("Unsafe E2E configuration")
os.environ.clear(); os.environ.update(config)
sys.path.insert(0,str(ROOT/"backend"))
import httpx
from db import client
from auth import create_access_token
import server

async def main():
    checks=[]
    def check(name,condition,**details):
        checks.append({"test":name,"result":"PASS" if condition else "FAIL",**details})
    platform=client[config["PLATFORM_DB_NAME"]]
    for label in "ab":
        slug="e2e-tenant-"+label
        owner=await platform.tenant_owners.find_one({"tenant_slug":slug})
        h={"Authorization":"Bearer "+create_access_token(str(owner["_id"]),owner["email"])}
        db=client["sellerbottel_tenant_e2e_tenant_"+label]
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8002",timeout=20) as http:
            content=f"katalog,product,jenis (inventory/jasa),Harga\nImport {label},Imported {label},inventory,12000\n"
            r=await http.post("/api/public/tenant/full/products/import",headers=h,files={"file":("products.csv",content.encode(),"text/csv")})
            product=await db.products.find_one({"name":"Imported "+label})
            check("live product CSV import "+label,r.status_code==200 and product is not None,status=r.status_code)
            if product:
                r=await http.delete("/api/public/tenant/full/products/"+product["_id"],headers=h)
                check("live own product deletion "+label,r.status_code==200 and await db.products.find_one({"_id":product["_id"]}) is None,status=r.status_code)
        await db.purchases.replace_one({"_id":"smtp-mock-retry"},{"_id":"smtp-mock-retry","status":"delivered","delivery_email_status":"failed","customer_email":"idsegwork@gmail.com","currency":"IDR","total":0,"invoice_id":"DEV-MOCK-"+label,"items":[{"name":"E2E Store "+label.upper(),"qty":1,"unit_price":0,"subtotal":0,"delivery_type":"service"}]},upsert=True)
        class FailingSMTP:
            def __init__(self,*args,**kwargs):
                raise ConnectionError("controlled development SMTP failure")
        captured=[]
        class SuccessfulSMTP:
            def __init__(self,*args,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def starttls(self): pass
            def login(self,*args): pass
            def send_message(self,msg): captured.append(msg.get_body(preferencelist=("plain",)).get_content())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url="http://local",headers=h) as http:
            with patch("smtplib.SMTP",FailingSMTP),patch("smtplib.SMTP_SSL",FailingSMTP):
                r=await http.post("/api/public/tenant/full/orders/smtp-mock-retry/email/retry")
            check("real Mongo SMTP failure state "+label,(await db.purchases.find_one({"_id":"smtp-mock-retry"}))["delivery_email_status"]=="failed",status=r.status_code)
            with patch("smtplib.SMTP",SuccessfulSMTP),patch("smtplib.SMTP_SSL",SuccessfulSMTP):
                r=await http.post("/api/public/tenant/full/orders/smtp-mock-retry/email/retry")
            check("real Mongo SMTP retry state "+label,r.status_code==200 and (await db.purchases.find_one({"_id":"smtp-mock-retry"}))["delivery_email_status"]=="sent")
            check("mock captured receipt tenant content "+label,bool(captured) and "E2E Store "+label.upper() in captured[0] and "E2E Store "+("B" if label=="a" else "A") not in captured[0])
    (ROOT/"test_reports/live-dev-e2e-20261008/additional-results.json").write_text(json.dumps(checks,indent=2)+"\n")
    print(json.dumps({"passed":sum(c["result"]=="PASS" for c in checks),"failed":sum(c["result"]=="FAIL" for c in checks)}))
    client.close()

asyncio.run(main())
