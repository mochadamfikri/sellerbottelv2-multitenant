"""Tests for the tenant registry dependency injection module."""
import asyncio
import sys
from functools import wraps
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from mongomock_motor import AsyncMongoMockClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return wrapper


def test_get_tenant_registry_returns_singleton():
    """get_tenant_registry should return the same MongoTenantRegistry instance."""
    from dependencies import get_tenant_registry

    registry = get_tenant_registry()
    registry2 = get_tenant_registry()
    assert registry is registry2


def test_get_tenant_registry_returns_mongo_tenant_registry():
    """get_tenant_registry must return a MongoTenantRegistry, not an in-memory TenantRegistry."""
    from dependencies import get_tenant_registry
    from tenant_registry import MongoTenantRegistry

    registry = get_tenant_registry()
    assert isinstance(registry, MongoTenantRegistry), (
        f"Expected MongoTenantRegistry, got {type(registry).__name__}"
    )


def test_get_tenant_registry_uses_db_client():
    """The MongoTenantRegistry from get_tenant_registry should use the db module's client."""
    from dependencies import get_tenant_registry
    from db import client as db_client

    registry = get_tenant_registry()
    assert registry.client is db_client
