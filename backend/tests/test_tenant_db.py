import pytest

from tenant_db import (
    PLATFORM_DATABASE_ENV_VAR,
    resolve_platform_database_name,
    tenant_database_name,
    validate_tenant_id,
)


def test_tenant_database_name_uses_isolated_safe_prefix():
    assert tenant_database_name("acme-shop") == "sellerbottel_tenant_acme_shop"


@pytest.mark.parametrize("tenant_id", ["acme", "acme-shop", "tenant_42"])
def test_validate_tenant_id_accepts_safe_slug(tenant_id):
    assert validate_tenant_id(tenant_id) == tenant_id


@pytest.mark.parametrize(
    "tenant_id",
    ["", " has-space", "has space", "tenant.db", "tenant/db", "tenant$", "-tenant", "tenant-"],
)
def test_validate_tenant_id_rejects_unsafe_slug(tenant_id):
    with pytest.raises(ValueError, match="tenant ID"):
        validate_tenant_id(tenant_id)


def test_validate_tenant_id_rejects_non_string_value():
    with pytest.raises(ValueError, match="tenant ID"):
        validate_tenant_id(None)


@pytest.mark.parametrize("tenant_id", ["sellerbottel", "sellerbottel_mock_only"])
def test_tenant_database_name_rejects_reserved_legacy_database_names(tenant_id):
    with pytest.raises(ValueError, match="reserved"):
        tenant_database_name(tenant_id)


def test_tenant_database_name_rejects_configured_platform_database_name_collision():
    with pytest.raises(ValueError, match="reserved"):
        tenant_database_name(
            "platform-core",
            platform_database_name="sellerbottel_tenant_platform_core",
        )


def test_resolve_platform_database_name_uses_safe_default_when_env_is_missing():
    assert resolve_platform_database_name({}) == "sellerbottel"


def test_resolve_platform_database_name_reads_configured_environment_value():
    environment = {PLATFORM_DATABASE_ENV_VAR: "platform_core"}

    assert resolve_platform_database_name(environment) == "platform_core"


@pytest.mark.parametrize(
    "value",
    ["", " ", "not valid", "tenant/db", "tenant.db", "tenant$"],
)
def test_resolve_platform_database_name_rejects_unsafe_environment_value(value):
    with pytest.raises(ValueError, match=PLATFORM_DATABASE_ENV_VAR):
        resolve_platform_database_name({PLATFORM_DATABASE_ENV_VAR: value})
