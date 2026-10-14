"""Attach the explicitly confirmed development bot to disposable Tenant A only."""
import asyncio
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from dotenv import dotenv_values
source=dotenv_values(ROOT/"backend/.env")
config=dotenv_values(ROOT/"backend/.env.live-e2e")
if config.get("ENVIRONMENT")!="development" or not config.get("MONGO_URL", "").startswith("mongodb://127.0.0.1:27019/"):
    raise SystemExit("Unsafe E2E configuration")
os.environ.clear(); os.environ.update(config)
import httpx
from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    token=source.get("TELEGRAM_TOKEN","")
    async with httpx.AsyncClient(timeout=20) as http:
        data=(await http.get("https://api.telegram.org/bot"+token+"/getMe")).json()
        if not data.get("ok"):
            raise SystemExit("Development token validation failed; no mutation")
        webhook=(await http.get("https://api.telegram.org/bot"+token+"/getWebhookInfo")).json()
        if webhook.get("result",{}).get("url"):
            raise SystemExit("Existing webhook present; no mutation")
        pending=(await http.post("https://api.telegram.org/bot"+token+"/getUpdates",json={"timeout":0})).json()
        if not pending.get("ok"):
            raise SystemExit("Development polling unavailable; no mutation")
    mongo=AsyncIOMotorClient(config["MONGO_URL"])
    registry=mongo[config["PLATFORM_DB_NAME"]].tenants
    bot={"token_encrypted":Fernet(config["INVENTORY_ENCRYPTION_KEY"].encode()).encrypt(token.encode()).decode(),"brand_name":"E2E Store A","reseller_enabled":False,"admin_ids":[]}
    changed=await registry.update_one({"slug":"e2e-tenant-a","status":"active"},{"$set":{"metadata.bot_config":bot}})
    if changed.matched_count != 1:
        raise SystemExit("Disposable Tenant A missing")
    mongo.close()
    evidence={"result":"PASS","tenant_slug":"e2e-tenant-a","database_name":"sellerbottel_tenant_e2e_tenant_a","bot_id":data["result"]["id"],"webhook_changed":False,"polling_available":True,"bot2_enabled":False}
    (ROOT/"test_reports/live-dev-e2e-20261008/bot-configuration.json").write_text(json.dumps(evidence,indent=2)+"\n")
    print(json.dumps(evidence))

asyncio.run(main())
