"""Tenant isolation and boundary security test suite.

This suite verifies that:
1. Database-level isolation prevents cross-tenant data access
2. Request-boundary tenant context prevents cross-tenant operations
3. Suspended/disabled tenants are rejected with 403 Forbidden
4. Non-existent tenants are rejected with 404 Not Found
5. Invalid tenant slugs are rejected with 400 Bad Request
6. Platform admin vs tenant admin permission boundaries are enforced
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from tenant_context import configure_development_tenant_resolver, get_tenant_context


TENANTS = {
    "tenant-a": {
        "slug": "tenant-a",
        "status": "active",
        "database_name": "sellerbottel_tenant_tenant_a",
    },
    "tenant-b": {
        "slug": "tenant-b",
        "status": "active",
        "database_name": "sellerbottel_tenant_tenant_b",
    },
}


@pytest.fixture
def tenant_request_client():
    """Expose reads and mutations only through the request tenant context."""
    from db import client

    configure_development_tenant_resolver(TENANTS, client)
    app = FastAPI()

    @app.get("/records/{record_id}")
    async def read_record(record_id: str, context=Depends(get_tenant_context)):
        record = await context.database.records.find_one({"_id": record_id})
        return {"record": record}

    @app.patch("/records/{record_id}")
    async def mutate_record(record_id: str, context=Depends(get_tenant_context)):
        result = await context.database.records.update_one(
            {"_id": record_id}, {"$set": {"mutated": True}}
        )
        return {"modified_count": result.modified_count}

    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_tenant_databases():
    """Prevent data created by one security assertion leaking into another."""
    from db import client

    async def clear():
        for database_name in (
            "sellerbottel_tenant_tenant_a",
            "sellerbottel_tenant_tenant_b",
        ):
            await client[database_name].records.delete_many({})
            await client[database_name].products.delete_many({})
            await client[database_name].orders.delete_many({})
            await client[database_name].inventory.delete_many({})

    run_async(clear())
    yield
    run_async(clear())


@pytest.mark.usefixtures("tenant_request_client")
class TestTenantRequestBoundaryIsolation:
    """Assert X-Tenant-ID selects the only database a request can operate on."""

    def test_tenant_a_header_cannot_read_tenant_b_record(self, tenant_request_client):
        """A Tenant A request sees 404-equivalent empty data for Tenant B records."""
        from db import client

        run_async(
            client["sellerbottel_tenant_tenant_b"].records.insert_one(
                {"_id": "tenant-b-only", "owner": "tenant-b"}
            )
        )

        response = tenant_request_client.get(
            "/records/tenant-b-only", headers={"X-Tenant-ID": "tenant-a"}
        )

        assert response.status_code == 200
        assert response.json() == {"record": None}

    def test_tenant_a_header_cannot_mutate_tenant_b_record(self, tenant_request_client):
        """A Tenant A mutation cannot modify the identically keyed Tenant B record."""
        from db import client

        async def seed_and_verify():
            tenant_b_records = client["sellerbottel_tenant_tenant_b"].records
            await tenant_b_records.insert_one({"_id": "tenant-b-only", "mutated": False})

            response = tenant_request_client.patch(
                "/records/tenant-b-only", headers={"X-Tenant-ID": "tenant-a"}
            )

            assert response.status_code == 200
            assert response.json() == {"modified_count": 0}
            assert (await tenant_b_records.find_one({"_id": "tenant-b-only"}))["mutated"] is False

        run_async(seed_and_verify())

    @pytest.mark.parametrize(
        ("tenant_id", "status_code"),
        [
            ("suspended-tenant", 403),
            ("disabled-tenant", 403),
            ("unknown-tenant", 404),
            ("tenant/invalid", 400),
        ],
    )
    def test_request_boundary_rejects_invalid_or_inactive_tenants(
        self, tenant_request_client, tenant_id, status_code
    ):
        """The dependency maps inactive, unknown, and invalid headers to safe errors."""
        tenants = {
            **TENANTS,
            "suspended-tenant": {"status": "suspended"},
            "disabled-tenant": {"status": "disabled"},
        }
        from db import client

        configure_development_tenant_resolver(tenants, client)
        response = tenant_request_client.get(
            "/records/any-record", headers={"X-Tenant-ID": tenant_id}
        )

        assert response.status_code == status_code

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run_async(coro):
    """Helper to run async coroutines in sync tests."""
    return asyncio.run(coro)


class TestDatabaseLevelIsolation:
    """Verify that tenant databases are physically isolated."""

    def test_tenant_a_database_cannot_see_tenant_b_data(self):
        """Database handles for different tenants cannot access each other's data."""
        from db import client

        async def test():
            # Create isolated database handles for two tenants
            tenant_a_db = client["sellerbottel_tenant_tenant_a"]
            tenant_b_db = client["sellerbottel_tenant_tenant_b"]

            # Insert data into Tenant B's products collection
            await tenant_b_db.products.insert_one({"_id": "product-b1", "name": "Secret Product"})

            # Verify Tenant A cannot see Tenant B's data
            result = await tenant_a_db.products.find_one({"_id": "product-b1"})
            assert result is None, "Tenant A should not see Tenant B's data"

        run_async(test())

    def test_tenant_b_database_cannot_see_tenant_a_data(self):
        """Reverse isolation: Tenant B cannot access Tenant A's data."""
        from db import client

        async def test():
            tenant_a_db = client["sellerbottel_tenant_tenant_a"]
            tenant_b_db = client["sellerbottel_tenant_tenant_b"]

            # Insert data into Tenant A's orders collection
            await tenant_a_db.orders.insert_one({"_id": "order-a1", "total": 100.00})

            # Verify Tenant B cannot see Tenant A's data
            result = await tenant_b_db.orders.find_one({"_id": "order-a1"})
            assert result is None, "Tenant B should not see Tenant A's data"

        run_async(test())

    def test_tenant_databases_have_distinct_namespaces(self):
        """Each tenant database maintains its own collection namespace."""
        from db import client

        async def test():
            tenant_a_db = client["sellerbottel_tenant_tenant_a"]
            tenant_b_db = client["sellerbottel_tenant_tenant_b"]

            # Both tenants can have same collection and document IDs without collision
            await tenant_a_db.inventory.insert_one({"_id": "item-1", "quantity": 10})
            await tenant_b_db.inventory.insert_one({"_id": "item-1", "quantity": 20})

            # Verify each tenant sees only their own data
            a_item = await tenant_a_db.inventory.find_one({"_id": "item-1"})
            b_item = await tenant_b_db.inventory.find_one({"_id": "item-1"})

            assert a_item["quantity"] == 10, "Tenant A should see their own quantity"
            assert b_item["quantity"] == 20, "Tenant B should see their own quantity"

        run_async(test())


class TestTenantContextIsolation:
    """Verify tenant context from X-Tenant-ID header prevents cross-tenant access."""

    def test_tenant_a_context_cannot_read_tenant_b_records(self):
        """Tenant context for tenant-a cannot access tenant-b resources."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                # Return a mock that tracks which database was accessed
                return {"database_name": database_name, "accessed": True}

        tenants = {
            "tenant-a": {
                "slug": "tenant-a",
                "status": "active",
                "database_name": "sellerbottel_tenant_tenant_a",
            },
            "tenant-b": {
                "slug": "tenant-b",
                "status": "active",
                "database_name": "sellerbottel_tenant_tenant_b",
            },
        }

        # Resolve context for tenant-a
        context_a = resolve_tenant_context("tenant-a", tenants, MockDatabaseClient())

        # Verify it points to tenant-a database only
        assert context_a.tenant_id == "tenant-a"
        assert context_a.database["database_name"] == "sellerbottel_tenant_tenant_a"

        # Verify tenant-a context does NOT have access to tenant-b database
        assert context_a.database["database_name"] != "sellerbottel_tenant_tenant_b"

    def test_tenant_b_context_cannot_mutate_tenant_a_records(self):
        """Tenant context for tenant-b cannot modify tenant-a resources."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                return {"database_name": database_name}

        tenants = {
            "tenant-a": {
                "slug": "tenant-a",
                "status": "active",
                "database_name": "sellerbottel_tenant_tenant_a",
            },
            "tenant-b": {
                "slug": "tenant-b",
                "status": "active",
                "database_name": "sellerbottel_tenant_tenant_b",
            },
        }

        # Resolve context for tenant-b
        context_b = resolve_tenant_context("tenant-b", tenants, MockDatabaseClient())

        # Verify it is bound to tenant-b database
        assert context_b.tenant_id == "tenant-b"
        assert context_b.database["database_name"] == "sellerbottel_tenant_tenant_b"

        # Verify tenant-b context is NOT bound to tenant-a database
        assert context_b.database["database_name"] != "sellerbottel_tenant_tenant_a"


class TestSuspendedTenantRejection:
    """Verify suspended or disabled tenants are rejected at request boundary."""

    def test_suspended_tenant_is_rejected_with_403_forbidden(self):
        """Suspended tenant status triggers 403 Forbidden at request boundary."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                return {"database_name": database_name}

        tenants = {
            "suspended-tenant": {
                "slug": "suspended-tenant",
                "status": "suspended",
                "database_name": "sellerbottel_tenant_suspended_tenant",
            }
        }

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context("suspended-tenant", tenants, MockDatabaseClient())

        assert exc_info.value.status_code == 403
        assert "not active" in exc_info.value.detail.lower()

    def test_disabled_tenant_is_rejected_with_403_forbidden(self):
        """Any non-active status (including 'disabled') triggers 403 Forbidden."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                return {"database_name": database_name}

        tenants = {
            "disabled-tenant": {
                "slug": "disabled-tenant",
                "status": "disabled",
                "database_name": "sellerbottel_tenant_disabled_tenant",
            }
        }

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context("disabled-tenant", tenants, MockDatabaseClient())

        assert exc_info.value.status_code == 403
        assert "not active" in exc_info.value.detail.lower()

    def test_only_active_status_is_allowed(self):
        """Only tenants with status='active' are permitted access."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                return {"database_name": database_name}

        tenants = {
            "active-tenant": {
                "slug": "active-tenant",
                "status": "active",
                "database_name": "sellerbottel_tenant_active_tenant",
            }
        }

        # Should not raise
        context = resolve_tenant_context("active-tenant", tenants, MockDatabaseClient())
        assert context.tenant_id == "active-tenant"
        assert context.status == "active"


class TestNonExistentTenantRejection:
    """Verify non-existent tenants are rejected with 404 Not Found."""

    def test_non_existent_tenant_is_rejected_with_404_not_found(self):
        """Unknown tenant slug triggers 404 Not Found."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                return {"database_name": database_name}

        tenants = {
            "existing-tenant": {
                "slug": "existing-tenant",
                "status": "active",
                "database_name": "sellerbottel_tenant_existing_tenant",
            }
        }

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context("unknown-tenant", tenants, MockDatabaseClient())

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Unknown tenant"

    def test_empty_tenant_registry_rejects_all_tenants(self):
        """When no tenants are registered, all requests are rejected with 404."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                return {"database_name": database_name}

        tenants = {}

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context("any-tenant", tenants, MockDatabaseClient())

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Unknown tenant"


class TestInvalidTenantSlugRejection:
    """Verify invalid tenant slugs are rejected with 400 Bad Request."""

    def test_invalid_slug_with_slash_is_rejected_with_400_bad_request(self):
        """Tenant slug containing '/' triggers 400 Bad Request."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                return {"database_name": database_name}

        tenants = {}

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context("tenant/path", tenants, MockDatabaseClient())

        assert exc_info.value.status_code == 400
        assert "Invalid X-Tenant-ID header" in exc_info.value.detail

    def test_invalid_slug_with_dot_is_rejected_with_400_bad_request(self):
        """Tenant slug containing '.' triggers 400 Bad Request."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                return {"database_name": database_name}

        tenants = {}

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context("tenant.db", tenants, MockDatabaseClient())

        assert exc_info.value.status_code == 400
        assert "Invalid X-Tenant-ID header" in exc_info.value.detail

    def test_invalid_slug_with_special_characters_is_rejected(self):
        """Tenant slug with special characters triggers 400 Bad Request."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                return {"database_name": database_name}

        tenants = {}

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context("tenant$special", tenants, MockDatabaseClient())

        assert exc_info.value.status_code == 400
        assert "Invalid X-Tenant-ID header" in exc_info.value.detail

    def test_empty_string_slug_is_rejected_with_400_bad_request(self):
        """Empty tenant slug triggers 400 Bad Request."""
        from tenant_context import resolve_tenant_context

        class MockDatabaseClient:
            def __getitem__(self, database_name):
                return {"database_name": database_name}

        tenants = {}

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context("", tenants, MockDatabaseClient())

        assert exc_info.value.status_code == 400
        assert "Invalid X-Tenant-ID header" in exc_info.value.detail


class TestPlatformAdminVsTenantAdminBoundary:
    """Verify platform admin vs tenant admin permission boundaries."""

    def test_platform_admin_role_grants_platform_access(self):
        """Explicit platform_admin role grants platform-wide access."""
        from platform_rbac import is_platform_admin

        admin = {
            "_id": "admin-1",
            "email": "admin@example.com",
            "role": "admin",
            "platform_role": "platform_admin",
        }

        assert is_platform_admin(admin) is True

    def test_tenant_admin_role_denies_platform_access(self):
        """Explicit tenant_admin role denies platform-wide access."""
        from platform_rbac import is_platform_admin

        admin = {
            "_id": "admin-2",
            "email": "admin@example.com",
            "role": "admin",
            "platform_role": "tenant_admin",
        }

        assert is_platform_admin(admin) is False

    def test_legacy_admin_without_platform_role_has_platform_access(self):
        """Legacy admin records without platform_role retain platform access."""
        from platform_rbac import is_platform_admin

        legacy_admin = {
            "_id": "admin-3",
            "email": "legacy@example.com",
            "role": "admin",
        }

        assert is_platform_admin(legacy_admin) is True

    def test_non_admin_without_platform_role_denies_platform_access(self):
        """Non-admin users without platform_role are denied platform access."""
        from platform_rbac import is_platform_admin

        user = {
            "_id": "user-1",
            "email": "user@example.com",
            "role": "user",
        }

        assert is_platform_admin(user) is False

    def test_require_platform_admin_rejects_tenant_admin(self):
        """require_platform_admin dependency rejects tenant_admin users."""
        import asyncio

        from platform_rbac import require_platform_admin

        tenant_admin = {
            "_id": "admin-4",
            "email": "tenant@example.com",
            "role": "admin",
            "platform_role": "tenant_admin",
        }

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(require_platform_admin(tenant_admin))

        assert exc_info.value.status_code == 403
        assert "platform admin" in exc_info.value.detail.lower()


class TestCrossTenantInventoryAllocationImpossibility:
    """Verify that inventory allocation cannot cross tenant boundaries."""

    def test_tenant_a_cannot_allocate_from_tenant_b_inventory(self):
        """Tenant A's operations cannot decrement Tenant B's inventory."""
        from db import client

        async def test():
            tenant_a_db = client["sellerbottel_tenant_tenant_a"]
            tenant_b_db = client["sellerbottel_tenant_tenant_b"]

            # Tenant B has inventory
            await tenant_b_db.inventory.insert_one({"_id": "sku-100", "quantity": 50})

            # Tenant A has separate inventory with same SKU
            await tenant_a_db.inventory.insert_one({"_id": "sku-100", "quantity": 10})

            # Allocate from Tenant A's inventory
            await tenant_a_db.inventory.update_one(
                {"_id": "sku-100"}, {"$inc": {"quantity": -5}}
            )

            # Verify Tenant A's inventory decreased
            a_inventory = await tenant_a_db.inventory.find_one({"_id": "sku-100"})
            assert a_inventory["quantity"] == 5

            # Verify Tenant B's inventory is unchanged
            b_inventory = await tenant_b_db.inventory.find_one({"_id": "sku-100"})
            assert b_inventory["quantity"] == 50, "Tenant B inventory must remain unchanged"

        run_async(test())

    def test_tenant_b_cannot_allocate_from_tenant_a_inventory(self):
        """Reverse: Tenant B operations cannot affect Tenant A inventory."""
        from db import client

        async def test():
            tenant_a_db = client["sellerbottel_tenant_tenant_a"]
            tenant_b_db = client["sellerbottel_tenant_tenant_b"]

            # Tenant A has inventory
            await tenant_a_db.inventory.insert_one({"_id": "sku-200", "quantity": 100})

            # Tenant B has no such inventory initially
            result = await tenant_b_db.inventory.find_one({"_id": "sku-200"})
            assert result is None

            # Tenant B tries to allocate (this would fail to find the document)
            update_result = await tenant_b_db.inventory.update_one(
                {"_id": "sku-200"}, {"$inc": {"quantity": -10}}
            )

            # Verify no document was modified in Tenant B
            assert update_result.modified_count == 0

            # Verify Tenant A's inventory is unchanged
            a_inventory = await tenant_a_db.inventory.find_one({"_id": "sku-200"})
            assert a_inventory["quantity"] == 100, "Tenant A inventory must remain unchanged"

        run_async(test())
