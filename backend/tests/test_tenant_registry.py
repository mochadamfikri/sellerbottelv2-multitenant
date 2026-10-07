from datetime import datetime, timezone

from tenant_registry import TenantRegistry


def test_create_tenant_stores_required_fields_and_derived_database_name():
    registry = TenantRegistry(environment={"DB_NAME": "platform_db"})

    tenant = registry.create_tenant(slug="acme-shop", name="Acme Shop")

    assert tenant["_id"]
    assert tenant["slug"] == "acme-shop"
    assert tenant["name"] == "Acme Shop"
    assert tenant["status"] == "active"
    assert tenant["database_name"] == "sellerbottel_tenant_acme_shop"
    assert isinstance(tenant["created_at"], datetime)
    assert tenant["created_at"].tzinfo == timezone.utc


def test_get_tenant_returns_a_copy_by_slug():
    registry = TenantRegistry()
    created = registry.create_tenant(slug="acme", name="Acme")

    tenant = registry.get_tenant("acme")

    assert tenant == created
    assert tenant is not created


def test_get_tenant_returns_none_for_unknown_slug():
    assert TenantRegistry().get_tenant("missing") is None


def test_list_tenants_returns_created_tenants_in_creation_order():
    registry = TenantRegistry()
    registry.create_tenant(slug="beta", name="Beta")
    registry.create_tenant(slug="alpha", name="Alpha")

    assert [tenant["slug"] for tenant in registry.list_tenants()] == ["beta", "alpha"]


def test_create_tenant_rejects_duplicate_slug():
    registry = TenantRegistry()
    registry.create_tenant(slug="acme", name="Acme")

    try:
        registry.create_tenant(slug="acme", name="Duplicate Acme")
    except ValueError as error:
        assert "slug" in str(error).lower()
    else:
        raise AssertionError("duplicate tenant slug was accepted")


def test_update_status_changes_an_existing_tenant():
    registry = TenantRegistry()
    registry.create_tenant(slug="acme", name="Acme")

    updated = registry.update_status("acme", "suspended")

    assert updated["status"] == "suspended"
    assert registry.get_tenant("acme")["status"] == "suspended"


def test_update_status_rejects_unsupported_status():
    registry = TenantRegistry()
    registry.create_tenant(slug="acme", name="Acme")

    try:
        registry.update_status("acme", "deleting")
    except ValueError as error:
        assert "status" in str(error).lower()
    else:
        raise AssertionError("unsupported tenant status was accepted")


def test_ensure_indexes_declares_unique_slug_index():
    registry = TenantRegistry()

    indexes = registry.ensure_indexes()

    assert indexes == {"slug": {"unique": True}}
