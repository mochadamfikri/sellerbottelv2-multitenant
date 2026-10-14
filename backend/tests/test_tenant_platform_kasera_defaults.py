from __future__ import annotations

import asyncio
from functools import wraps


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return wrapper


class Collection:
    def __init__(self, document=None):
        self.document = document

    async def find_one(self, _query):
        return self.document


class TenantDb:
    def __init__(self):
        self.payment_settings = Collection()
        self.gateway_credentials = Collection()


class PlatformDb:
    def __init__(self):
        self.platform_payment_settings = Collection({
            "_id": "kasera",
            "credential_id": "platform-credential",
            "environment": "live",
            "capabilities": {"coverage": "LIVE", "supported_methods": ["qris"]},
        })


@async_test
async def test_new_tenant_inherits_platform_kasera_live(monkeypatch):
    import payments.router as router

    tenant = TenantDb()
    platform = PlatformDb()
    monkeypatch.setattr(router, "db", tenant)
    monkeypatch.setattr(router, "platform_db", lambda: platform)
    monkeypatch.setattr(router.launch, "enabled", lambda: False)

    result = await router.settings_response()

    assert result["payment_mode"] == "platform_settlement"
    assert result["provider"] == "kasera"
    assert result["environment"] == "live"
    assert result["platform_configured"] is True
    assert result["masked_fields"] == {}


@async_test
async def test_new_tenant_test_connection_uses_platform_route(monkeypatch):
    import payments.router as router

    tenant = TenantDb()
    platform = PlatformDb()
    expected = {"coverage": "LIVE", "supported_methods": ["qris"]}

    async def resolve_platform(*_args):
        return "platform_settlement", object(), "platform-credential", expected

    monkeypatch.setattr(router, "db", tenant)
    monkeypatch.setattr(router, "platform_db", lambda: platform)
    monkeypatch.setattr(router, "_resolve_db", lambda: tenant)
    monkeypatch.setattr(router, "tenant_identity", lambda _database: "tenant-new")
    monkeypatch.setattr(router, "resolve", resolve_platform)

    assert await router.test_connection() == expected


@async_test
async def test_v1_launch_rejects_tenant_self_gateway(monkeypatch):
    import payments.router as router
    from commerce.fulfillment_types import CommerceError

    tenant = TenantDb()
    monkeypatch.setattr(router, "_resolve_db", lambda: tenant)
    monkeypatch.setattr(router, "tenant_identity", lambda _database: "tenant-new")
    monkeypatch.setattr(router.launch, "enabled", lambda: True)
    monkeypatch.setattr(router.launch, "require_provider", lambda _provider: None)

    body = router.SettingsBody(
        payment_mode="self_gateway", provider="kasera", environment="sandbox"
    )
    try:
        await router.save_settings(body)
    except CommerceError as error:
        assert "Settlement IDSE" in str(error)
    else:  # pragma: no cover - explicit regression guard
        raise AssertionError("self gateway must be rejected in V1 launch mode")
