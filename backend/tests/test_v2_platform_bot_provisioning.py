"""Offline contracts for platform tenant database and bot provisioning."""
from __future__ import annotations

import asyncio
import os
from functools import wraps
from uuid import uuid4

import httpx
from fastapi import FastAPI

os.environ.setdefault("JWT_SECRET", "offline-test-secret-at-least-32-characters")


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def _app():
    from v2_platform_routes import router

    app = FastAPI()
    app.include_router(router)
    return app


def _token_for(admin_id: str) -> str:
    from auth import create_access_token

    return create_access_token(admin_id, f"{admin_id}@example.test")


async def _request(method: str, path: str, *, json=None, headers=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://offline"
    ) as client:
        return await client.request(method, path, json=json, headers=headers)


async def _seed_platform_admin(admin_id: str) -> dict[str, str]:
    from db import db

    await db.admins.delete_many({})
    await db.admins.insert_one(
        {
            "_id": admin_id,
            "email": f"{admin_id}@example.test",
            "role": "admin",
            "platform_role": "platform_admin",
        }
    )
    return {"Authorization": f"Bearer {_token_for(admin_id)}"}


async def _create_tenant(headers: dict[str, str], slug: str) -> dict:
    response = await _request(
        "POST",
        "/api/v2/platform/tenants",
        json={"slug": slug, "name": "Original name"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _cleanup_tenants(*slugs: str) -> None:
    """Remove test tenants so other test modules see a pristine tenant list."""
    from db import db
    from tenant_db import resolve_platform_database_name

    await db.client[resolve_platform_database_name(os.environ)]["tenants"].delete_many(
        {"slug": {"$in": list(slugs)}}
    )


@async_test
async def test_provision_initializes_tenant_schema_not_just_database_handle():
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    tenant = await _create_tenant(headers, "schema-platform-test")

    try:
        response = await _request(
            "POST", f"/api/v2/platform/tenants/{tenant['id']}/provision", headers=headers
        )

        assert response.status_code == 200, response.text
        from db import db

        tenant_db = db.client[tenant["database_name"]]
        assert await tenant_db.settings.find_one({"_id": "main"}) is not None
        assert "active_created_at" in await tenant_db.products.index_information()
    finally:
        await _cleanup_tenants("schema-platform-test")


@async_test
async def test_validate_bot_token_uses_injected_get_me_without_returning_token(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    tenant = await _create_tenant(headers, "validate-bot-test")
    supplied_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE_12345"

    import v2_platform_routes

    received_tokens = []

    async def fake_validate(token: str) -> dict:
        received_tokens.append(token)
        return {"id": 98765, "is_bot": True, "first_name": "Acme Bot", "username": "acme_bot"}

    monkeypatch.setattr(v2_platform_routes, "validate_telegram_bot_token", fake_validate)
    try:
        response = await _request(
            "POST",
            f"/api/v2/platform/tenants/{tenant['id']}/bot/validate",
            json={"telegram_token": supplied_token},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert received_tokens == [supplied_token]
        assert response.json() == {
            "telegram_bot_id": 98765,
            "username": "acme_bot",
            "bot_name": "Acme Bot",
            "default_brand_name": "Acme Bot",
        }
        assert supplied_token not in response.text
    finally:
        await _cleanup_tenants("validate-bot-test")


@async_test
async def test_provision_bot_config_encrypts_token_and_brand_is_editable(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    tenant = await _create_tenant(headers, "bot-config-test")
    supplied_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE_12345"

    import v2_platform_routes

    async def fake_validate(_: str) -> dict:
        return {"id": 98765, "is_bot": True, "first_name": "Acme Bot", "username": "acme_bot"}

    monkeypatch.setattr(v2_platform_routes, "validate_telegram_bot_token", fake_validate)
    monkeypatch.setattr(v2_platform_routes, "encrypt_telegram_bot_token", lambda _: "encrypted-token")

    try:
        configured = await _request(
            "PUT",
            f"/api/v2/platform/tenants/{tenant['id']}/bot-config",
            json={"telegram_token": supplied_token},
            headers=headers,
        )

        assert configured.status_code == 200, configured.text
        body = configured.json()
        assert body["telegram_bot_id"] == 98765
        assert body["username"] == "acme_bot"
        assert body["bot_name"] == "Acme Bot"
        assert body["brand_name"] == "Acme Bot"
        # New provisioning status is tracked on every fresh token attach.
        prov = body["bot_provisioning"]
        assert prov["status"] == "provisioning"
        assert prov["estimated_minutes"] == 2
        assert "started_at" in prov
        assert supplied_token not in configured.text

        edited = await _request(
            "PATCH",
            f"/api/v2/platform/tenants/{tenant['id']}/bot-config",
            json={"brand_name": "Editable Brand"},
            headers=headers,
        )

        assert edited.status_code == 200, edited.text
        assert edited.json()["brand_name"] == "Editable Brand"

        from dependencies import get_tenant_registry

        stored = await get_tenant_registry().get_tenant("bot-config-test")
        assert stored is not None
        bot_config = stored["metadata"]["bot_config"]
        assert bot_config["token_encrypted"] == "encrypted-token"
        assert supplied_token not in repr(bot_config)
    finally:
        await _cleanup_tenants("bot-config-test")


@async_test
async def test_double_submit_during_provisioning_returns_409(monkeypatch):
    """Second token submit while provisioning is in-flight must be rejected."""
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    tenant = await _create_tenant(headers, "double-submit-test")
    supplied_token = "222222222:BBFakeFakeFakeFakeFakeFakeFakeFake34"

    import v2_platform_routes

    async def fake_validate(_: str) -> dict:
        return {"id": 22222, "is_bot": True, "first_name": "Double Bot", "username": "double_bot"}

    monkeypatch.setattr(v2_platform_routes, "validate_telegram_bot_token", fake_validate)
    monkeypatch.setattr(v2_platform_routes, "encrypt_telegram_bot_token", lambda _: "encrypted-token")
    # Silence Telegram fan-out in tests.
    async def fake_notify(*args, **kwargs):
        return None
    monkeypatch.setattr(v2_platform_routes, "_notify_provisioning", fake_notify)

    try:
        first = await _request(
            "PUT",
            f"/api/v2/platform/tenants/{tenant['id']}/bot-config",
            json={"telegram_token": supplied_token, "admin_ids": [424242]},
            headers=headers,
        )
        assert first.status_code == 200, first.text

        second = await _request(
            "PUT",
            f"/api/v2/platform/tenants/{tenant['id']}/bot-config",
            json={"telegram_token": "333333333:CCFakeFakeFakeFakeFakeFakeFakeFake56"},
            headers=headers,
        )
        assert second.status_code == 409, second.text
        assert "proses pemasangan" in second.text
    finally:
        # Clean up so other tests see a pristine tenant list.
        from tenant_db import resolve_platform_database_name
        from db import db
        await db.client[resolve_platform_database_name(os.environ)]["demo_usage"].delete_many({"telegram_id": 424242})
        await _cleanup_tenants("double-submit-test")


@async_test
async def test_demo_once_rule_rejects_second_demo_for_same_telegram_id(monkeypatch):
    """One Telegram ID may only ever use demo one time."""
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)

    import v2_platform_routes

    async def fake_validate(_: str) -> dict:
        return {"id": 33333, "is_bot": True, "first_name": "Demo Bot", "username": "demo_bot"}

    monkeypatch.setattr(v2_platform_routes, "validate_telegram_bot_token", fake_validate)
    monkeypatch.setattr(v2_platform_routes, "encrypt_telegram_bot_token", lambda _: "encrypted-token")
    async def fake_notify(*args, **kwargs):
        return None
    monkeypatch.setattr(v2_platform_routes, "_notify_provisioning", fake_notify)

    # First demo tenant for this Telegram user: allowed (plan defaults to demo).
    tenant1 = await _create_tenant(headers, "demo-once-first")
    try:
        first = await _request(
            "PUT",
            f"/api/v2/platform/tenants/{tenant1['id']}/bot-config",
            json={"telegram_token": "444444444:DDFakeFakeFakeFakeFakeFakeFakeFake78", "admin_ids": [777001]},
            headers=headers,
        )
        assert first.status_code == 200, first.text

        # Second demo tenant for the SAME Telegram ID: rejected.
        tenant2 = await _create_tenant(headers, "demo-once-second")
        second = await _request(
            "PUT",
            f"/api/v2/platform/tenants/{tenant2['id']}/bot-config",
            json={"telegram_token": "555555555:EEFakeFakeFakeFakeFakeFakeFakeFake90", "admin_ids": [777001]},
            headers=headers,
        )
        assert second.status_code == 422, second.text
        assert "demo 1x" in second.text or "demo satu kali" in second.text
    finally:
        # Clean up so other tests see a pristine tenant list.
        from tenant_db import resolve_platform_database_name
        from db import db
        await db.client[resolve_platform_database_name(os.environ)]["demo_usage"].delete_many({"telegram_id": 777001})
        await _cleanup_tenants("demo-once-first", "demo-once-second")
