#!/usr/bin/env python3
"""Create immutable legacy-web reset markers from migration provenance.

Run only during the authorized cutover migration. It reads account bindings
and writes tenant-side marker documents; it never mutates customer records.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from legacy_web_reset import mark_legacy_web_customer_bindings


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--migration-db", required=True)
    parser.add_argument("--mongo-url", default=os.environ.get("MONGO_URL", ""))
    args = parser.parse_args()
    if not args.mongo_url:
        raise SystemExit("MONGO_URL or --mongo-url is required")
    client = AsyncIOMotorClient(args.mongo_url)
    result = await mark_legacy_web_customer_bindings(client, args.migration_db)
    if result["bindings"] != 5:
        raise SystemExit(f"Expected exactly 5 legacy web bindings, found {result['bindings']}")
    print(f"legacy_web_reset_markers: bindings={result['bindings']} created={result['created']} existing={result['existing']}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
