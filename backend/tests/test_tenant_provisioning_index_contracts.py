"""Test tenant provisioning index contracts enforce strict tenant isolation.

Per OWNER_DECISIONS.md:
- Inventory isolation is STRICT (tenant_id must be first field in tenant-owned indexes)
- Customer identity is GLOBAL (no tenant_id in email/telegram_id indexes)
"""
import asyncio

import pytest


def test_products_index_includes_tenant_id_for_isolation():
    """Products active_created_at index must include tenant_id as first field."""
    from mongomock_motor import AsyncMongoMockClient
    from tenant_provisioning import provision_tenant_database

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("test-tenant", client)
        db = client["sellerbottel_tenant_test_tenant"]

        indexes = await db.products.index_information()
        active_created_at = indexes["active_created_at"]

        # Index must have tenant_id as first field for strict isolation
        assert active_created_at["key"][0] == ("tenant_id", 1), (
            "products index must have tenant_id as first field for tenant isolation"
        )
        assert active_created_at["key"][1] == ("active", 1)
        assert active_created_at["key"][2] == ("created_at", -1)

    asyncio.run(run())


def test_inventory_items_product_status_index_includes_tenant_id():
    """Inventory product_status index must include tenant_id for strict isolation."""
    from mongomock_motor import AsyncMongoMockClient
    from tenant_provisioning import provision_tenant_database

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("test-tenant", client)
        db = client["sellerbottel_tenant_test_tenant"]

        indexes = await db.inventory_items.index_information()
        product_status = indexes["product_status"]

        # Index must have tenant_id as first field per owner decision (strict isolation)
        assert product_status["key"][0] == ("tenant_id", 1), (
            "inventory_items product_status index must have tenant_id as first field"
        )
        assert product_status["key"][1] == ("product_id", 1)
        assert product_status["key"][2] == ("status", 1)

    asyncio.run(run())


def test_inventory_items_unique_fingerprint_index_includes_tenant_id():
    """Inventory fingerprint uniqueness must be scoped to tenant per owner decision.
    
    OWNER_DECISIONS.md lines 65-78: Strict isolation - inventory items belong to single tenant.
    Same fingerprint can exist in different tenant databases.
    """
    from mongomock_motor import AsyncMongoMockClient
    from tenant_provisioning import provision_tenant_database

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("test-tenant", client)
        db = client["sellerbottel_tenant_test_tenant"]

        indexes = await db.inventory_items.index_information()
        fingerprint_unique = indexes["product_fingerprint_unique"]

        # Index must have tenant_id as first field for per-tenant uniqueness
        assert fingerprint_unique["key"][0] == ("tenant_id", 1), (
            "inventory_items unique fingerprint must be scoped by tenant_id per owner decision"
        )
        assert fingerprint_unique["key"][1] == ("product_id", 1)
        assert fingerprint_unique["key"][2] == ("fingerprint", 1)
        assert fingerprint_unique["unique"] is True

    asyncio.run(run())


def test_purchases_index_includes_tenant_id_for_isolation():
    """Purchases user_created_at index must include tenant_id for query isolation."""
    from mongomock_motor import AsyncMongoMockClient
    from tenant_provisioning import provision_tenant_database

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("test-tenant", client)
        db = client["sellerbottel_tenant_test_tenant"]

        indexes = await db.purchases.index_information()
        user_created_at = indexes["user_created_at"]

        # Index must have tenant_id as first field for efficient tenant-scoped queries
        assert user_created_at["key"][0] == ("tenant_id", 1), (
            "purchases user_created_at index must have tenant_id as first field"
        )
        assert user_created_at["key"][1] == ("user_tid", 1)
        assert user_created_at["key"][2] == ("created_at", -1)

    asyncio.run(run())


def test_deposits_indexes_include_tenant_id_for_isolation():
    """Deposits indexes must include tenant_id for query isolation."""
    from mongomock_motor import AsyncMongoMockClient
    from tenant_provisioning import provision_tenant_database

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("test-tenant", client)
        db = client["sellerbottel_tenant_test_tenant"]

        indexes = await db.deposits.index_information()
        
        # user_created_at index
        user_created_at = indexes["user_created_at"]
        assert user_created_at["key"][0] == ("tenant_id", 1), (
            "deposits user_created_at index must have tenant_id as first field"
        )
        assert user_created_at["key"][1] == ("user_tid", 1)
        assert user_created_at["key"][2] == ("created_at", -1)

        # customer_created_at index
        customer_created_at = indexes["customer_created_at"]
        assert customer_created_at["key"][0] == ("tenant_id", 1), (
            "deposits customer_created_at index must have tenant_id as first field"
        )
        assert customer_created_at["key"][1] == ("customer_id", 1)
        assert customer_created_at["key"][2] == ("created_at", -1)

    asyncio.run(run())


def test_customer_identity_indexes_remain_global():
    """Customer identity indexes must NOT include tenant_id per owner decision.
    
    OWNER_DECISIONS.md lines 8-28: Email and telegram_id are globally unique.
    Customers can have memberships in multiple tenants.
    """
    from mongomock_motor import AsyncMongoMockClient
    from tenant_provisioning import provision_tenant_database

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("test-tenant", client)
        db = client["sellerbottel_tenant_test_tenant"]

        # Verify store_customers indexes are global (no tenant_id)
        customer_indexes = await db.store_customers.index_information()
        email_unique = customer_indexes["email_unique"]
        telegram_unique = customer_indexes["telegram_id_unique"]

        assert email_unique["key"] == [("email", 1)], (
            "email index must be global (no tenant_id) per owner decision"
        )
        assert email_unique["unique"] is True

        assert telegram_unique["key"] == [("telegram_id", 1)], (
            "telegram_id index must be global (no tenant_id) per owner decision"
        )
        assert telegram_unique["unique"] is True

        # Verify bot_users telegram_id is global
        bot_user_indexes = await db.bot_users.index_information()
        bot_telegram = bot_user_indexes["telegram_id_unique"]

        assert bot_telegram["key"] == [("telegram_id", 1)], (
            "bot_users telegram_id must be global (no tenant_id) per owner decision"
        )
        assert bot_telegram["unique"] is True

    asyncio.run(run())


def test_purchase_idempotency_index_includes_tenant_id():
    """Purchase idempotency must be unique within each tenant-owned purchase stream."""
    from mongomock_motor import AsyncMongoMockClient
    from tenant_provisioning import provision_tenant_database

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("test-tenant", client)
        db = client["sellerbottel_tenant_test_tenant"]

        index = (await db.purchases.index_information())["store_customer_idempotency_unique"]

        assert index["key"] == [
            ("tenant_id", 1),
            ("customer_id", 1),
            ("idempotency_key", 1),
        ]
        assert index["unique"] is True

    asyncio.run(run())


def test_invoice_id_index_remains_global():
    """Invoice ID uniqueness must remain global per owner decision.
    
    OWNER_DECISIONS.md lines 32-53: Invoice IDs are globally unique.
    Per-tenant counters, but uniqueness enforced globally for backward compatibility.
    """
    from mongomock_motor import AsyncMongoMockClient
    from tenant_provisioning import provision_tenant_database

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("test-tenant", client)
        db = client["sellerbottel_tenant_test_tenant"]

        indexes = await db.purchases.index_information()
        invoice_unique = indexes["invoice_id_unique"]

        # Invoice uniqueness is global (no tenant_id prefix)
        assert invoice_unique["key"] == [("invoice_id", 1)], (
            "invoice_id uniqueness must be global per owner decision"
        )
        assert invoice_unique["unique"] is True
        assert invoice_unique["sparse"] is True

    asyncio.run(run())


def test_meta_collection_uses_bracket_notation():
    """_meta collection access must use bracket notation for reserved names."""
    from unittest.mock import MagicMock
    from tenant_provisioning import provision_tenant_database

    class MockDatabase:
        def __init__(self):
            self.bracket_accessed = []
            self.attribute_accessed = []
            self.settings = MagicMock()
            self.settings.update_one = MagicMock(side_effect=self._mock_async)
            self.products = MagicMock()
            self.products.create_index = MagicMock(side_effect=self._mock_async)
            self.inventory_items = MagicMock()
            self.inventory_items.create_index = MagicMock(side_effect=self._mock_async)
            self.purchases = MagicMock()
            self.purchases.create_index = MagicMock(side_effect=self._mock_async)
            self.deposits = MagicMock()
            self.deposits.create_index = MagicMock(side_effect=self._mock_async)
            self.store_customers = MagicMock()
            self.store_customers.create_index = MagicMock(side_effect=self._mock_async)
            self.bot_users = MagicMock()
            self.bot_users.create_index = MagicMock(side_effect=self._mock_async)
            self.meta_col = MagicMock()
            self.meta_col.update_one = MagicMock(side_effect=self._mock_async)

        async def _mock_async(self, *args, **kwargs):
            return None

        def __getitem__(self, item):
            self.bracket_accessed.append(item)
            if item == "_meta":
                return self.meta_col
            return MagicMock()

        def __getattr__(self, item):
            self.attribute_accessed.append(item)
            return MagicMock()

    class MockClient:
        def __init__(self, db):
            self.db = db
        def __getitem__(self, item):
            return self.db

    mock_db = MockDatabase()
    mock_client = MockClient(mock_db)

    async def run():
        await provision_tenant_database("bracket-test", mock_client)
        assert "_meta" in mock_db.bracket_accessed, "_meta must be accessed via database['_meta'] bracket notation"
        assert "_meta" not in mock_db.attribute_accessed, "_meta must not be accessed as attribute database._meta"

    asyncio.run(run())
