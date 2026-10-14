"""Read only confirmed development bot; send SMTP only to authorized test recipient.

Never applies .env Mongo/payment configuration. Does not change Telegram webhook.
"""
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from dotenv import dotenv_values
settings=dotenv_values(ROOT/"backend/.env")
from live_dev_e2e import ENV, EVIDENCE
for k,v in settings.items():
    if k.startswith("SMTP_") and v:
        os.environ[k]=v
import httpx
from db import client
from bot_tenant_scope import BotTenantScope, _install, _restore
from storefront_routes import send_order_completion_email

async def main():
    evidence={}
    for name in ("TELEGRAM_TOKEN","BOT2_TELEGRAM_TOKEN"):
        token=settings.get(name)
        if not token:
            evidence[name]={"result":"NOT RUN","reason":"development token not configured"}
            continue
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                response=await http.get("https://api.telegram.org/bot"+token+"/getMe")
                data=response.json()
                evidence[name]={"result":"PASS" if data.get("ok") else "FAIL","getMe_ok":bool(data.get("ok")),"http_status":response.status_code,"telegram_error_code":data.get("error_code"),"bot_id":data.get("result",{}).get("id"),"bot_username":data.get("result",{}).get("username")}
                response=await http.get("https://api.telegram.org/bot"+token+"/getWebhookInfo")
                info=response.json().get("result",{})
                evidence[name]["existing_webhook_present"]=bool(info.get("url"))
                evidence[name]["live_user_flows"]="NOT RUN — no dedicated second bot or user interaction"
        except Exception as error:
            evidence[name]={"result":"NOT RUN","exception_class":type(error).__name__}
    db=client["sellerbottel_tenant_e2e_tenant_a"]
    order={"_id":"smtp-live-dev","status":"delivered","customer_email":"idsegwork@gmail.com","customer_name":"Development E2E recipient","currency":"IDR","total":0,"invoice_id":"DEV-E2E-SMTP-20261008","items":[{"name":"E2E Store A — development email only","qty":1,"unit_price":0,"subtotal":0,"delivery_type":"service"}]}
    if "--telegram-only" in sys.argv:
        client.close()
        (EVIDENCE/"telegram.json").write_text(json.dumps(evidence,indent=2)+"\n")
        print(json.dumps(evidence))
        return
    await db.purchases.insert_one(order)
    scope=_install(BotTenantScope(tenant_id="e2e-tenant-a",slug="e2e-tenant-a",database_name=db.name,db_handle=db,bot_token="unconfigured-tenant-bot",brand_name="E2E Store A"))
    try:
        delivered=await send_order_completion_email(order["_id"])
        current=await db.purchases.find_one({"_id":order["_id"]})
        evidence["SMTP"]={"result":"PASS" if delivered else "FAIL","recipient":"idsegwork@gmail.com","delivery_state":current.get("delivery_email_status"),"inbox_receipt":"NOT VERIFIED","other_tenant_content":"NOT VERIFIED — emitted MIME not captured"}
    finally:
        _restore(scope)
    client.close()
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    (EVIDENCE/"integrations.json").write_text(json.dumps(evidence,indent=2)+"\n")
    print(json.dumps(evidence))

asyncio.run(main())
