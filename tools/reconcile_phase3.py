"""Dev-only reconciliation report/receipt projection repair. No external retries.

Explicit environment: MONGO_URL localhost:27019, DB_NAME/PLATFORM_DB_NAME the
dedicated acceptance database. Never loads .env or accepts arbitrary databases.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

async def run(args):
    from db import client, platform_db
    from bot_tenant_scope import BotTenantScope, use_bot_tenant
    from payments.router import reconciliation, reconcile_repair
    tenant = await platform_db().tenants.find_one({"slug": args.tenant, "status": "active"})
    if not tenant:
        raise SystemExit("Active dev tenant required")
    database = client[tenant["database_name"]]
    async with use_bot_tenant(BotTenantScope(tenant_id=tenant["_id"], slug=tenant["slug"], database_name=database.name, db_handle=database)):
        report = await reconcile_repair() if args.repair else await reconciliation()
    print(json.dumps(report, default=str, indent=2))
    client.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--repair", action="store_true", help="Repair trusted local receipts/projections; never resubmit external financial actions")
    args = parser.parse_args()
    address = urlparse(os.environ.get("MONGO_URL", ""))
    platform_name = os.environ.get("PLATFORM_DB_NAME", "")
    if address.scheme != "mongodb" or address.hostname not in {"127.0.0.1", "localhost"} or address.port != 27019 or not platform_name.startswith("sellerbottel_phase3_dev_") or os.environ.get("DB_NAME") != platform_name:
        raise SystemExit("Only explicit dedicated Phase 3 dev Mongo configuration is permitted")
    asyncio.run(run(args))
