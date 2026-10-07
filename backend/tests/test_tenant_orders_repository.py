"""Tests for tenant-scoped orders repository with idempotency support."""
import asyncio
from functools import wraps
from types import SimpleNamespace
import pytest

from tenant_orders_repository import (
    TenantOrdersRepository,
    TenantOrdersScopeError,
)


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def create_mock_tenant_db():
    """In-memory mock for tenant database."""
    class MockCollection:
        def __init__(self):
            self.documents = []

        async def find_one(self, query):
            for doc in self.documents:
                match = True
                for k, v in query.items():
                    if doc.get(k) != v:
                        match = False
                        break
                if match:
                    return dict(doc)
            return None

        async def insert_one(self, document):
            if "customer_id" in document and document.get("idempotency_key"):
                for doc in self.documents:
                    if (doc.get("customer_id") == document["customer_id"] and
                            doc.get("idempotency_key") == document["idempotency_key"]):
                        raise Exception("E11000 duplicate key error collection: purchases index: store_customer_idempotency_unique")
            self.documents.append(dict(document))
            return type("Result", (), {"inserted_id": document.get("_id")})()

    class MockDatabase:
        def __init__(self):
            self.purchases = MockCollection()

    return MockDatabase()


def test_repository_initialization_with_injected_context():
    """Test repository initializes with a tenant context object."""
    mock_db = create_mock_tenant_db()
    context = SimpleNamespace(tenant_id="tenant-alpha", database=mock_db)
    repo = TenantOrdersRepository(context)

    assert repo.tenant_id == "tenant-alpha"
    assert repo.database is mock_db


def test_repository_initialization_with_slug_and_db():
    """Test repository initializes with explicit tenant slug and database."""
    mock_db = create_mock_tenant_db()
    repo = TenantOrdersRepository("tenant-beta", mock_db)

    assert repo.tenant_id == "tenant-beta"
    assert repo.database is mock_db


def test_repository_rejects_missing_or_invalid_inputs():
    """Test repository initialization validates tenant and database."""
    mock_db = create_mock_tenant_db()
    with pytest.raises(ValueError):
        TenantOrdersRepository("", mock_db)

    with pytest.raises(ValueError):
        TenantOrdersRepository("tenant-123", None)

    with pytest.raises(ValueError):
        TenantOrdersRepository(12345, mock_db)


@async_test
async def test_create_order_generates_tenant_scoped_order():
    """Test creating an order with customer_id, invoice reference, and idempotency key."""
    mock_db = create_mock_tenant_db()
    repo = TenantOrdersRepository("tenant-123", mock_db)

    order = await repo.create_order(
        customer_id="cust-456",
        invoice_id="INV-2026-001",
        idempotency_key="idemp-key-1",
        order_data={"total": 50000, "currency": "IDR", "items": [{"product_id": "p1", "qty": 1}]}
    )

    assert order["tenant_id"] == "tenant-123"
    assert order["customer_id"] == "cust-456"
    assert order["invoice_id"] == "INV-2026-001"
    assert order["idempotency_key"] == "idemp-key-1"
    assert order["total"] == 50000
    assert "_id" in order
    assert "created_at" in order


@async_test
async def test_duplicate_customer_and_idempotency_returns_original():
    """Test that retrying with identical customer_id + idempotency_key returns original order."""
    mock_db = create_mock_tenant_db()
    repo = TenantOrdersRepository("tenant-123", mock_db)

    first_order = await repo.create_order(
        customer_id="cust-456",
        invoice_id="INV-2026-001",
        idempotency_key="idemp-key-1",
        order_data={"total": 50000}
    )

    duplicate_order = await repo.create_order(
        customer_id="cust-456",
        invoice_id="INV-DIFFERENT",
        idempotency_key="idemp-key-1",
        order_data={"total": 99999}
    )

    assert duplicate_order["_id"] == first_order["_id"]
    assert duplicate_order["invoice_id"] == "INV-2026-001"
    assert duplicate_order["total"] == 50000


@async_test
async def test_different_idempotency_keys_create_distinct_orders():
    """Test that distinct idempotency keys create different orders."""
    mock_db = create_mock_tenant_db()
    repo = TenantOrdersRepository("tenant-123", mock_db)

    order1 = await repo.create_order(
        customer_id="cust-456",
        invoice_id="INV-001",
        idempotency_key="key-alpha",
        order_data={"total": 1000}
    )
    order2 = await repo.create_order(
        customer_id="cust-456",
        invoice_id="INV-002",
        idempotency_key="key-beta",
        order_data={"total": 2000}
    )

    assert order1["_id"] != order2["_id"]
    assert order1["invoice_id"] == "INV-001"
    assert order2["invoice_id"] == "INV-002"


@async_test
async def test_different_customers_with_same_idempotency_key_are_distinct():
    """Test that same idempotency key across different customers creates distinct orders."""
    mock_db = create_mock_tenant_db()
    repo = TenantOrdersRepository("tenant-123", mock_db)

    order1 = await repo.create_order(
        customer_id="cust-1",
        invoice_id="INV-001",
        idempotency_key="shared-key",
        order_data={"total": 1000}
    )
    order2 = await repo.create_order(
        customer_id="cust-2",
        invoice_id="INV-002",
        idempotency_key="shared-key",
        order_data={"total": 2000}
    )

    assert order1["_id"] != order2["_id"]
    assert order1["customer_id"] == "cust-1"
    assert order2["customer_id"] == "cust-2"


@async_test
async def test_rejects_tenant_mismatch():
    """Test that providing a mismatched tenant_id in order_data or call raises scope error."""
    mock_db = create_mock_tenant_db()
    repo = TenantOrdersRepository("tenant-123", mock_db)

    with pytest.raises((ValueError, TenantOrdersScopeError), match="[Tt]enant.*mismatch"):
        await repo.create_order(
            customer_id="cust-456",
            invoice_id="INV-001",
            idempotency_key="key-1",
            order_data={"tenant_id": "tenant-other"}
        )


@async_test
async def test_create_order_validates_required_parameters():
    """Test that customer_id and invoice_id cannot be empty."""
    mock_db = create_mock_tenant_db()
    repo = TenantOrdersRepository("tenant-123", mock_db)

    with pytest.raises(ValueError, match="customer_id is required"):
        await repo.create_order(
            customer_id="",
            invoice_id="INV-001"
        )

    with pytest.raises(ValueError, match="invoice_id is required"):
        await repo.create_order(
            customer_id="cust-456",
            invoice_id=""
        )


@async_test
async def test_get_order_by_id_scoped_to_tenant():
    """Test fetching an order by ID respects tenant isolation."""
    mock_db = create_mock_tenant_db()
    repo1 = TenantOrdersRepository("tenant-123", mock_db)
    repo2 = TenantOrdersRepository("tenant-other", mock_db)

    order = await repo1.create_order(
        customer_id="cust-456",
        invoice_id="INV-001",
        idempotency_key="key-1",
        order_data={"total": 1000}
    )

    found1 = await repo1.get_order_by_id(order["_id"])
    assert found1 is not None
    assert found1["_id"] == order["_id"]

    found2 = await repo2.get_order_by_id(order["_id"])
    assert found2 is None


@async_test
async def test_get_order_by_invoice_id_scoped_to_tenant():
    """Test fetching an order by invoice_id respects tenant isolation."""
    mock_db = create_mock_tenant_db()
    repo1 = TenantOrdersRepository("tenant-123", mock_db)
    repo2 = TenantOrdersRepository("tenant-other", mock_db)

    await repo1.create_order(
        customer_id="cust-456",
        invoice_id="INV-001",
        idempotency_key="key-1",
        order_data={"total": 1000}
    )

    found1 = await repo1.get_order_by_invoice_id("INV-001")
    assert found1 is not None
    assert found1["invoice_id"] == "INV-001"

    found2 = await repo2.get_order_by_invoice_id("INV-001")
    assert found2 is None


@async_test
async def test_find_order_by_idempotency_scoped_to_tenant():
    """Test fetching an order by customer_id + idempotency_key respects tenant isolation."""
    mock_db = create_mock_tenant_db()
    repo1 = TenantOrdersRepository("tenant-123", mock_db)
    repo2 = TenantOrdersRepository("tenant-other", mock_db)

    created = await repo1.create_order(
        customer_id="cust-456",
        invoice_id="INV-001",
        idempotency_key="key-1",
        order_data={"total": 1000}
    )

    found1 = await repo1.find_order_by_idempotency(customer_id="cust-456", idempotency_key="key-1")
    assert found1 is not None
    assert found1["_id"] == created["_id"]

    found2 = await repo2.find_order_by_idempotency(customer_id="cust-456", idempotency_key="key-1")
    assert found2 is None


@async_test
async def test_concurrent_duplicate_key_error_returns_existing_order():
    """Test that race condition DuplicateKeyError returns the existing order."""
    class ConcurrentRaceMockCollection:
        def __init__(self):
            self.first_find = True
            self.stored = None

        async def find_one(self, query):
            if self.first_find:
                self.first_find = False
                return None
            return self.stored

        async def insert_one(self, document):
            self.stored = dict(document, _id="existing-order-race")
            raise Exception("E11000 duplicate key error collection: purchases index: store_customer_idempotency_unique")

    class ConcurrentMockDatabase:
        def __init__(self):
            self.purchases = ConcurrentRaceMockCollection()

    mock_db = ConcurrentMockDatabase()
    repo = TenantOrdersRepository("tenant-123", mock_db)

    order = await repo.create_order(
        customer_id="cust-456",
        invoice_id="INV-001",
        idempotency_key="key-race",
        order_data={"total": 1000}
    )

    assert order["_id"] == "existing-order-race"
