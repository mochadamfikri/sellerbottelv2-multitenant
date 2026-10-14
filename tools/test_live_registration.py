"""Exercise SMTP OTP registration using the explicitly authorized test email.

The disposable DB is read to automate entering the received OTP. No codes,
passwords, JWTs or verification tokens are written to evidence.
"""
import asyncio
from datetime import datetime
import json
from pathlib import Path
import secrets
from dotenv import dotenv_values
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
ROOT=Path(__file__).resolve().parents[1]
config=dotenv_values(ROOT/"backend/.env.live-e2e")
if not config.get("MONGO_URL", "").startswith("mongodb://127.0.0.1:27019/") or config.get("PLATFORM_DB_NAME")!="sellerbottel_live_e2e_dev":
    raise SystemExit("Unsafe E2E configuration")

async def main():
    mongo=AsyncIOMotorClient(config["MONGO_URL"])
    db=mongo[config["PLATFORM_DB_NAME"]]
    email="idsegwork@gmail.com"
    evidence={"recipient":email,"steps":[],"OTP_entry":"automated from dedicated E2E DB; inbox receipt not verified"}
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8002",timeout=45) as http:
        response=await http.post("/api/public/register/request-code",json={"email":email})
        evidence["steps"].append({"step":"SMTP request-code","status":response.status_code,"result":"PASS" if response.status_code==200 else "FAIL"})
        if response.status_code==200:
            record=await db.public_reg_otp.find_one({"email":email})
            response=await http.post("/api/public/register/verify-code",json={"email":email,"code":record["code"]})
            evidence["steps"].append({"step":"verify-code","status":response.status_code,"result":"PASS" if response.status_code==200 else "FAIL"})
            if response.status_code==200:
                response=await http.post("/api/public/register",json={"username":"e2e-auto-registration","store_name":"E2E Automatic Registration","email":email,"password":secrets.token_urlsafe(24),"whatsapp":"081234567890","verify_token":response.json()["verify_token"]})
                evidence["steps"].append({"step":"register provision","status":response.status_code,"result":"PASS" if response.status_code==201 else "FAIL"})
                if response.status_code==201:
                    tenant=await db.tenants.find_one({"slug":"e2e-auto-registration"})
                    evidence["tenant"]={"slug":tenant["slug"],"id":tenant["_id"],"database_name":tenant["database_name"],"status":tenant["status"],"bot_configured":False}
    mongo.close()
    (ROOT/"test_reports/live-dev-e2e-20261008/automatic-registration.json").write_text(json.dumps(evidence,indent=2)+"\n")
    print(json.dumps(evidence))

asyncio.run(main())
