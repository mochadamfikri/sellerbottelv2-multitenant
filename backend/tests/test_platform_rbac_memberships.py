"""TDD coverage for persistent platform tenant memberships."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(coro):
    return asyncio.run(coro)


def test_add_tenant_member_persists_required_membership_fields():
    from platform_rbac import add_tenant_member

    db = AsyncMongoMockClient()["platform"]
    membership = run(add_tenant_member(db, "tenant-1", "user-1", "tenant_admin"))

    assert membership["tenant_id"] == "tenant-1"
    assert membership["user_id"] == "user-1"
    assert membership["role"] == "tenant_admin"
    assert membership["_id"]
    assert membership["created_at"] == membership["updated_at"]
    assert run(db.tenant_memberships.find_one({"_id": membership["_id"]})) == membership


def test_add_tenant_member_updates_existing_membership_without_duplicate():
    from platform_rbac import add_tenant_member, list_tenant_members

    db = AsyncMongoMockClient()["platform"]
    created = run(add_tenant_member(db, "tenant-1", "user-1", "tenant_viewer"))
    updated = run(add_tenant_member(db, "tenant-1", "user-1", "tenant_operator"))

    assert updated["_id"] == created["_id"]
    assert updated["role"] == "tenant_operator"
    assert updated["updated_at"] >= created["updated_at"]
    assert len(run(list_tenant_members(db, "tenant-1"))) == 1


def test_add_tenant_member_rejects_unknown_role():
    from platform_rbac import add_tenant_member

    with pytest.raises(ValueError, match="role"):
        run(add_tenant_member(AsyncMongoMockClient()["platform"], "tenant-1", "user-1", "editor"))


def test_get_and_list_memberships_are_scoped_to_tenant():
    from platform_rbac import add_tenant_member, get_tenant_membership, list_tenant_members

    db = AsyncMongoMockClient()["platform"]
    run(add_tenant_member(db, "tenant-1", "user-1", "tenant_owner"))
    run(add_tenant_member(db, "tenant-1", "user-2", "tenant_viewer"))
    run(add_tenant_member(db, "tenant-2", "user-1", "tenant_admin"))

    assert run(get_tenant_membership(db, "tenant-1", "user-1"))["role"] == "tenant_owner"
    assert run(get_tenant_membership(db, "tenant-2", "user-2")) is None
    assert [member["user_id"] for member in run(list_tenant_members(db, "tenant-1"))] == ["user-1", "user-2"]


def test_remove_tenant_member_removes_only_requested_membership():
    from platform_rbac import add_tenant_member, get_tenant_membership, remove_tenant_member

    db = AsyncMongoMockClient()["platform"]
    run(add_tenant_member(db, "tenant-1", "user-1", "tenant_owner"))
    run(add_tenant_member(db, "tenant-2", "user-1", "tenant_owner"))

    assert run(remove_tenant_member(db, "tenant-1", "user-1")) is True
    assert run(get_tenant_membership(db, "tenant-1", "user-1")) is None
    assert run(get_tenant_membership(db, "tenant-2", "user-1")) is not None
    assert run(remove_tenant_member(db, "tenant-1", "user-1")) is False


def test_require_tenant_role_allows_member_with_sufficient_role(monkeypatch):
    import platform_rbac

    db = AsyncMongoMockClient()["platform"]
    run(platform_rbac.add_tenant_member(db, "tenant-1", "user-1", "tenant_admin"))
    monkeypatch.setattr(platform_rbac, "db", db)

    principal = {"_id": "user-1", "email": "user@example.com"}
    assert run(platform_rbac.require_tenant_role("tenant-1", "tenant_operator")(principal)) == principal


def test_require_tenant_role_rejects_missing_or_insufficient_membership(monkeypatch):
    import platform_rbac

    db = AsyncMongoMockClient()["platform"]
    run(platform_rbac.add_tenant_member(db, "tenant-1", "viewer", "tenant_viewer"))
    monkeypatch.setattr(platform_rbac, "db", db)

    with pytest.raises(HTTPException) as missing:
        run(platform_rbac.require_tenant_role("tenant-1", "tenant_viewer")({"_id": "missing"}))
    assert missing.value.status_code == 403

    with pytest.raises(HTTPException) as insufficient:
        run(platform_rbac.require_tenant_role("tenant-1", "tenant_admin")({"_id": "viewer"}))
    assert insufficient.value.status_code == 403


def test_require_tenant_membership_requires_at_least_viewer_role(monkeypatch):
    import platform_rbac

    db = AsyncMongoMockClient()["platform"]
    monkeypatch.setattr(platform_rbac, "db", db)

    with pytest.raises(HTTPException) as denied:
        run(platform_rbac.require_tenant_membership("tenant-1")({"_id": "missing"}))
    assert denied.value.status_code == 403
