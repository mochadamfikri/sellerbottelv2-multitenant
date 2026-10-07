"""Regression tests for server startup configuration validation."""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_startup_rejects_production_mongo_url_in_development_before_db_init(monkeypatch):
    """Startup rejects a production MongoDB endpoint before database initialization."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017/sellerbottel_dev")
    monkeypatch.setenv("DB_NAME", "sellerbottel_dev")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-secret")

    import server

    with patch.object(server, "ensure_settings", new_callable=AsyncMock) as ensure_settings:
        with patch.object(server, "ensure_indexes", new_callable=AsyncMock) as ensure_indexes:
            with pytest.raises(ValueError, match="27017"):
                asyncio.run(server.startup())

    ensure_settings.assert_not_awaited()
    ensure_indexes.assert_not_awaited()


def test_startup_configures_tenant_registry_resolver(monkeypatch):
    """Server startup must call configure_tenant_registry_resolver with MongoTenantRegistry."""
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-secret")

    import server

    with patch.object(server, "ensure_settings", new_callable=AsyncMock), \
         patch.object(server, "ensure_indexes", new_callable=AsyncMock), \
         patch.object(server, "load_overrides", new_callable=AsyncMock), \
         patch.object(server, "seed_admin", new_callable=AsyncMock), \
         patch.object(server, "resume_service_waiters", new_callable=AsyncMock), \
         patch.object(server, "start_promo_runtime", new_callable=AsyncMock), \
         patch("server.validate_environment", return_value="production"), \
         patch("server.configure_tenant_registry_resolver") as mock_configure:
        try:
            asyncio.run(server.startup())
        except (RuntimeError, Exception):
            pass

    mock_configure.assert_called_once()
    args = mock_configure.call_args
    # First argument should be a MongoTenantRegistry instance
    from tenant_registry import MongoTenantRegistry
    assert isinstance(args[0][0], MongoTenantRegistry), (
        f"Expected MongoTenantRegistry, got {type(args[0][0])}"
    )
    # Second argument should be the db client
    from db import client as db_client
    assert args[0][1] is db_client


def test_startup_configures_registry_before_routes_are_usable(monkeypatch):
    """configure_tenant_registry_resolver must be called early in startup,
    before any tenant routes could be exercised."""
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-secret")

    import server

    call_order = []

    def track_configure(*args, **kwargs):
        call_order.append("configure_registry")

    async def track_ensure_settings():
        call_order.append("ensure_settings")

    with patch("server.configure_tenant_registry_resolver", side_effect=track_configure), \
         patch.object(server, "ensure_settings", side_effect=track_ensure_settings), \
         patch.object(server, "ensure_indexes", new_callable=AsyncMock), \
         patch.object(server, "load_overrides", new_callable=AsyncMock), \
         patch.object(server, "seed_admin", new_callable=AsyncMock), \
         patch.object(server, "resume_service_waiters", new_callable=AsyncMock), \
         patch.object(server, "start_promo_runtime", new_callable=AsyncMock), \
         patch("server.validate_environment", return_value="production"):
        try:
            asyncio.run(server.startup())
        except (RuntimeError, Exception):
            pass

    assert "configure_registry" in call_order, (
        "configure_tenant_registry_resolver was never called during startup"
    )
    # Registry should be configured before ensure_settings (i.e., before DB init completes)
    configure_idx = call_order.index("configure_registry")
    settings_idx = call_order.index("ensure_settings")
    assert configure_idx < settings_idx, (
        f"Registry configured at {configure_idx} but ensure_settings at {settings_idx}; "
        "registry must be configured before routes could be called"
    )
