"""Tests for async invoice counter repository - per-tenant atomic counters."""

import asyncio
from functools import wraps


class InMemoryCounters:
    def __init__(self):
        self.documents = {}

    async def update_one(self, query, update, *, upsert):
        key = (query["tenant_id"], query["counter_name"])
        if key not in self.documents and upsert:
            self.documents[key] = {
                "tenant_id": key[0],
                "counter_name": key[1],
                "value": update["$setOnInsert"]["value"],
            }

    async def find_one_and_update(self, query, update, *, upsert, return_document):
        key = (query["tenant_id"], query["counter_name"])
        if key not in self.documents and upsert:
            initial = update.get("$setOnInsert", {}).get("value", 0)
            self.documents[key] = {
                "tenant_id": key[0],
                "counter_name": key[1],
                "value": initial,
            }
        self.documents[key]["value"] += update.get("$inc", {}).get("value", 0)
        return self.documents[key].copy()


class InMemoryDatabase:
    def __init__(self):
        self.counters = InMemoryCounters()


class RecordingCounters(InMemoryCounters):
    async def find_one_and_update(self, query, update, *, upsert, return_document):
        self.last_query = query
        self.last_update = update
        self.last_upsert = upsert
        return await super().find_one_and_update(
            query, update, upsert=upsert, return_document=return_document
        )


class RecordingDatabase:
    def __init__(self):
        self.counters = RecordingCounters()


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


class TestInvoiceCounterInitialization:
    """Initialize tenant counters from legacy max values."""

    def test_repository_rejects_unscoped_or_invalid_tenant_id(self):
        """Counters must never be created outside a valid tenant scope."""
        from invoice_counter_repository import InvoiceCounterRepository

        repo = InvoiceCounterRepository(database=InMemoryDatabase())

        for tenant_id in ("", "tenant/db", None):
            try:
                asyncio.run(repo.initialize_counter(tenant_id, "invoice", 0))
            except ValueError:
                continue
            raise AssertionError(f"expected ValueError for {tenant_id!r}")

    @async_test
    async def test_initialize_counter_from_legacy_max(self):
        """Initialize IDSE counter to continue from legacy max (71 → next is 72)."""
        from invoice_counter_repository import InvoiceCounterRepository
        
        db = InMemoryDatabase()
        repo = InvoiceCounterRepository(database=db)
        
        await repo.initialize_counter(tenant_id="idse", counter_name="invoice", legacy_max=71)
        
        # Counter should be initialized to 71, so next increment returns 72
        next_value = await repo.get_next_counter(tenant_id="idse", counter_name="invoice")
        assert next_value == 72

    @async_test
    async def test_initialize_new_tenant_counter_from_zero(self):
        """New tenant starts from 0, first invoice is #1."""
        from invoice_counter_repository import InvoiceCounterRepository
        
        db = InMemoryDatabase()
        repo = InvoiceCounterRepository(database=db)
        
        await repo.initialize_counter(tenant_id="acme-shop", counter_name="invoice", legacy_max=0)
        
        next_value = await repo.get_next_counter(tenant_id="acme-shop", counter_name="invoice")
        assert next_value == 1

    @async_test
    async def test_initialize_counter_idempotent_does_not_regress_counter(self):
        """Re-initializing an active counter does not overwrite higher values."""
        from mongomock_motor import AsyncMongoMockClient
        from invoice_counter_repository import InvoiceCounterRepository

        client = AsyncMongoMockClient()
        db = client["test_database"]
        repo = InvoiceCounterRepository(database=db)

        # Initialize to 71
        await repo.initialize_counter(tenant_id="idse", counter_name="invoice", legacy_max=71)
        # Advance to 72
        assert await repo.get_next_counter(tenant_id="idse", counter_name="invoice") == 72

        # Re-initialize to 71 (e.g. rerun migration script)
        await repo.initialize_counter(tenant_id="idse", counter_name="invoice", legacy_max=71)

        # Next counter must be 73, NOT 72
        assert await repo.get_next_counter(tenant_id="idse", counter_name="invoice") == 73


class TestAtomicCounterIncrement:
    """Atomic increment operations for per-tenant counters."""

    @async_test
    async def test_get_next_counter_increments_atomically(self):
        """Each call returns sequential values."""
        from invoice_counter_repository import InvoiceCounterRepository
        
        db = InMemoryDatabase()
        repo = InvoiceCounterRepository(database=db)
        
        await repo.initialize_counter(tenant_id="test", counter_name="invoice", legacy_max=5)
        
        assert await repo.get_next_counter(tenant_id="test", counter_name="invoice") == 6
        assert await repo.get_next_counter(tenant_id="test", counter_name="invoice") == 7
        assert await repo.get_next_counter(tenant_id="test", counter_name="invoice") == 8

    @async_test
    async def test_counters_isolated_per_tenant(self):
        """Each tenant has independent counter sequences."""
        from invoice_counter_repository import InvoiceCounterRepository
        
        db = InMemoryDatabase()
        repo = InvoiceCounterRepository(database=db)
        
        await repo.initialize_counter(tenant_id="idse", counter_name="invoice", legacy_max=71)
        await repo.initialize_counter(tenant_id="acme", counter_name="invoice", legacy_max=0)
        
        # IDSE continues from 71
        assert await repo.get_next_counter(tenant_id="idse", counter_name="invoice") == 72
        assert await repo.get_next_counter(tenant_id="idse", counter_name="invoice") == 73
        
        # ACME starts fresh from 0
        assert await repo.get_next_counter(tenant_id="acme", counter_name="invoice") == 1
        assert await repo.get_next_counter(tenant_id="acme", counter_name="invoice") == 2
        
        # IDSE counter not affected
        assert await repo.get_next_counter(tenant_id="idse", counter_name="invoice") == 74

class TestMongomockIntegration:
    """Ensure compatibility with AsyncMongoMockClient (used in offline tests)."""

    @async_test
    async def test_repository_with_mongomock_database(self):
        from mongomock_motor import AsyncMongoMockClient
        from invoice_counter_repository import InvoiceCounterRepository

        client = AsyncMongoMockClient()
        db = client["test_database"]

        repo = InvoiceCounterRepository(database=db)

        # Initialize IDSE legacy max 71
        await repo.initialize_counter(tenant_id="idse", counter_name="invoice", legacy_max=71)

        # First increment returns 72
        next_val = await repo.get_next_counter(tenant_id="idse", counter_name="invoice")
        assert next_val == 72

        # Second increment returns 73
        next_val = await repo.get_next_counter(tenant_id="idse", counter_name="invoice")
        assert next_val == 73

        # New tenant starts from 0, first increment returns 1
        next_acme = await repo.get_next_counter(tenant_id="acme", counter_name="invoice")
        assert next_acme == 1
