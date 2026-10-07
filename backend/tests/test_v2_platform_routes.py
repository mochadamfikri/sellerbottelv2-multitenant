"""HTTP contract tests for the V2 platform tenant registry routes."""
from __future__ import annotations

import asyncio
import os
from functools import wraps
from uuid import uuid4

import httpx
from fastapi import FastAPI

os.environ.setdefault("JWT_SECRET", "offline-test-secret-at-least-32-characters")


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def _app():
    from v2_platform_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


def _token_for(admin_id: str) -> str:
    from auth import create_access_token

    return create_access_token(admin_id, f"{admin_id}@example.test")


async def _request(method: str, path: str, *, json=None, headers=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://offline"
    ) as client:
        return await client.request(method, path, json=json, headers=headers)


async def _seed_admin(admin_id: str, **values) -> None:
    from db import db

    await db.admins.delete_many({})
    await db.admins.insert_one({"_id": admin_id, "email": f"{admin_id}@example.test", **values})


def _admin_headers(admin_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(admin_id)}"}


@async_test
async def test_tenant_routes_require_authentication():
    response = await _request("GET", "/api/v2/platform/tenants")

    assert response.status_code == 401


@async_test
async def test_tenant_routes_reject_non_platform_admin():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="tenant_admin")

    response = await _request(
        "GET", "/api/v2/platform/tenants", headers=_admin_headers(admin_id)
    )

    assert response.status_code == 403


@async_test
async def test_create_list_and_get_tenant_without_database_credentials():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)

    created = await _request(
        "POST",
        "/api/v2/platform/tenants",
        json={"slug": "acme-shop", "name": "Acme Shop"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    tenant = created.json()
    assert tenant["slug"] == "acme-shop"
    assert tenant["name"] == "Acme Shop"
    assert tenant["status"] == "provisioning"
    assert tenant["id"]
    assert "database_credentials" not in tenant
    assert "db_credentials" not in tenant
    assert "connection_uri" not in tenant

    listed = await _request("GET", "/api/v2/platform/tenants", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [tenant["id"]]

    fetched = await _request(
        "GET", f"/api/v2/platform/tenants/{tenant['id']}", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == tenant


@async_test
async def test_create_tenant_rejects_duplicate_slug():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)
    payload = {"slug": "unique-shop", "name": "Unique Shop"}

    assert (await _request("POST", "/api/v2/platform/tenants", json=payload, headers=headers)).status_code == 201
    duplicate = await _request("POST", "/api/v2/platform/tenants", json=payload, headers=headers)

    assert duplicate.status_code == 409


@async_test
async def test_tenant_status_allows_active_and_suspended_transitions_only():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)
    created = await _request(
        "POST",
        "/api/v2/platform/tenants",
        json={"slug": "lifecycle-shop", "name": "Lifecycle Shop"},
        headers=headers,
    )
    tenant_id = created.json()["id"]

    suspended = await _request(
        "PATCH",
        f"/api/v2/platform/tenants/{tenant_id}/status",
        json={"status": "suspended"},
        headers=headers,
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"

    active = await _request(
        "PATCH",
        f"/api/v2/platform/tenants/{tenant_id}/status",
        json={"status": "active"},
        headers=headers,
    )
    assert active.status_code == 200, active.text
    assert active.json()["status"] == "active"

    invalid = await _request(
        "PATCH",
        f"/api/v2/platform/tenants/{tenant_id}/status",
        json={"status": "deleted"},
        headers=headers,
    )
    assert invalid.status_code == 422
