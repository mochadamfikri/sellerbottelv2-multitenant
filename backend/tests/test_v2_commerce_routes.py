"""Offline tests for tenant commerce routes with injected context."""
import asyncio
from decimal import Decimal
from functools import wraps
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def make_tenant_context(tenant_id: str, database):
    """Factory for test tenant contexts."""
    return SimpleNamespace(
        tenant_id=tenant_id,
        database=database,
        status="active",
        metadata={},
    )


def _test_app_with_overrides(context, auth_override=None):
    """Create test app with context and optional auth overrides."""
    from v2_commerce_routes import router, require_tenant_viewer, require_tenant_operator
    from tenant_context import get_tenant_context

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    # Default: bypass auth for existing tests
    if auth_override is None:
        auth_override = {"_id": "test_user"}
    app.dependency_overrides[require_tenant_viewer] = lambda: auth_override
    app.dependency_overrides[require_tenant_operator] = lambda: auth_override

    return app


@async_test
async def test_create_product_uses_tenant_context():
    """POST /products creates product scoped to injected tenant context."""
    from v2_commerce_routes import router, CreateProductRequest
    from tenant_context import get_tenant_context

    database = AsyncMongoMockClient()["tenant_a_db"]
    context = make_tenant_context("tenant-a", database)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    client = TestClient(app)
    response = client.post("/products", json={
        "name": "Test Product",
        "price": "99.99",
        "currency": "USD",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "tenant-a"
    assert data["name"] == "Test Product"
    assert "_id" in data

    # Verify stored in correct tenant database
    stored = await database.products.find_one({"_id": data["_id"]})
    assert stored is not None
    assert stored["tenant_id"] == "tenant-a"


@async_test
async def test_list_products_scoped_to_tenant():
    """GET /products returns only products for the injected tenant."""
    from v2_commerce_routes import router
    from tenant_context import get_tenant_context

    database = AsyncMongoMockClient()["shared_db"]
    await database.products.insert_many([
        {"_id": "p1", "tenant_id": "tenant-a", "name": "Product A"},
        {"_id": "p2", "tenant_id": "tenant-b", "name": "Product B"},
        {"_id": "p3", "tenant_id": "tenant-a", "name": "Product A2"},
    ])

    context = make_tenant_context("tenant-a", database)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    client = TestClient(app)
    response = client.get("/products")

    assert response.status_code == 200
    products = response.json()
    assert len(products) == 2
    assert all(p["tenant_id"] == "tenant-a" for p in products)
    assert {p["_id"] for p in products} == {"p1", "p3"}


@async_test
async def test_patch_product_scoped_to_tenant():
    """PATCH /products/{product_id} updates only tenant's product."""
    from v2_commerce_routes import router
    from tenant_context import get_tenant_context

    database = AsyncMongoMockClient()["shared_db"]
    await database.products.insert_many([
        {"_id": "p1", "tenant_id": "tenant-a", "name": "Product A"},
        {"_id": "p2", "tenant_id": "tenant-b", "name": "Product B"},
    ])

    context = make_tenant_context("tenant-a", database)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    client = TestClient(app)

    # Update tenant-a product
    response = client.patch("/products/p1", json={"price": "199.99"})
    assert response.status_code == 200
    assert response.json()["price"] == "199.99"

    # Attempt to update tenant-b product (should 404)
    response = client.patch("/products/p2", json={"price": "299.99"})
    assert response.status_code == 404


@async_test
async def test_add_inventory_scoped_to_tenant():
    """POST /inventory creates inventory item scoped to tenant context."""
    from v2_commerce_routes import router
    from tenant_context import get_tenant_context

    database = AsyncMongoMockClient()["tenant_a_db"]
    context = make_tenant_context("tenant-a", database)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    client = TestClient(app)
    response = client.post("/inventory", json={
        "product_id": "prod-123",
        "serial_number": "SN-001",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "tenant-a"
    assert data["product_id"] == "prod-123"
    assert data["status"] == "available"
    assert "_id" in data


@async_test
async def test_get_inventory_hides_secret_fields():
    """GET /inventory/{product_id} returns inventory without secret fields."""
    from v2_commerce_routes import router
    from tenant_context import get_tenant_context

    database = AsyncMongoMockClient()["tenant_a_db"]
    await database.inventory_items.insert_many([
        {
            "_id": "inv1",
            "tenant_id": "tenant-a",
            "product_id": "prod-123",
            "serial_number": "SECRET-SN-001",
            "status": "available",
        },
        {
            "_id": "inv2",
            "tenant_id": "tenant-a",
            "product_id": "prod-123",
            "serial_number": "SECRET-SN-002",
            "status": "reserved",
            "reservation_id": "res-456",
        },
    ])

    context = make_tenant_context("tenant-a", database)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    client = TestClient(app)
    response = client.get("/inventory/prod-123")

    assert response.status_code == 200
    data = response.json()
    assert data["product_id"] == "prod-123"
    assert data["available_count"] == 1
    assert data["reserved_count"] == 1
    # Ensure no secret fields exposed
    response_str = str(response.json())
    assert "serial_number" not in response_str
    assert "SECRET-SN" not in response_str
    assert "reservation_id" not in response_str


@async_test
async def test_create_order_scoped_to_tenant():
    """POST /orders creates order scoped to tenant context."""
    from v2_commerce_routes import router
    from tenant_context import get_tenant_context

    database = AsyncMongoMockClient()["tenant_a_db"]
    context = make_tenant_context("tenant-a", database)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    client = TestClient(app)
    response = client.post("/orders", json={
        "customer_id": "cust-123",
        "invoice_id": "inv-456",
        "total": "199.99",
        "currency": "USD",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "tenant-a"
    assert data["customer_id"] == "cust-123"
    assert data["invoice_id"] == "inv-456"
    assert "_id" in data


@async_test
async def test_list_orders_scoped_to_tenant():
    """GET /orders returns only orders for the injected tenant."""
    from v2_commerce_routes import router
    from tenant_context import get_tenant_context

    database = AsyncMongoMockClient()["shared_db"]
    await database.purchases.insert_many([
        {"_id": "o1", "tenant_id": "tenant-a", "customer_id": "c1"},
        {"_id": "o2", "tenant_id": "tenant-b", "customer_id": "c2"},
        {"_id": "o3", "tenant_id": "tenant-a", "customer_id": "c3"},
    ])

    context = make_tenant_context("tenant-a", database)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    client = TestClient(app)
    response = client.get("/orders")

    assert response.status_code == 200
    orders = response.json()
    assert len(orders) == 2
    assert all(o["tenant_id"] == "tenant-a" for o in orders)
    assert {o["_id"] for o in orders} == {"o1", "o3"}


@async_test
async def test_create_wallet_entry_scoped_to_tenant():
    """POST /wallet/entries creates ledger entry scoped to tenant."""
    from v2_commerce_routes import router
    from tenant_context import get_tenant_context

    database = AsyncMongoMockClient()["tenant_a_db"]
    context = make_tenant_context("tenant-a", database)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    client = TestClient(app)
    response = client.post("/wallet/entries", json={
        "entry_type": "credit",
        "amount": "100.00",
        "currency": "USD",
        "reference_id": "ref-123",
        "idempotency_key": "idem-456",
        "description": "Test credit",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["entry"]["tenant_id"] == "tenant-a"
    assert data["entry"]["entry_type"] == "credit"
    assert data["entry"]["amount"] == "100.00"
    assert data["replayed"] is False


@async_test
async def test_get_wallet_balance_scoped_to_tenant():
    """GET /wallet/{customer_id}/balance calculates balance for tenant."""
    from v2_commerce_routes import router
    from tenant_context import get_tenant_context

    database = AsyncMongoMockClient()["tenant_a_db"]
    await database.wallet_ledger.insert_many([
        {
            "tenant_id": "tenant-a",
            "entry_type": "credit",
            "amount": "100.00",
            "currency": "USD",
            "reference_id": "ref1",
        },
        {
            "tenant_id": "tenant-a",
            "entry_type": "debit",
            "amount": "30.00",
            "currency": "USD",
            "reference_id": "ref2",
        },
        {
            "tenant_id": "tenant-b",
            "entry_type": "credit",
            "amount": "500.00",
            "currency": "USD",
            "reference_id": "ref3",
        },
    ])

    context = make_tenant_context("tenant-a", database)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    client = TestClient(app)
    response = client.get("/wallet/cust-123/balance?currency=USD")

    assert response.status_code == 200
    data = response.json()
    assert data["balance"] == "70.00"
    assert data["currency"] == "USD"


@async_test
async def test_sandbox_payment_scoped_to_tenant():
    """POST /payments/sandbox creates payment scoped to tenant."""
    from v2_commerce_routes import router
    from tenant_context import get_tenant_context

    database = AsyncMongoMockClient()["tenant_a_db"]
    context = make_tenant_context("tenant-a", database)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    from v2_commerce_routes import require_tenant_viewer, require_tenant_operator
    app.dependency_overrides[require_tenant_viewer] = lambda: {"_id": "test-user"}
    app.dependency_overrides[require_tenant_operator] = lambda: {"_id": "test-user"}

    client = TestClient(app)
    response = client.post("/payments/sandbox", json={
        "order_id": "order-123",
        "amount": "99.99",
        "currency": "USD",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "tenant-a"
    assert data["order_id"] == "order-123"
    assert data["amount"] == "99.99"
    assert data["status"] == "paid"
