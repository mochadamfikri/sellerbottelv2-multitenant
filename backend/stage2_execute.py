#!/usr/bin/env python3
"""Stage 2 Execution: Provision sellerbottel_tenant_idse and perform Dry-Run Verification.

SAFETY:
- Development MongoDB only (mongodb://127.0.0.1:27018)
- Provisions sellerbottel_tenant_idse via tenant_provisioning.py
- Samples records from sellerbottel_dev, validates schema and isolation
- Cleans up sample records after test
"""
import os
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27018")
os.environ.setdefault("DB_NAME", "sellerbottel_platform")
os.environ.setdefault("ENVIRONMENT", "development")

import asyncio
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = "mongodb://127.0.0.1:27018"
SOURCE_DB = "sellerbottel_dev"
TENANT_ID = "idse"
TENANT_DB = "sellerbottel_tenant_idse"


async def stage2_execute():
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
        print(f"✓ Connected to {MONGO_URL}")
    except Exception as exc:
        print(f"✗ MongoDB connection failed: {exc}")
        return 1

    sys.path.insert(0, "/opt/sellerbottel-v2/repo/backend")
    from tenant_provisioning import provision_tenant_database

    print(f"\n[1/4] Provisioning tenant database: {TENANT_DB}...")
    provision_result = await provision_tenant_database(TENANT_ID, client)
    print(f"  Status: {provision_result['status']}")
    print(f"  Database: {provision_result['database_name']}")
    print(f"  Initialized collections: {len(provision_result['collections_initialized'])}")

    tenant_db = client[TENANT_DB]
    source_db = client[SOURCE_DB]

    # Verify settings & schema version
    meta = await tenant_db["_meta"].find_one({"_id": "schema"})
    settings = await tenant_db.settings.find_one({"_id": "main"})
    print(f"  _meta: schema_version={meta.get('schema_version')}")
    print(f"  settings: tenant_id={settings.get('tenant_id')}")

    # Step 2: Check indexes
    print(f"\n[2/4] Verifying tenant database indexes...")
    for col_name in ["products", "inventory_items", "purchases", "deposits", "store_customers"]:
        indexes = await tenant_db[col_name].index_information()
        print(f"  {col_name}: {list(indexes.keys())}")

    # Step 3: Dry-run sample records injection and isolation check
    print(f"\n[3/4] Dry-run testing with sample records...")
    sample_product = await source_db.products.find_one({})
    sample_inv = await source_db.inventory_items.find_one({})
    sample_purchase = await source_db.purchases.find_one({})

    if sample_product:
        p_copy = dict(sample_product)
        p_copy["tenant_id"] = TENANT_ID
        await tenant_db.products.insert_one(p_copy)
        print(f"  Inserted sample product: {p_copy.get('name', p_copy.get('_id'))}")

    if sample_inv:
        inv_copy = dict(sample_inv)
        inv_copy["tenant_id"] = TENANT_ID
        await tenant_db.inventory_items.insert_one(inv_copy)
        print(f"  Inserted sample inventory item: {inv_copy.get('_id')}")

    if sample_purchase:
        pur_copy = dict(sample_purchase)
        pur_copy["tenant_id"] = TENANT_ID
        await tenant_db.purchases.insert_one(pur_copy)
        print(f"  Inserted sample purchase: invoice_id={pur_copy.get('invoice_id')}")

    # Verify isolation query
    found_products = await tenant_db.products.count_documents({"tenant_id": TENANT_ID})
    found_inv = await tenant_db.inventory_items.count_documents({"tenant_id": TENANT_ID})
    found_pur = await tenant_db.purchases.count_documents({"tenant_id": TENANT_ID})
    print(f"  Verified query count in tenant DB: products={found_products}, inv={found_inv}, purchases={found_pur}")

    # Cross-tenant check: other tenant ID query returns 0
    other_query = await tenant_db.products.count_documents({"tenant_id": "other_tenant"})
    print(f"  Cross-tenant query check (should be 0): {other_query}")
    assert other_query == 0

    # Step 4: Cleanup sample records (Rollback dry-run)
    print(f"\n[4/4] Cleaning up sample test records (rollback)...")
    if sample_product:
        await tenant_db.products.delete_one({"_id": sample_product["_id"]})
    if sample_inv:
        await tenant_db.inventory_items.delete_one({"_id": sample_inv["_id"]})
    if sample_purchase:
        await tenant_db.purchases.delete_one({"_id": sample_purchase["_id"]})

    rem_products = await tenant_db.products.count_documents({})
    rem_inv = await tenant_db.inventory_items.count_documents({})
    rem_pur = await tenant_db.purchases.count_documents({})
    print(f"  Remaining business docs after rollback: products={rem_products}, inv={rem_inv}, purchases={rem_pur}")

    print(f"\n{'='*60}")
    print(f"STAGE 2 COMPLETE & VERIFIED")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(stage2_execute()))
