"""Authorization boundaries for dynamic V2 commerce tenant scope."""
import asyncio
from functools import wraps
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return wrapper


def make_context(tenant_id, database):
    return SimpleNamespace(tenant_id=tenant_id, database=database, status="active", metadata={})


def make_app(context, principal, platform_db):
    """App wired to isolated context, principal, and platform membership store."""
    import platform_rbac
    from auth import get_current_admin
    from tenant_context import get_tenant_context
    from v2_commerce_routes import router

    platform_rbac.db = platform_db
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: context
    app.dependency_overrides[get_current_admin] = lambda: principal
    return app


@async_test
async def test_missing_auth_returns_401():
    """No authenticated principal is rejected before commerce read."""
    import platform_rbac
    from auth import get_current_admin
    from tenant_context import get_tenant_context
    from v2_commerce_routes import router

    database = AsyncMongoMockClient()["tenant_a_db"]
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_tenant_context] = lambda: make_context("tenant-a", database)

    def missing_auth():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_current_admin] = missing_auth
    platform_rbac.db = AsyncMongoMockClient()["platform"]
    assert TestClient(app).get("/products").status_code == 401


@async_test
async def test_viewer_can_read_but_cannot_write():
    """tenant_viewer can list products, but cannot create one."""
    from platform_rbac import add_tenant_member

    client_db = AsyncMongoMockClient()
    platform_db = client_db["platform"]
    tenant_db = client_db["tenant_a"]
    user_id = str(uuid4())
    await add_tenant_member(platform_db, "tenant-a", user_id, "tenant_viewer")

    app = make_app(make_context("tenant-a", tenant_db), {"_id": user_id}, platform_db)
    client = TestClient(app)
    assert client.get("/products").status_code == 200
    assert client.post("/products", json={"name": "A", "price": "1.00"}).status_code == 403


@async_test
async def test_operator_cannot_write_other_tenant():
    """tenant_operator membership is bound to the context tenant only."""
    from platform_rbac import add_tenant_member
    from tenant_context import get_tenant_context

    mongo = AsyncMongoMockClient()
    platform_db = mongo["platform"]
    shared_tenant_db = mongo["tenant_data"]
    user_id = str(uuid4())
    await add_tenant_member(platform_db, "tenant-a", user_id, "tenant_operator")

    app = make_app(make_context("tenant-a", shared_tenant_db), {"_id": user_id}, platform_db)
    client = TestClient(app)
    assert client.post("/products", json={"name": "A", "price": "1.00"}).status_code == 200

    app.dependency_overrides[get_tenant_context] = lambda: make_context("tenant-b", shared_tenant_db)
    assert client.post("/products", json={"name": "B", "price": "1.00"}).status_code == 403


@async_test
async def test_tenant_admin_cannot_read_other_tenant():
    """tenant_admin for A receives 403 when switching context to B."""
    from platform_rbac import add_tenant_member
    from tenant_context import get_tenant_context

    mongo = AsyncMongoMockClient()
    platform_db = mongo["platform"]
    tenant_db = mongo["tenant_data"]
    user_id = str(uuid4())
    await add_tenant_member(platform_db, "tenant-a", user_id, "tenant_admin")

    app = make_app(make_context("tenant-a", tenant_db), {"_id": user_id}, platform_db)
    client = TestClient(app)
    assert client.get("/products").status_code == 200

    app.dependency_overrides[get_tenant_context] = lambda: make_context("tenant-b", tenant_db)
    assert client.get("/products").status_code == 403


@async_test
async def test_platform_admin_requires_explicit_tenant_membership():
    """Platform authority does not silently bypass tenant membership."""
    mongo = AsyncMongoMockClient()
    platform_db = mongo["platform"]
    app = make_app(
        make_context("tenant-a", mongo["tenant_a"]),
        {"_id": str(uuid4()), "platform_role": "platform_admin"},
        platform_db,
    )
    assert TestClient(app).get("/products").status_code == 403
