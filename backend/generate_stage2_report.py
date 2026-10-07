#!/usr/bin/env python3
"""Generate Stage 2 dry-run verification report from current database state.

SAFETY:
- Read-only operations on development MongoDB (127.0.0.1:27018)
- No document migration or writes
- Reports current state of tenant provisioning
"""

import asyncio
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from stage2_report import generate_verification_report

MONGO_URL = "mongodb://127.0.0.1:27018"
SOURCE_DB = "sellerbottel_dev"
TENANT_DB = "sellerbottel_tenant_idse"
TENANT_ID = "idse"


async def gather_database_state():
    """Gather read-only state from source and tenant databases."""
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    
    try:
        await client.admin.command("ping")
        print(f"✓ Connected to {MONGO_URL}")
    except Exception as exc:
        print(f"✗ MongoDB connection failed: {exc}", file=sys.stderr)
        return None
    
    source_db = client[SOURCE_DB]
    tenant_db = client[TENANT_DB]
    
    # Gather source collection counts
    print(f"\n[1/4] Gathering source counts from {SOURCE_DB}...")
    source_collections = await source_db.list_collection_names()
    source_counts = {}
    
    for col_name in source_collections:
        count = await source_db[col_name].count_documents({})
        source_counts[col_name] = count
        if count > 0:
            print(f"  {col_name}: {count}")
    
    # Gather tenant database state
    print(f"\n[2/4] Gathering tenant database state from {TENANT_DB}...")
    tenant_collections = await tenant_db.list_collection_names()
    tenant_doc_counts = {}
    
    for col_name in tenant_collections:
        count = await tenant_db[col_name].count_documents({})
        tenant_doc_counts[col_name] = count
        print(f"  {col_name}: {count} documents")
    
    # Gather tenant indexes
    print(f"\n[3/4] Gathering tenant indexes...")
    tenant_indexes = {}
    
    for col_name in tenant_collections:
        indexes = await tenant_db[col_name].index_information()
        index_names = list(indexes.keys())
        tenant_indexes[col_name] = index_names
        print(f"  {col_name}: {index_names}")
    
    # Get MongoDB version
    server_info = await client.server_info()
    mongo_version = server_info.get("version", "unknown")
    
    client.close()
    
    return {
        "source_counts": source_counts,
        "tenant_collections": tenant_collections,
        "tenant_doc_counts": tenant_doc_counts,
        "tenant_indexes": tenant_indexes,
        "mongo_version": mongo_version,
    }


async def main():
    """Generate and display verification report."""
    state = await gather_database_state()
    
    if state is None:
        return 1
    
    print(f"\n[4/4] Generating verification report...")
    
    report = generate_verification_report(
        source_counts=state["source_counts"],
        tenant_id=TENANT_ID,
        tenant_db_name=TENANT_DB,
        tenant_collections=state["tenant_collections"],
        tenant_indexes=state["tenant_indexes"],
        clock=datetime.now(timezone.utc),
        mongo_version=state["mongo_version"],
    )
    
    # Display summary
    print(f"\n{'='*70}")
    print("STAGE 2 DRY-RUN VERIFICATION REPORT")
    print(f"{'='*70}")
    print(f"Generated: {report['generated_at']}")
    print(f"MongoDB Version: {report['mongo_version']}")
    print(f"Source Database: {report['source_database']}")
    print(f"Tenant Database: {report['tenant_database']}")
    print(f"Tenant ID: {report['tenant_id']}")
    print(f"\nSource Collections: {len(report['source_counts'])}")
    print(f"Source Total Documents: {sum(report['source_counts'].values())}")
    print(f"\nTenant Collections Initialized: {report['tenant_collections_initialized']}")
    print(f"Essential Collections Present: {report['essential_collections_present']}")
    
    if report['missing_collections']:
        print(f"Missing Collections: {report['missing_collections']}")
    
    print(f"\nRead-Only: {report['read_only']}")
    print(f"Documents Migrated: {report['documents_migrated']}")
    print(f"Status: {report['status']}")
    
    print(f"\n{'='*70}")
    print("KEY COLLECTIONS")
    print(f"{'='*70}")
    
    key_collections = [
        "products", "inventory_items", "purchases", "deposits",
        "store_customers", "bot_users", "admins"
    ]
    
    for col in key_collections:
        source_count = report['source_counts'].get(col, 0)
        tenant_count = state['tenant_doc_counts'].get(col, 0)
        print(f"{col:30} Source: {source_count:5}  Tenant: {tenant_count:5}")
    
    print(f"\n{'='*70}")
    print("TENANT INDEXES")
    print(f"{'='*70}")
    
    for col in sorted(report['tenant_indexes'].keys()):
        indexes = report['tenant_indexes'][col]
        print(f"\n{col}:")
        for idx in indexes:
            print(f"  - {idx}")
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
