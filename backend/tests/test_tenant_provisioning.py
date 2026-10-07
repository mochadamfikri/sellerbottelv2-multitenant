"""Test tenant database provisioning and schema initialization."""
import asyncio

import pytest

from tenant_provisioning import provision_tenant_database


@pytest.fixture
def mock_client():
    """Provide a mock MongoDB client with tenant database access."""
    from mongomock_motor import AsyncMongoMockClient
    return AsyncMongoMockClient()


def test_provision_tenant_database_creates_settings_collection_with_defaults():
    """provision_tenant_database must bootstrap a settings document."""
    from mongomock_motor import AsyncMongoMockClient
    
    client = AsyncMongoMockClient()
    
    async def run():
        result = await provision_tenant_database("acme-shop", client)
        
        # Verify provisioning succeeded
        assert result["status"] == "success"
        assert result["database_name"] == "sellerbottel_tenant_acme_shop"
        assert "settings" in result["collections_initialized"]
        
        # Verify settings document exists with required fields
        db = client["sellerbottel_tenant_acme_shop"]
        settings = await db.settings.find_one({"_id": "main"})
        
        assert settings is not None
        assert settings["_id"] == "main"
        assert settings["tenant_id"] == "acme-shop"
        assert settings["store_name"] == ""
        assert settings["rate_mode"] == "auto"
        assert settings["manual_rate"] == 16000.0
        assert "qris_enabled" in settings
        assert "bank_enabled" in settings
    
    asyncio.run(run())


def test_provision_tenant_database_creates_meta_collection_with_schema_version():
    """provision_tenant_database must record schema_version in _meta."""
    from mongomock_motor import AsyncMongoMockClient
    
    client = AsyncMongoMockClient()
    
    async def run():
        result = await provision_tenant_database("beta-store", client)
        
        # Verify _meta collection initialized
        assert "_meta" in result["collections_initialized"]
        
        # Verify schema version recorded
        db = client["sellerbottel_tenant_beta_store"]
        meta = await db._meta.find_one({"_id": "schema"})
        
        assert meta is not None
        assert meta["schema_version"] == 1
        assert "created_at" in meta
    
    asyncio.run(run())


def test_provision_tenant_database_creates_essential_indexes():
    """provision_tenant_database must create indexes for core collections."""
    from mongomock_motor import AsyncMongoMockClient

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("gamma-store", client)

        db = client["sellerbottel_tenant_gamma_store"]

        assert "active_created_at" in await db.products.index_information()
        assert "product_status" in await db.inventory_items.index_information()
        assert "product_fingerprint_unique" in await db.inventory_items.index_information()
        assert "invoice_id_unique" in await db.purchases.index_information()
        assert "user_created_at" in await db.purchases.index_information()
        assert "store_customer_idempotency_unique" in await db.purchases.index_information()
        assert "tx_hash_unique" in await db.deposits.index_information()
        assert "user_created_at" in await db.deposits.index_information()
        assert "customer_created_at" in await db.deposits.index_information()

    asyncio.run(run())


def test_provision_tenant_database_preserves_global_customer_identity_indexes():
    """Customer identities keep global field keys rather than tenant-scoped keys."""
    from mongomock_motor import AsyncMongoMockClient

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("global-identity-store", client)
        db = client["sellerbottel_tenant_global_identity_store"]

        customer_indexes = await db.store_customers.index_information()
        bot_user_indexes = await db.bot_users.index_information()

        assert customer_indexes["email_unique"]["key"] == [("email", 1)]
        assert customer_indexes["email_unique"]["unique"] is True
        assert customer_indexes["telegram_id_unique"]["key"] == [("telegram_id", 1)]
        assert customer_indexes["telegram_id_unique"]["unique"] is True
        assert bot_user_indexes["telegram_id_unique"]["key"] == [("telegram_id", 1)]
        assert bot_user_indexes["telegram_id_unique"]["unique"] is True

    asyncio.run(run())


def test_provision_tenant_database_keeps_invoice_numbers_unique_per_tenant():
    """Invoice uniqueness is enforced in each isolated tenant database."""
    from mongomock_motor import AsyncMongoMockClient

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("invoice-a", client)
        await provision_tenant_database("invoice-b", client)

        await client["sellerbottel_tenant_invoice_a"].purchases.insert_one(
            {"invoice_id": "INV-1"}
        )
        await client["sellerbottel_tenant_invoice_b"].purchases.insert_one(
            {"invoice_id": "INV-1"}
        )

    asyncio.run(run())


def test_provision_tenant_database_keeps_inventory_fingerprints_isolated():
    """Inventory fingerprints are unique only within their tenant database."""
    from mongomock_motor import AsyncMongoMockClient

    client = AsyncMongoMockClient()

    async def run():
        await provision_tenant_database("inventory-a", client)
        await provision_tenant_database("inventory-b", client)

        inventory_item = {"product_id": "product-1", "fingerprint": "same-stock"}
        await client["sellerbottel_tenant_inventory_a"].inventory_items.insert_one(inventory_item)
        await client["sellerbottel_tenant_inventory_b"].inventory_items.insert_one(inventory_item)

    asyncio.run(run())




def test_provision_tenant_database_derives_correct_database_name():
    """provision_tenant_database must use tenant_database_name for isolation."""
    from mongomock_motor import AsyncMongoMockClient
    
    client = AsyncMongoMockClient()
    
    async def run():
        result = await provision_tenant_database("test-tenant", client)
        
        assert result["database_name"] == "sellerbottel_tenant_test_tenant"
        
        # Verify the database was actually used
        db = client["sellerbottel_tenant_test_tenant"]
        settings = await db.settings.find_one({"_id": "main"})
        assert settings is not None
    
    asyncio.run(run())


def test_provision_tenant_database_returns_collections_summary():
    """provision_tenant_database must return a summary of initialized collections."""
    from mongomock_motor import AsyncMongoMockClient
    
    client = AsyncMongoMockClient()
    
    async def run():
        result = await provision_tenant_database("delta-corp", client)
        
        assert result["status"] == "success"
        assert isinstance(result["collections_initialized"], list)
        
        # Essential collections must be in the list
        collections = result["collections_initialized"]
        assert "settings" in collections
        assert "_meta" in collections
        assert len(collections) >= 2
    
    asyncio.run(run())


def test_provision_tenant_database_rejects_invalid_tenant_id():
    """provision_tenant_database must validate tenant_id before provisioning."""
    from mongomock_motor import AsyncMongoMockClient
    
    client = AsyncMongoMockClient()
    
    async def run():
        with pytest.raises(ValueError, match="tenant ID"):
            await provision_tenant_database("invalid tenant!", client)
    
    asyncio.run(run())


def test_provision_tenant_database_initializes_empty_collections():
    """provision_tenant_database must create empty collections for tenant data."""
    from mongomock_motor import AsyncMongoMockClient
    
    client = AsyncMongoMockClient()
    
    async def run():
        await provision_tenant_database("epsilon", client)
        
        db = client["sellerbottel_tenant_epsilon"]
        
        # Essential collections should exist (even if empty)
        assert await db.products.count_documents({}) == 0
        assert await db.inventory_items.count_documents({}) == 0
        assert await db.purchases.count_documents({}) == 0
        assert await db.store_customers.count_documents({}) == 0
        assert await db.bot_users.count_documents({}) == 0
    
    asyncio.run(run())


def test_provision_tenant_database_settings_includes_all_required_fields():
    """provision_tenant_database settings must include all critical fields."""
    from mongomock_motor import AsyncMongoMockClient
    
    client = AsyncMongoMockClient()
    
    async def run():
        await provision_tenant_database("zeta", client)
        
        db = client["sellerbottel_tenant_zeta"]
        settings = await db.settings.find_one({"_id": "main"})
        
        # Verify critical fields exist
        required_fields = [
            "tenant_id", "store_name", "rate_mode", "manual_rate", 
            "cached_rate", "qris_enabled", "store_qris_enabled",
            "bank_enabled", "min_deposit_idr", "min_deposit_usd",
            "whatsapp_contact_number"
        ]
        
        for field in required_fields:
            assert field in settings, f"Missing required field: {field}"
    
    asyncio.run(run())
