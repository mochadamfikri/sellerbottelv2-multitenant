#!/usr/bin/env python3
"""Verify Development MongoDB :27018 state after Phase 3 integration."""
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import json

async def verify():
    client = AsyncIOMotorClient("mongodb://127.0.0.1:27018", serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")

        # Platform control plane
        platform_db = client["sellerbottel_platform"]
        tenant_count = await platform_db.tenants.count_documents({})
        membership_count = await platform_db.tenant_memberships.count_documents({})
        idse_tenant = await platform_db.tenants.find_one({"slug": "idse"})

        # IDSE tenant database
        idse_db = client["sellerbottel_tenant_idse"]
        collections = await idse_db.list_collection_names()
        products_count = await idse_db.products.count_documents({})
        inventory_count = await idse_db.inventory_items.count_documents({})
        purchases_count = await idse_db.purchases.count_documents({})

        # Source legacy (untouched)
        source_db = client["sellerbottel_dev"]
        source_products = await source_db.products.count_documents({})
        source_inventory = await source_db.inventory_items.count_documents({})
        source_purchases = await source_db.purchases.count_documents({})
        source_deposits = await source_db.deposits.count_documents({})

        return {
            "platform": {
                "tenants": tenant_count,
                "memberships": membership_count,
                "idse_tenant_id": str(idse_tenant["_id"]) if idse_tenant else None,
                "idse_status": idse_tenant["status"] if idse_tenant else None
            },
            "idse_tenant_db": {
                "collections_count": len(collections),
                "collections": sorted(collections),
                "products": products_count,
                "inventory_items": inventory_count,
                "purchases": purchases_count
            },
            "source_legacy": {
                "products": source_products,
                "inventory_items": source_inventory,
                "purchases": source_purchases,
                "deposits": source_deposits
            }
        }
    finally:
        client.close()

if __name__ == "__main__":
    print(json.dumps(asyncio.run(verify()), indent=2))
