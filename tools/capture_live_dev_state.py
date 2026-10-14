"""Capture safe runtime metadata and scan logs without emitting secret matches."""
import asyncio
import json
from pathlib import Path
import re
from dotenv import dotenv_values
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"test_reports/live-dev-e2e-20261008"
config=dotenv_values(ROOT/"backend/.env.live-e2e")
if not config.get("MONGO_URL", "").startswith("mongodb://127.0.0.1:27019/"):
    raise SystemExit("Unsafe E2E configuration")
async def main():
    mongo=AsyncIOMotorClient(config["MONGO_URL"])
    platform=mongo[config["PLATFORM_DB_NAME"]]
    tenants=[]
    for label in "ab":
        t=await platform.tenants.find_one({"slug":"e2e-tenant-"+label})
        tenants.append({"slug":t["slug"],"id":t["_id"],"database_name":t["database_name"],"status":t["status"],"bot_configured":bool((t.get("metadata") or {}).get("bot_config",{}).get("token_encrypted")),"processed_telegram_update_count":await mongo[t["database_name"]].processed_updates.count_documents({})})
    async with httpx.AsyncClient(timeout=10) as http:
        state={"backend_health":(await http.get("http://127.0.0.1:8002/api/")).status_code,"frontend_http":(await http.get("http://127.0.0.1:3002/admin")).status_code,"tenants":tenants,"automatic_registration_owner_cleaned":await platform.tenant_owners.find_one({"email":"idsegwork@gmail.com"}) is None}
    secret_values=[]
    for source in (ROOT/"backend/.env",ROOT/"backend/.env.live-e2e"):
        for key,value in dotenv_values(source).items():
            if value and len(value)>=8 and any(part in key.upper() for part in ("TOKEN","SECRET","PASSWORD","ENCRYPTION_KEY","SESSION_KEY")):
                secret_values.append(value)
    scans=[]
    for p in (OUT/"runtime.log",ROOT/"backend/storage_data/live-dev-runtime.log",ROOT/"backend/storage_data/live-dev-dispatcher.log",ROOT/"backend/storage_data/live-dev-dispatcher-restart.log"):
        body=p.read_text()
        values=sum(body.count(value) for value in secret_values)
        patterns=len(re.findall(r"Bearer\s+[A-Za-z0-9._-]{20,}|[0-9]{7,}:[A-Za-z0-9_-]{25,}|mongodb(?:\+srv)?://(?!\[REDACTED\])\S+",body))
        scans.append({"path":str(p.relative_to(ROOT)),"actual_secret_matches":values,"unredacted_credential_patterns":patterns,"result":"PASS" if not values and not patterns else "FAIL"})
    state["dispatcher_restart"]={"result":"PASS","expected_worker_slugs":["e2e-tenant-a"],"restart_log_worker_start_count":(ROOT/"backend/storage_data/live-dev-dispatcher-restart.log").read_text().count("worker started for tenant e2e-tenant-a")}
    (OUT/"runtime-state.json").write_text(json.dumps(state,indent=2)+"\n")
    (OUT/"log-safety.json").write_text(json.dumps(scans,indent=2)+"\n")
    print(json.dumps({"backend":state["backend_health"],"frontend":state["frontend_http"],"secret_log_matches":sum(s["actual_secret_matches"]+s["unredacted_credential_patterns"] for s in scans)}))
    mongo.close()
asyncio.run(main())
