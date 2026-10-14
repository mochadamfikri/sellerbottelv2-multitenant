"""Remove only the extra disposable registration created by this audit.

Preserves Tenant A/B and releases the authorized recipient for future signup.
Refuses cleanup if IDs differ or application data has appeared.
"""
import asyncio
import json
from pathlib import Path
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
ROOT=Path(__file__).resolve().parents[1]
evidence_path=ROOT/"test_reports/live-dev-e2e-20261008/automatic-registration.json"
evidence=json.loads(evidence_path.read_text())
tenant=evidence["tenant"]
config=dotenv_values(ROOT/"backend/.env.live-e2e")
if not config.get("MONGO_URL", "").startswith("mongodb://127.0.0.1:27019/") or tenant["slug"]!="e2e-auto-registration" or tenant["database_name"]!="sellerbottel_tenant_e2e_auto_registration":
    raise SystemExit("Unsafe disposable cleanup request")
async def main():
    mongo=AsyncIOMotorClient(config["MONGO_URL"])
    platform=mongo[config["PLATFORM_DB_NAME"]]
    record=await platform.tenants.find_one({"_id":tenant["id"],"slug":tenant["slug"]})
    if not record:
        raise SystemExit("Disposable tenant no longer matches; no mutation")
    database=mongo[tenant["database_name"]]
    for name in await database.list_collection_names():
        if name not in {"settings","_meta"} and await database[name].count_documents({}):
            raise SystemExit("Application data exists; cleanup refused")
    await platform.tenant_owners.delete_one({"tenant_id":tenant["id"],"email":"idsegwork@gmail.com"})
    await platform.domains.delete_many({"tenant_id":tenant["id"]})
    await platform.tenants.delete_one({"_id":tenant["id"],"slug":tenant["slug"]})
    await mongo.drop_database(tenant["database_name"])
    evidence["cleanup"]={"result":"PASS","recipient_available_for_future_registration":await platform.tenant_owners.find_one({"email":"idsegwork@gmail.com"}) is None,"tenant_A_B_preserved":await platform.tenants.count_documents({"slug":{"$in":["e2e-tenant-a","e2e-tenant-b"]}})==2}
    evidence_path.write_text(json.dumps(evidence,indent=2)+"\n")
    print(json.dumps(evidence["cleanup"]))
    mongo.close()
asyncio.run(main())
