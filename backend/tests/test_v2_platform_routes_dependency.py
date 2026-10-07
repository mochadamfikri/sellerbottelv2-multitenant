"""Dependency-injection regression tests for V2 platform tenant routes."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from functools import wraps
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI

os.environ.setdefault("JWT_SECRET", "offline-test-secret-at-least-32-characters")


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def _app() -> FastAPI:
    from v2_platform_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


def _token_for(admin_id: str) -> str:
    from auth import create_access_token

    return create_access_token(admin_id, f"{admin_id}@example.test")


async def _seed_admin(admin_id: str, **values: object) -> None:
    from db import db

    await db.admins.delete_many({})
    await db.admins.insert_one({"_id": admin_id, "email": f"{admin_id}@example.test", **values})


@async_test
async def test_create_tenant_uses_dependency_injected_mongo_registry():
    """Endpoint uses FastAPI's registry dependency rather than module state."""
    from dependencies import get_tenant_registry
    from tenant_registry import MongoTenantRegistry

    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    registry = AsyncMock(spec=MongoTenantRegistry)
    registry.create_tenant.return_value = {
        "_id": "injected-tenant-id",
        "slug": "injected-shop",
        "name": "Injected Shop",
        "status": "provisioning",
        "database_name": "sellerbottel_tenant_injected_shop",
        "created_at": datetime.now(timezone.utc),
    }

    app = _app()
    app.dependency_overrides[get_tenant_registry] = lambda: registry
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://offline"
    ) as client:
        response = await client.post(
            "/api/v2/platform/tenants",
            json={"slug": "injected-shop", "name": "Injected Shop"},
            headers={"Authorization": f"Bearer {_token_for(admin_id)}"},
        )

    assert response.status_code == 201, response.text
    registry.create_tenant.assert_awaited_once_with(
        slug="injected-shop", name="Injected Shop", plan="demo"
    )


def test_v2_platform_routes_has_no_module_registry_instance():
    """Routes must not retain an in-memory registry created during import."""
    import v2_platform_routes

    assert not hasattr(v2_platform_routes, "tenant_registry")
