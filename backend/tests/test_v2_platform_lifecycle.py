"""HTTP contract tests for Phase 2 tenant lifecycle management."""
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


async def _create_tenant(headers: dict[str, str], slug: str = "test-tenant") -> dict:
    """Helper to create a tenant and return its data."""
    response = await _request(
        "POST",
        "/api/v2/platform/tenants",
        json={"slug": slug, "name": f"{slug} name"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


@async_test
async def test_create_tenant_writes_audit_event():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)

    tenant = await _create_tenant(headers, "create-audit-test")

    from db import db

    event = await db.audit_events.find_one(
        {"action": "tenant.created", "scope.tenant_id": tenant["id"]}
    )
    assert event is not None
    assert event["actor"] == admin_id


@async_test
async def test_provision_tenant_database():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)
    tenant = await _create_tenant(headers, "provision-test")

    response = await _request(
        "POST",
        f"/api/v2/platform/tenants/{tenant['id']}/provision",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["provisioned"] is True
    assert data["database_name"] == tenant["database_name"]


@async_test
async def test_provision_rejects_nonexistent_tenant():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)
    fake_tenant_id = str(uuid4())

    response = await _request(
        "POST",
        f"/api/v2/platform/tenants/{fake_tenant_id}/provision",
        headers=headers,
    )

    assert response.status_code == 404


@async_test
async def test_add_member_to_tenant():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)
    tenant = await _create_tenant(headers, "member-test")
    user_id = str(uuid4())

    response = await _request(
        "POST",
        f"/api/v2/platform/tenants/{tenant['id']}/members",
        json={"user_id": user_id, "role": "tenant_admin"},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["user_id"] == user_id
    assert data["role"] == "tenant_admin"
    assert data["tenant_id"] == tenant["id"]


@async_test
async def test_list_tenant_members():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)
    tenant = await _create_tenant(headers, "list-members-test")
    user1_id = str(uuid4())
    user2_id = str(uuid4())

    # Add two members
    await _request(
        "POST",
        f"/api/v2/platform/tenants/{tenant['id']}/members",
        json={"user_id": user1_id, "role": "tenant_admin"},
        headers=headers,
    )
    await _request(
        "POST",
        f"/api/v2/platform/tenants/{tenant['id']}/members",
        json={"user_id": user2_id, "role": "tenant_viewer"},
        headers=headers,
    )

    response = await _request(
        "GET",
        f"/api/v2/platform/tenants/{tenant['id']}/members",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    members = response.json()
    assert len(members) == 2
    assert {m["user_id"] for m in members} == {user1_id, user2_id}


@async_test
async def test_remove_tenant_member():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)
    tenant = await _create_tenant(headers, "remove-member-test")
    user_id = str(uuid4())

    # Add member
    await _request(
        "POST",
        f"/api/v2/platform/tenants/{tenant['id']}/members",
        json={"user_id": user_id, "role": "tenant_admin"},
        headers=headers,
    )

    # Remove member
    response = await _request(
        "DELETE",
        f"/api/v2/platform/tenants/{tenant['id']}/members/{user_id}",
        headers=headers,
    )

    assert response.status_code == 204, response.text

    # Verify member is gone
    list_response = await _request(
        "GET",
        f"/api/v2/platform/tenants/{tenant['id']}/members",
        headers=headers,
    )
    assert len(list_response.json()) == 0


@async_test
async def test_update_tenant_plan():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)
    tenant = await _create_tenant(headers, "plan-test")

    response = await _request(
        "PATCH",
        f"/api/v2/platform/tenants/{tenant['id']}/plan",
        json={"plan": "monthly", "quotas": {"max_users": 10, "max_orders": 1000}},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["plan"] == "monthly"
    assert data["quotas"]["max_users"] == 10
    assert data["quotas"]["max_orders"] == 1000


@async_test
async def test_update_plan_validates_plan_types():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)
    tenant = await _create_tenant(headers, "plan-validation-test")

    response = await _request(
        "PATCH",
        f"/api/v2/platform/tenants/{tenant['id']}/plan",
        json={"plan": "invalid_plan", "quotas": {}},
        headers=headers,
    )

    assert response.status_code == 422


@async_test
async def test_all_phase2_endpoints_write_audit_events():
    """Verify all Phase 2 management actions are audited."""
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    headers = _admin_headers(admin_id)
    tenant = await _create_tenant(headers, "audit-coverage-test")
    user_id = str(uuid4())
    
    from db import db
    
    # Clear audit log
    await db.audit_events.delete_many({})
    
    # Provision tenant
    await _request("POST", f"/api/v2/platform/tenants/{tenant['id']}/provision", headers=headers)
    
    # Add member
    await _request(
        "POST",
        f"/api/v2/platform/tenants/{tenant['id']}/members",
        json={"user_id": user_id, "role": "tenant_admin"},
        headers=headers,
    )
    
    # Update plan
    await _request(
        "PATCH",
        f"/api/v2/platform/tenants/{tenant['id']}/plan",
        json={"plan": "monthly", "quotas": {"max_users": 5}},
        headers=headers,
    )
    
    # Remove member
    await _request(
        "DELETE",
        f"/api/v2/platform/tenants/{tenant['id']}/members/{user_id}",
        headers=headers,
    )
    
    # Verify audit events
    events = await db.audit_events.find({}).to_list(length=100)
    actions = {e["action"] for e in events}
    
    assert "tenant.provisioned" in actions
    assert "tenant.member_added" in actions
    assert "tenant.plan_updated" in actions
    assert "tenant.member_removed" in actions
    
    # Verify all events have platform scope
    for event in events:
        assert event["scope"]["platform"] == "control-plane"
        assert event["scope"]["tenant_id"] == tenant["id"]
        assert event["actor"] == admin_id
