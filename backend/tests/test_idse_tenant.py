"""Tests for IDSE tenant metadata and initialization."""

from idse_tenant import (
    IDSE_TENANT_ID,
    IDSE_TENANT_NAME,
    IDSE_DEFAULT_PLAN,
    get_idse_tenant_metadata,
    ensure_idse_tenant,
)
from tenant_registry import TenantRegistry


def test_idse_constants_are_defined():
    assert IDSE_TENANT_ID == "idse"
    assert IDSE_TENANT_NAME == "IDSE Digital Market"
    assert IDSE_DEFAULT_PLAN == "lifetime"


def test_get_idse_tenant_metadata_returns_canonical_definition():
    metadata = get_idse_tenant_metadata()
    
    assert metadata["slug"] == "idse"
    assert metadata["name"] == "IDSE Digital Market"
    assert metadata["plan"] == "lifetime"
    assert metadata["status"] == "active"
    assert metadata["database_name"] == "sellerbottel_tenant_idse"


def test_ensure_idse_tenant_creates_tenant_when_not_registered():
    registry = TenantRegistry()
    provisioned = []
    
    def mock_provisioning(tenant):
        provisioned.append(tenant)
    
    result = ensure_idse_tenant(registry, mock_provisioning)
    
    assert result["slug"] == "idse"
    assert result["name"] == "IDSE Digital Market"
    assert result["plan"] == "lifetime"
    assert result["status"] == "active"
    assert result["database_name"] == "sellerbottel_tenant_idse"
    assert len(provisioned) == 1
    assert provisioned[0]["slug"] == "idse"
    assert registry.get_tenant("idse")["plan"] == "lifetime"


def test_ensure_idse_tenant_is_idempotent_when_tenant_already_exists():
    registry = TenantRegistry()
    provisioned = []
    
    def mock_provisioning(tenant):
        provisioned.append(tenant)
    
    # First call creates tenant
    first_result = ensure_idse_tenant(registry, mock_provisioning)
    
    # Second call returns existing tenant without re-provisioning
    second_result = ensure_idse_tenant(registry, mock_provisioning)
    
    assert second_result["slug"] == "idse"
    assert second_result["_id"] == first_result["_id"]
    assert len(provisioned) == 1  # Provisioning called only once


def test_ensure_idse_tenant_skips_provisioning_when_provisioning_fn_is_none():
    registry = TenantRegistry()
    
    result = ensure_idse_tenant(registry, provisioning_fn=None)
    
    assert result["slug"] == "idse"
    assert registry.get_tenant("idse") is not None
