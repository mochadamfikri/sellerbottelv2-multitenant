#!/usr/bin/env python3
"""Stage 1 Execution: IDSE Control Plane Setup

SAFETY:
- Development-only (mongodb://127.0.0.1:27018)
- Creates sellerbottel_platform database
- Copies admin from sellerbottel_dev
- Updates admin email to ipinujus600@gmail.com
- Creates IDSE tenant + platform_admin role + tenant_owner membership
"""
import asyncio
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

# Development MongoDB only
MONGO_URL = "mongodb://127.0.0.1:27018"
SOURCE_DB = "sellerbottel_dev"
PLATFORM_DB = "sellerbottel_platform"
OWNER_EMAIL = "ipinujus600@gmail.com"


async def stage1_setup():
    """Execute Stage 1: Platform control plane setup."""
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    
    try:
        # Verify connection
        await client.admin.command("ping")
        print(f"✓ Connected to {MONGO_URL}")
    except Exception as exc:
        print(f"✗ MongoDB connection failed: {exc}")
        return 1
    
    source_db = client[SOURCE_DB]
    platform_db = client[PLATFORM_DB]
    
    # Step 1: Check/copy admin from source
    print(f"\n[1/4] Checking admin in {SOURCE_DB}...")
    source_admin = await source_db.admins.find_one({"_id": "admin-1"})
    
    if not source_admin:
        print(f"✗ Admin 'admin-1' not found in {SOURCE_DB}")
        return 1
    
    print(f"  Found: {source_admin.get('email')} (role={source_admin.get('role')})")
    
    # Step 2: Copy admin to platform DB with updated email
    print(f"\n[2/4] Setting up admin in {PLATFORM_DB}...")
    existing_admin = await platform_db.admins.find_one({"_id": "admin-1"})
    
    if existing_admin:
        print(f"  Admin already exists: {existing_admin.get('email')}")
        # Update email if different
        if existing_admin.get("email") != OWNER_EMAIL:
            await platform_db.admins.update_one(
                {"_id": "admin-1"},
                {"$set": {"email": OWNER_EMAIL, "updated_at": datetime.now(timezone.utc)}}
            )
            print(f"  Updated email to {OWNER_EMAIL}")
    else:
        # Copy admin from source and update email
        admin_copy = dict(source_admin)
        admin_copy["email"] = OWNER_EMAIL
        admin_copy["updated_at"] = datetime.now(timezone.utc)
        await platform_db.admins.insert_one(admin_copy)
        print(f"  Created admin with email {OWNER_EMAIL}")
    
    # Step 3: Run control plane setup
    print(f"\n[3/4] Running setup_idse_control_plane()...")
    sys.path.insert(0, "/opt/sellerbottel-v2/repo/backend")
    from control_plane_setup import setup_idse_control_plane
    
    try:
        result = await setup_idse_control_plane(platform_db, "admin-1")
        print(f"  ✓ IDSE tenant created:")
        print(f"    - Tenant ID: {result['tenant']['_id']}")
        print(f"    - Slug: {result['tenant']['slug']}")
        print(f"    - Name: {result['tenant']['name']}")
        print(f"    - Plan: {result['tenant']['plan']}")
        print(f"    - Status: {result['tenant']['status']}")
        print(f"    - Database: {result['tenant']['database_name']}")
        print(f"  ✓ Admin upgraded:")
        print(f"    - Platform role: {result['admin'].get('platform_role')}")
        print(f"  ✓ Tenant membership created:")
        print(f"    - Membership ID: {result['membership']['_id']}")
        print(f"    - Role: {result['membership']['role']}")
    except Exception as exc:
        print(f"  ✗ Setup failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Step 4: Verify platform database state
    print(f"\n[4/4] Verifying platform database state...")
    tenant_count = await platform_db.tenants.count_documents({})
    membership_count = await platform_db.tenant_memberships.count_documents({})
    admin_count = await platform_db.admins.count_documents({})
    
    print(f"  Tenants: {tenant_count}")
    print(f"  Memberships: {membership_count}")
    print(f"  Admins: {admin_count}")
    
    # Verify IDSE tenant specifically
    idse_tenant = await platform_db.tenants.find_one({"slug": "idse"})
    if idse_tenant:
        print(f"\n✓ IDSE tenant verified:")
        print(f"  - ID: {idse_tenant['_id']}")
        print(f"  - Database: {idse_tenant['database_name']}")
        print(f"  - Status: {idse_tenant['status']}")
        print(f"  - Created: {idse_tenant['created_at']}")
    else:
        print(f"\n✗ IDSE tenant not found!")
        return 1
    
    print(f"\n{'='*60}")
    print(f"STAGE 1 COMPLETE")
    print(f"{'='*60}")
    print(f"Platform Database: {PLATFORM_DB}")
    print(f"Owner Email: {OWNER_EMAIL}")
    print(f"IDSE Tenant: {idse_tenant['_id']} (slug=idse)")
    print(f"Next: Stage 2 - Provision tenant database + dry-run migration")
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(stage1_setup())
    sys.exit(exit_code)
