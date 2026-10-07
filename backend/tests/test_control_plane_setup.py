"""Offline TDD coverage for Stage 1 control-plane setup."""
import asyncio

import pytest
from mongomock_motor import AsyncMongoMockClient


def run(coro):
    return asyncio.run(coro)


def test_setup_idse_control_plane_creates_canonical_tenant_and_grants_existing_admin():
    from control_plane_setup import setup_idse_control_plane

    database = AsyncMongoMockClient()["platform"]
    run(database.admins.insert_one({"_id": "admin-1", "email": "admin@example.test", "role": "admin"}))

    result = run(setup_idse_control_plane(database, "admin-1"))

    assert result["tenant"]["slug"] == "idse"
    assert result["tenant"]["name"] == "IDSE Digital Market"
    assert result["tenant"]["plan"] == "lifetime"
    assert result["tenant"]["status"] == "active"
    assert result["tenant"]["database_name"] == "sellerbottel_tenant_idse"
    assert result["admin"]["platform_role"] == "platform_admin"
    assert result["membership"]["tenant_id"] == result["tenant"]["_id"]
    assert result["membership"]["user_id"] == "admin-1"
    assert result["membership"]["role"] == "tenant_owner"


def test_setup_idse_control_plane_is_idempotent_without_duplicate_records():
    from control_plane_setup import setup_idse_control_plane

    database = AsyncMongoMockClient()["platform"]
    run(database.admins.insert_one({"_id": "admin-1", "email": "admin@example.test", "role": "admin"}))

    first = run(setup_idse_control_plane(database, "admin-1"))
    second = run(setup_idse_control_plane(database, "admin-1"))

    assert second["tenant"]["_id"] == first["tenant"]["_id"]
    assert second["membership"]["_id"] == first["membership"]["_id"]
    assert second["membership"]["created_at"] == first["membership"]["created_at"]
    assert run(database.tenants.count_documents({"slug": "idse"})) == 1
    assert run(database.tenant_memberships.count_documents({"tenant_id": first["tenant"]["_id"], "user_id": "admin-1"})) == 1


def test_setup_idse_control_plane_requires_existing_admin():
    from control_plane_setup import setup_idse_control_plane

    database = AsyncMongoMockClient()["platform"]

    with pytest.raises(LookupError, match="admin"):
        run(setup_idse_control_plane(database, "missing-admin"))

    assert run(database.tenants.count_documents({})) == 0
    assert run(database.tenant_memberships.count_documents({})) == 0


def test_setup_idse_control_plane_promotes_existing_non_owner_membership():
    from control_plane_setup import setup_idse_control_plane

    database = AsyncMongoMockClient()["platform"]
    run(database.admins.insert_one({"_id": "admin-1", "email": "admin@example.test", "role": "admin"}))
    run(database.tenants.insert_one({
        "_id": "existing-tenant-id",
        "slug": "idse",
        "name": "IDSE Digital Market",
        "plan": "lifetime",
        "status": "active",
        "database_name": "sellerbottel_tenant_idse",
    }))
    run(database.tenant_memberships.insert_one({
        "_id": "membership-1",
        "tenant_id": "existing-tenant-id",
        "user_id": "admin-1",
        "role": "tenant_viewer",
    }))

    result = run(setup_idse_control_plane(database, "admin-1"))

    assert result["membership"]["_id"] == "membership-1"
    assert result["membership"]["role"] == "tenant_owner"
    stored = run(database.tenant_memberships.find_one({"_id": "membership-1"}))
    assert stored["role"] == "tenant_owner"


def test_setup_idse_control_plane_resolves_admin_by_email_identifier():
    from control_plane_setup import setup_idse_control_plane

    database = AsyncMongoMockClient()["platform"]
    run(database.admins.insert_one({"_id": "admin-uuid-123", "email": "owner@idse.store", "role": "admin"}))

    result = run(setup_idse_control_plane(database, "owner@idse.store"))

    assert result["admin"]["_id"] == "admin-uuid-123"
    assert result["admin"]["platform_role"] == "platform_admin"
    assert result["membership"]["user_id"] == "admin-uuid-123"
    assert result["membership"]["role"] == "tenant_owner"


