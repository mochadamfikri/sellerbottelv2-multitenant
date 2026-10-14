"""Explicit local-development tenant migration; dry-run unless --apply.

Requires environment configuration with PYTHON_DOTENV_DISABLED=1. Never reads .env.
Historical orders and their snapshots are deliberately untouched.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    url = urlsplit(os.environ.get("MONGO_URL", ""))
    if os.environ.get("ENVIRONMENT") != "development" or os.environ.get("PYTHON_DOTENV_DISABLED") != "1" or url.hostname != "127.0.0.1" or url.port != 27019:
        raise SystemExit("Dedicated development environment required; configuration withheld")
    from dependencies import get_tenant_registry
    from db import client
    from commerce.migration import backfill_products
    tenant = await get_tenant_registry().get_tenant(args.tenant)
    if not tenant or tenant["status"] != "active":
        raise SystemExit("Active development tenant required")
    result = await backfill_products(client[tenant["database_name"]], tenant_id=str(tenant["_id"]), tenant_slug=tenant["slug"], apply=args.apply)
    print(json.dumps(result))
    client.close()

if __name__ == "__main__":
    asyncio.run(main())
