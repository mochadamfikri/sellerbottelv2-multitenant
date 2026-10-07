"""Offline contracts for the V2 customer config panel.

Covers: OTP register/verify/login flow, unverified-login rejection, bot token
encryption round-trip via the existing reseller seam, tenant isolation
(A credentials never reach B data), and access separation (a customer login
grants nothing on platform routes).
"""
from __future__ import annotations

import asyncio
import os
from functools import wraps
from uuid import uuid4

import httpx
from fastapi import FastAPI

os.environ.setdefault("JWT_SECRET", "offline-test-secret-at-least-32-characters")

from cryptography.fernet import Fernet

os.environ.setdefault("INVENTORY_ENCRYPTION_KEY", Fernet.generate_key().decode())


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


_CREATED_TENANT_SLUGS: list[str] = []


async def _cleanup_created_tenants() -> None:
    """Remove tenants created by this module so later test files see a clean registry."""
    if not _CREATED_TENANT_SLUGS:
        return
    from db import db
    from dependencies import get_tenant_registry

    registry = get_tenant_registry()
    for slug in _CREATED_TENANT_SLUGS:
        tenant = await registry.get_tenant(slug)
        if tenant is None:
            continue
        tid = str(tenant["_id"])
        await registry.collection.delete_one({"_id": tenant["_id"]})
        await db.customer_accounts.delete_many({"tenant_id": tid})
        await db.customer_account_otps.delete_many({"tenant_id": tid})
    _CREATED_TENANT_SLUGS.clear()


def isolated_test(function):
    """async_test + tenant cleanup: this module must not pollute the shared mock DB."""

    @wraps(function)
    async def _run(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        finally:
            await _cleanup_created_tenants()

    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(_run(*args, **kwargs))

    return wrapper


def _app():
    from v2_platform_routes import router as platform_router
    from v2_customer_config_routes import (
        customer_router,
        platform_router as customer_config_platform_router,
    )

    app = FastAPI()
    app.include_router(platform_router)
    app.include_router(customer_config_platform_router)
    app.include_router(customer_router)
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


async def _create_active_tenant(headers: dict[str, str], slug: str) -> dict:
    response = await _request(
        "POST", "/api/v2/platform/tenants", json={"slug": slug, "name": slug}, headers=headers
    )
    assert response.status_code == 201, response.text
    tenant = response.json()
    _CREATED_TENANT_SLUGS.append(slug)
    activated = await _request(
        "PATCH",
        f"/api/v2/platform/tenants/{tenant['id']}/status",
        json={"status": "active"},
        headers=headers,
    )
    assert activated.status_code == 200, activated.text
    return tenant


async def _capture_otp(monkeypatch):
    import v2_customer_config_routes

    sent: list[tuple[str, str, str]] = []

    async def fake_send(email: str, code: str, purpose: str):
        sent.append((email, code, purpose))
        return {"dev_logged": False}

    monkeypatch.setattr(v2_customer_config_routes, "send_otp_email", fake_send)
    return sent


async def _register_customer(slug: str, username: str, email: str, password: str = "s3cret-pass"):
    response = await _request(
        "POST",
        f"/api/v2/customer/{slug}/register",
        json={"username": username, "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


@isolated_test
async def test_full_otp_flow_register_verify_login(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    await _create_active_tenant(headers, "otp-flow-tenant")
    sent = await _capture_otp(monkeypatch)

    await _register_customer("otp-flow-tenant", "budi", "budi@example.test")

    requested = await _request(
        "POST", "/api/v2/customer/otp-flow-tenant/otp/request", json={"email": "budi@example.test"}
    )
    assert requested.status_code == 200, requested.text
    assert len(sent) == 1
    _, code, purpose = sent[0]
    assert purpose == "verify_email" and len(code) == 6

    verified = await _request(
        "POST",
        "/api/v2/customer/otp-flow-tenant/otp/verify",
        json={"email": "budi@example.test", "code": code},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["email_verified"] is True

    # OTP is single-use: verifying again must fail.
    again = await _request(
        "POST",
        "/api/v2/customer/otp-flow-tenant/otp/verify",
        json={"email": "budi@example.test", "code": code},
    )
    assert again.status_code == 404, again.text

    logged_in = await _request(
        "POST",
        "/api/v2/customer/otp-flow-tenant/login",
        json={"identifier": "budi@example.test", "password": "s3cret-pass"},
    )
    assert logged_in.status_code == 200, logged_in.text
    token = logged_in.json()["access_token"]

    me = await _request(
        "GET",
        "/api/v2/customer/otp-flow-tenant/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "budi@example.test"
    assert "password_hash" not in me.text


@isolated_test
async def test_unverified_login_rejected_until_otp_verified(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    await _create_active_tenant(headers, "unverified-tenant")
    sent = await _capture_otp(monkeypatch)

    await _register_customer("unverified-tenant", "siti", "siti@example.test")
    await _request(
        "POST",
        "/api/v2/customer/unverified-tenant/otp/request",
        json={"email": "siti@example.test"},
    )
    assert len(sent) == 1

    denied = await _request(
        "POST",
        "/api/v2/customer/unverified-tenant/login",
        json={"identifier": "siti", "password": "s3cret-pass"},
    )
    assert denied.status_code == 403, denied.text

    await _request(
        "POST",
        "/api/v2/customer/unverified-tenant/otp/verify",
        json={"email": "siti@example.test", "code": sent[0][1]},
    )
    allowed = await _request(
        "POST",
        "/api/v2/customer/unverified-tenant/login",
        json={"identifier": "siti", "password": "s3cret-pass"},
    )
    assert allowed.status_code == 200, allowed.text


@isolated_test
async def test_bot_token_encrypts_and_decrypts_round_trip(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    tenant = await _create_active_tenant(headers, "roundtrip-tenant")
    supplied_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE_12345"

    import v2_customer_config_routes

    async def fake_validate(_: str) -> dict:
        return {"id": 4242, "is_bot": True, "first_name": "Toko Bot", "username": "toko_bot"}

    monkeypatch.setattr(v2_customer_config_routes, "validate_telegram_bot_token", fake_validate)

    configured = await _request(
        "PUT",
        f"/api/v2/platform/tenants/{tenant['id']}/customer-config",
        json={
            "telegram_token": supplied_token,
            "bot_username": "toko_bot",
            "owner_telegram_user_id": 777000111,
            "owner_telegram_username": "pemilik",
            "domain_choice": {"mode": "owner_subdomain", "hostname": "toko.idseconnect.my.id"},
        },
        headers=headers,
    )
    assert configured.status_code == 200, configured.text
    assert supplied_token not in configured.text
    body = configured.json()
    assert body["telegram_bot_id"] == 4242
    assert body["bot_username"] == "toko_bot"
    assert body["owner_telegram_user_id"] == 777000111
    assert body["owner_telegram_username"] == "pemilik"
    assert body["domain_choice"] == {"mode": "owner_subdomain", "hostname": "toko.idseconnect.my.id"}

    from dependencies import get_tenant_registry
    from reseller_service import decrypt_token

    stored = await get_tenant_registry().get_tenant("roundtrip-tenant")
    assert stored is not None
    bot_config = stored["metadata"]["bot_config"]
    assert supplied_token not in repr(bot_config)
    # Real Fernet round-trip through the shared reseller seam.
    assert decrypt_token(bot_config) == supplied_token

    fetched = await _request(
        "GET", f"/api/v2/platform/tenants/{tenant['id']}/customer-config", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert supplied_token not in fetched.text


@isolated_test
async def test_bot_username_mismatch_with_token_rejected(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    tenant = await _create_active_tenant(headers, "mismatch-tenant")

    import v2_customer_config_routes

    async def fake_validate(_: str) -> dict:
        return {"id": 99, "is_bot": True, "first_name": "Real Bot", "username": "real_bot"}

    monkeypatch.setattr(v2_customer_config_routes, "validate_telegram_bot_token", fake_validate)

    response = await _request(
        "PUT",
        f"/api/v2/platform/tenants/{tenant['id']}/customer-config",
        json={"telegram_token": "123456:abcdefghijklmnopqrstuvwxyzABCDE_12345", "bot_username": "impostor_bot"},
        headers=headers,
    )
    assert response.status_code == 422, response.text


@isolated_test
async def test_tenant_isolation_a_credentials_never_reach_b(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    await _create_active_tenant(headers, "tenant-a")
    await _create_active_tenant(headers, "tenant-b")
    sent = await _capture_otp(monkeypatch)

    await _register_customer("tenant-a", "agus", "agus@example.test")
    await _request(
        "POST", "/api/v2/customer/tenant-a/otp/request", json={"email": "agus@example.test"}
    )
    await _request(
        "POST",
        "/api/v2/customer/tenant-a/otp/verify",
        json={"email": "agus@example.test", "code": sent[0][1]},
    )
    logged_in = await _request(
        "POST",
        "/api/v2/customer/tenant-a/login",
        json={"identifier": "agus@example.test", "password": "s3cret-pass"},
    )
    assert logged_in.status_code == 200, logged_in.text
    token_a = logged_in.json()["access_token"]

    # Same credentials under tenant B: no such account.
    login_b = await _request(
        "POST",
        "/api/v2/customer/tenant-b/login",
        json={"identifier": "agus@example.test", "password": "s3cret-pass"},
    )
    assert login_b.status_code == 401, login_b.text

    # Tenant A token on tenant B routes: rejected.
    me_b = await _request(
        "GET",
        "/api/v2/customer/tenant-b/me",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert me_b.status_code == 401, me_b.text

    # Tenant A email unknown to tenant B's OTP flow.
    otp_b = await _request(
        "POST", "/api/v2/customer/tenant-b/otp/request", json={"email": "agus@example.test"}
    )
    assert otp_b.status_code == 404, otp_b.text

    # Tenant A token still works on tenant A.
    me_a = await _request(
        "GET",
        "/api/v2/customer/tenant-a/me",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert me_a.status_code == 200, me_a.text


@isolated_test
async def test_customer_token_grants_nothing_on_platform_routes(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    await _create_active_tenant(headers, "separation-tenant")
    sent = await _capture_otp(monkeypatch)

    await _register_customer("separation-tenant", "rani", "rani@example.test")
    await _request(
        "POST", "/api/v2/customer/separation-tenant/otp/request", json={"email": "rani@example.test"}
    )
    await _request(
        "POST",
        "/api/v2/customer/separation-tenant/otp/verify",
        json={"email": "rani@example.test", "code": sent[0][1]},
    )
    logged_in = await _request(
        "POST",
        "/api/v2/customer/separation-tenant/login",
        json={"identifier": "rani", "password": "s3cret-pass"},
    )
    customer_token = logged_in.json()["access_token"]

    platform = await _request(
        "GET",
        "/api/v2/platform/tenants",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert platform.status_code in (401, 403), platform.text


@isolated_test
async def test_otp_attempt_limit_locks_code(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    await _create_active_tenant(headers, "attempt-tenant")
    sent = await _capture_otp(monkeypatch)

    await _register_customer("attempt-tenant", "dedi", "dedi@example.test")
    await _request(
        "POST", "/api/v2/customer/attempt-tenant/otp/request", json={"email": "dedi@example.test"}
    )
    real_code = sent[0][1]
    assert real_code != "000000"

    for _ in range(5):
        wrong = await _request(
            "POST",
            "/api/v2/customer/attempt-tenant/otp/verify",
            json={"email": "dedi@example.test", "code": "000000"},
        )
        assert wrong.status_code == 401, wrong.text

    locked = await _request(
        "POST",
        "/api/v2/customer/attempt-tenant/otp/verify",
        json={"email": "dedi@example.test", "code": real_code},
    )
    assert locked.status_code == 429, locked.text


@isolated_test
async def test_expired_otp_rejected(monkeypatch):
    from datetime import datetime, timezone

    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    await _create_active_tenant(headers, "expiry-tenant")
    sent = await _capture_otp(monkeypatch)

    await _register_customer("expiry-tenant", "lina", "lina@example.test")
    await _request(
        "POST", "/api/v2/customer/expiry-tenant/otp/request", json={"email": "lina@example.test"}
    )

    from db import db

    past = datetime(2000, 1, 1, tzinfo=timezone.utc)
    await db.customer_account_otps.update_many({}, {"$set": {"expires_at": past}})

    expired = await _request(
        "POST",
        "/api/v2/customer/expiry-tenant/otp/verify",
        json={"email": "lina@example.test", "code": sent[0][1]},
    )
    assert expired.status_code == 410, expired.text


@isolated_test
async def test_password_reset_flow_via_verified_email(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    await _create_active_tenant(headers, "reset-tenant")
    sent = await _capture_otp(monkeypatch)

    await _register_customer("reset-tenant", "eko", "eko@example.test")
    await _request(
        "POST", "/api/v2/customer/reset-tenant/otp/request", json={"email": "eko@example.test"}
    )
    await _request(
        "POST",
        "/api/v2/customer/reset-tenant/otp/verify",
        json={"email": "eko@example.test", "code": sent[0][1]},
    )

    requested = await _request(
        "POST",
        "/api/v2/customer/reset-tenant/password-reset/request",
        json={"email": "eko@example.test"},
    )
    assert requested.status_code == 200, requested.text
    reset_code = sent[1][1]
    assert sent[1][2] == "password_reset"

    confirmed = await _request(
        "POST",
        "/api/v2/customer/reset-tenant/password-reset/confirm",
        json={"email": "eko@example.test", "code": reset_code, "new_password": "n3w-s3cret-pass"},
    )
    assert confirmed.status_code == 200, confirmed.text

    old_login = await _request(
        "POST",
        "/api/v2/customer/reset-tenant/login",
        json={"identifier": "eko", "password": "s3cret-pass"},
    )
    assert old_login.status_code == 401, old_login.text

    new_login = await _request(
        "POST",
        "/api/v2/customer/reset-tenant/login",
        json={"identifier": "eko", "password": "n3w-s3cret-pass"},
    )
    assert new_login.status_code == 200, new_login.text


@isolated_test
async def test_password_reset_requires_verified_email(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    await _create_active_tenant(headers, "reset-unverified-tenant")
    await _capture_otp(monkeypatch)

    await _register_customer("reset-unverified-tenant", "gilang", "gilang@example.test")
    denied = await _request(
        "POST",
        "/api/v2/customer/reset-unverified-tenant/password-reset/request",
        json={"email": "gilang@example.test"},
    )
    assert denied.status_code == 403, denied.text


@isolated_test
async def test_platform_admin_can_precreate_customer_account(monkeypatch):
    admin_id = str(uuid4())
    headers = await _seed_platform_admin(admin_id)
    tenant = await _create_active_tenant(headers, "precreate-tenant")
    sent = await _capture_otp(monkeypatch)

    created = await _request(
        "POST",
        f"/api/v2/platform/tenants/{tenant['id']}/customer-accounts",
        json={"username": "premade", "email": "premade@example.test", "password": "t3mp-pass!"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["verification_required"] is True
    assert "password_hash" not in created.text

    # Still unverified: login rejected.
    denied = await _request(
        "POST",
        "/api/v2/customer/precreate-tenant/login",
        json={"identifier": "premade", "password": "t3mp-pass!"},
    )
    assert denied.status_code == 403, denied.text

    # Customer completes OTP verification themselves, then logs in.
    await _request(
        "POST",
        "/api/v2/customer/precreate-tenant/otp/request",
        json={"email": "premade@example.test"},
    )
    verified = await _request(
        "POST",
        "/api/v2/customer/precreate-tenant/otp/verify",
        json={"email": "premade@example.test", "code": sent[0][1]},
    )
    assert verified.status_code == 200, verified.text
    logged_in = await _request(
        "POST",
        "/api/v2/customer/precreate-tenant/login",
        json={"identifier": "premade", "password": "t3mp-pass!"},
    )
    assert logged_in.status_code == 200, logged_in.text
