"""TDD tests for Blocker 4: slug→UUID resolution in RBAC tenant role checks.

tenant_memberships.tenant_id stores UUID but require_tenant_role may receive
a slug from the X-Tenant-ID header. Option A: resolve slug→UUID via registry
lookup before querying memberships.
"""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from mongomock_motor import AsyncMongoMockClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. resolve_tenant_id_or_slug: core resolution function
# ---------------------------------------------------------------------------

class TestResolveTenantIdOrSlug:
    """resolve_tenant_id_or_slug should return the canonical UUID for a tenant,
    whether given a UUID directly or a slug that needs registry lookup."""

    def test_returns_uuid_unchanged_when_given_uuid(self):
        """If tenant_id_or_slug looks like a UUID, return it as-is without registry lookup."""
        from platform_rbac import resolve_tenant_id_or_slug

        tenant_uuid = str(uuid4())
        # No registry needed for UUID passthrough
        result = run(resolve_tenant_id_or_slug(tenant_uuid, registry=None))
        assert result == tenant_uuid

    def test_resolves_slug_to_uuid_via_registry(self):
        """If tenant_id_or_slug is a slug (not UUID format), look up UUID from registry."""
        from platform_rbac import resolve_tenant_id_or_slug
        from tenant_registry import MongoTenantRegistry

        client = AsyncMongoMockClient()
        registry = MongoTenantRegistry(
            environment={"DB_NAME": "platform_test"},
            client=client,
        )
        # Create a tenant so the registry has a slug→UUID mapping
        tenant = run(registry.create_tenant("acme-shop", "Acme Shop", "demo"))
        tenant_uuid = tenant["_id"]

        result = run(resolve_tenant_id_or_slug("acme-shop", registry=registry))
        assert result == tenant_uuid

    def test_raises_404_for_unknown_slug(self):
        """If the slug doesn't exist in registry, raise HTTPException 404."""
        from fastapi import HTTPException
        from platform_rbac import resolve_tenant_id_or_slug
        from tenant_registry import MongoTenantRegistry

        client = AsyncMongoMockClient()
        registry = MongoTenantRegistry(
            environment={"DB_NAME": "platform_test"},
            client=client,
        )

        with pytest.raises(HTTPException) as exc_info:
            run(resolve_tenant_id_or_slug("nonexistent-slug", registry=registry))
        assert exc_info.value.status_code == 404

    def test_preserves_slug_when_no_registry_is_configured(self):
        """Legacy slug-valued memberships remain usable until a registry is configured."""
        from platform_rbac import resolve_tenant_id_or_slug

        assert run(resolve_tenant_id_or_slug("some-slug", registry=None)) == "some-slug"

    def test_auto_discovers_registry_from_tenant_context(self, monkeypatch):
        """When registry=None, resolve_tenant_id_or_slug auto-discovers configured tenant_context registry."""
        import tenant_context
        from platform_rbac import resolve_tenant_id_or_slug
        from tenant_registry import MongoTenantRegistry

        client = AsyncMongoMockClient()
        reg = MongoTenantRegistry(
            environment={"DB_NAME": "platform_test"},
            client=client,
        )
        tenant = run(reg.create_tenant("gamma-shop", "Gamma Shop", "demo"))
        tenant_uuid = tenant["_id"]

        monkeypatch.setattr(tenant_context, "_tenant_registry", reg)
        result = run(resolve_tenant_id_or_slug("gamma-shop"))
        assert result == tenant_uuid


# ---------------------------------------------------------------------------
# 2. require_tenant_role with slug resolution
# ---------------------------------------------------------------------------

class TestRequireTenantRoleWithSlug:
    """require_tenant_role should resolve slug→UUID before checking membership."""

    def test_slug_resolves_and_matches_uuid_membership(self, monkeypatch):
        """When X-Tenant-ID is a slug, require_tenant_role should resolve it
        to UUID and find the membership stored with that UUID."""
        import platform_rbac
        from tenant_registry import MongoTenantRegistry

        client = AsyncMongoMockClient()
        db = client["platform_test"]
        registry = MongoTenantRegistry(
            environment={"DB_NAME": "platform_test"},
            client=client,
        )

        # Create tenant (UUID generated internally)
        tenant = run(registry.create_tenant("acme-shop", "Acme Shop", "demo"))
        tenant_uuid = tenant["_id"]

        # Create membership using the UUID (as stored in DB)
        run(platform_rbac.add_tenant_member(db, tenant_uuid, "user-1", "tenant_admin"))

        # Monkeypatch the module-level db
        monkeypatch.setattr(platform_rbac, "db", db)

        # Now require_tenant_role with SLUG should resolve to UUID and succeed
        principal = {"_id": "user-1", "email": "user@example.com"}
        dep = platform_rbac.require_tenant_role(
            "acme-shop", "tenant_viewer", registry=registry
        )
        result = run(dep(principal))
        assert result == principal

    def test_uuid_passthrough_still_works(self, monkeypatch):
        """When X-Tenant-ID is already a UUID, require_tenant_role should work
        without registry lookup (backward compatible)."""
        import platform_rbac

        db = AsyncMongoMockClient()["platform"]
        tenant_uuid = str(uuid4())

        run(platform_rbac.add_tenant_member(db, tenant_uuid, "user-1", "tenant_owner"))
        monkeypatch.setattr(platform_rbac, "db", db)

        principal = {"_id": "user-1"}
        dep = platform_rbac.require_tenant_role(tenant_uuid, "tenant_viewer")
        result = run(dep(principal))
        assert result == principal

    def test_slug_resolution_rejects_when_no_membership(self, monkeypatch):
        """After resolving slug→UUID, if no membership exists, reject with 403."""
        import platform_rbac
        from fastapi import HTTPException
        from tenant_registry import MongoTenantRegistry

        client = AsyncMongoMockClient()
        db = client["platform_test"]
        registry = MongoTenantRegistry(
            environment={"DB_NAME": "platform_test"},
            client=client,
        )

        tenant = run(registry.create_tenant("beta-shop", "Beta Shop", "demo"))
        # No membership created for user-1

        monkeypatch.setattr(platform_rbac, "db", db)

        principal = {"_id": "user-1"}
        dep = platform_rbac.require_tenant_role(
            "beta-shop", "tenant_viewer", registry=registry
        )
        with pytest.raises(HTTPException) as exc_info:
            run(dep(principal))
        assert exc_info.value.status_code == 403
