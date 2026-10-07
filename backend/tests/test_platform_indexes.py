"""Test platform database index creation for tenants and tenant_memberships.

Blocker 1 from STAGE_2_PHASE_3_READINESS.md:
- tenants collection needs unique index on 'slug'
- tenant_memberships collection needs compound index on (tenant_id, user_id) unique
"""
import asyncio

import pytest


def test_ensure_platform_indexes_creates_tenant_slug_unique_index():
    """tenants collection must have unique index on slug field."""
    from mongomock_motor import AsyncMongoMockClient
    from platform_indexes import ensure_platform_indexes

    client = AsyncMongoMockClient()

    async def run():
        db = client["sellerbottel_platform"]
        await ensure_platform_indexes(db)

        indexes = await db.tenants.index_information()
        assert "tenant_slug_unique" in indexes

        slug_index = indexes["tenant_slug_unique"]
        assert slug_index["key"] == [("slug", 1)]
        assert slug_index["unique"] is True

    asyncio.run(run())


def test_ensure_platform_indexes_creates_tenant_database_name_unique_index():
    """tenants collection must have unique index on database_name field."""
    from mongomock_motor import AsyncMongoMockClient
    from platform_indexes import ensure_platform_indexes

    client = AsyncMongoMockClient()

    async def run():
        db = client["sellerbottel_platform"]
        await ensure_platform_indexes(db)

        indexes = await db.tenants.index_information()
        assert "tenant_database_name_unique" in indexes

        db_name_index = indexes["tenant_database_name_unique"]
        assert db_name_index["key"] == [("database_name", 1)]
        assert db_name_index["unique"] is True

    asyncio.run(run())


def test_ensure_platform_indexes_creates_tenant_status_created_at_index():
    """tenants collection must have index on (status, created_at) for queries."""
    from mongomock_motor import AsyncMongoMockClient
    from platform_indexes import ensure_platform_indexes

    client = AsyncMongoMockClient()

    async def run():
        db = client["sellerbottel_platform"]
        await ensure_platform_indexes(db)

        indexes = await db.tenants.index_information()

        # Find the status_created_at index (mongomock generates name)
        found = False
        for index_name, index_spec in indexes.items():
            if index_spec["key"] == [("status", 1), ("created_at", -1)]:
                found = True
                break

        assert found, "Missing (status, created_at) index on tenants collection"

    asyncio.run(run())


def test_ensure_platform_indexes_creates_membership_tenant_user_unique_index():
    """tenant_memberships must have unique compound index on (tenant_id, user_id)."""
    from mongomock_motor import AsyncMongoMockClient
    from platform_indexes import ensure_platform_indexes

    client = AsyncMongoMockClient()

    async def run():
        db = client["sellerbottel_platform"]
        await ensure_platform_indexes(db)

        indexes = await db.tenant_memberships.index_information()
        assert "tenant_user_unique" in indexes

        membership_index = indexes["tenant_user_unique"]
        assert membership_index["key"] == [("tenant_id", 1), ("user_id", 1)]
        assert membership_index["unique"] is True

    asyncio.run(run())


def test_ensure_platform_indexes_creates_membership_tenant_created_at_index():
    """tenant_memberships must have index on (tenant_id, created_at) for queries."""
    from mongomock_motor import AsyncMongoMockClient
    from platform_indexes import ensure_platform_indexes

    client = AsyncMongoMockClient()

    async def run():
        db = client["sellerbottel_platform"]
        await ensure_platform_indexes(db)

        indexes = await db.tenant_memberships.index_information()

        # Find the tenant_created_at index
        found = False
        for index_name, index_spec in indexes.items():
            if index_spec["key"] == [("tenant_id", 1), ("created_at", 1)]:
                found = True
                break

        assert found, "Missing (tenant_id, created_at) index on tenant_memberships"

    asyncio.run(run())


def test_ensure_platform_indexes_creates_membership_user_id_index():
    """tenant_memberships must have index on user_id for reverse lookups."""
    from mongomock_motor import AsyncMongoMockClient
    from platform_indexes import ensure_platform_indexes

    client = AsyncMongoMockClient()

    async def run():
        db = client["sellerbottel_platform"]
        await ensure_platform_indexes(db)

        indexes = await db.tenant_memberships.index_information()

        # Find the user_id index
        found = False
        for index_name, index_spec in indexes.items():
            if index_spec["key"] == [("user_id", 1)]:
                # Exclude the _id_ index
                if index_name != "_id_":
                    found = True
                    break

        assert found, "Missing user_id index on tenant_memberships"

    asyncio.run(run())


def test_ensure_platform_indexes_is_idempotent():
    """ensure_platform_indexes must be safe to call multiple times."""
    from mongomock_motor import AsyncMongoMockClient
    from platform_indexes import ensure_platform_indexes

    client = AsyncMongoMockClient()

    async def run():
        db = client["sellerbottel_platform"]

        # Call twice to verify idempotency
        await ensure_platform_indexes(db)
        await ensure_platform_indexes(db)

        # Verify indexes still correct after second call
        tenant_indexes = await db.tenants.index_information()
        membership_indexes = await db.tenant_memberships.index_information()

        assert "tenant_slug_unique" in tenant_indexes
        assert "tenant_database_name_unique" in tenant_indexes
        assert "tenant_user_unique" in membership_indexes

    asyncio.run(run())


def test_ensure_platform_indexes_prevents_duplicate_tenant_slugs():
    """Unique slug index must prevent duplicate tenant slugs."""
    from mongomock_motor import AsyncMongoMockClient
    from platform_indexes import ensure_platform_indexes

    client = AsyncMongoMockClient()

    async def run():
        db = client["sellerbottel_platform"]
        await ensure_platform_indexes(db)

        # Insert tenant with slug 'acme'
        await db.tenants.insert_one({"_id": "1", "slug": "acme", "name": "Acme Corp"})

        # Attempt to insert another tenant with same slug should fail
        with pytest.raises(Exception):  # DuplicateKeyError or similar
            await db.tenants.insert_one({"_id": "2", "slug": "acme", "name": "Acme 2"})

    asyncio.run(run())


def test_ensure_platform_indexes_prevents_duplicate_memberships():
    """Unique compound index must prevent duplicate (tenant_id, user_id) pairs."""
    from mongomock_motor import AsyncMongoMockClient
    from platform_indexes import ensure_platform_indexes

    client = AsyncMongoMockClient()

    async def run():
        db = client["sellerbottel_platform"]
        await ensure_platform_indexes(db)

        # Insert membership for tenant1, user1
        await db.tenant_memberships.insert_one({
            "_id": "1",
            "tenant_id": "tenant1",
            "user_id": "user1",
            "role": "tenant_owner"
        })

        # Attempt to insert duplicate membership should fail
        with pytest.raises(Exception):  # DuplicateKeyError or similar
            await db.tenant_memberships.insert_one({
                "_id": "2",
                "tenant_id": "tenant1",
                "user_id": "user1",
                "role": "tenant_admin"
            })

    asyncio.run(run())
