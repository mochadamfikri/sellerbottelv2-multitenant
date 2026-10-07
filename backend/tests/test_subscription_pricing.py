"""Tests for configurable subscription pricing (no hard-coded prices)."""
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


async def _seed_admin(admin_id: str, **values) -> None:
    from db import db

    await db.admins.delete_many({})
    await db.admins.insert_one({"_id": admin_id, "email": f"{admin_id}@example.test", **values})


def _admin_headers(admin_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(admin_id)}"}


async def _platform_admin_headers() -> dict[str, str]:
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="platform_admin")
    return _admin_headers(admin_id)


async def _clear_pricing() -> None:
    from db import db

    await db["subscription_pricing_config"].delete_many({})


@async_test
async def test_pricing_requires_authentication():
    response = await _request("GET", "/api/v2/platform/pricing")

    assert response.status_code == 401


@async_test
async def test_pricing_rejects_non_platform_admin():
    admin_id = str(uuid4())
    await _seed_admin(admin_id, role="admin", platform_role="tenant_admin")

    response = await _request(
        "GET", "/api/v2/platform/pricing", headers=_admin_headers(admin_id)
    )

    assert response.status_code == 403


@async_test
async def test_pricing_defaults_are_empty_with_no_invented_prices():
    from subscription_pricing import get_mode_price, get_subscription_pricing

    await _clear_pricing()
    headers = await _platform_admin_headers()

    response = await _request("GET", "/api/v2/platform/pricing", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["modes"] == {}
    assert body["reminder_schedule_days"] is None
    assert body["grace_period_days"] is None
    assert body["updated_at"] is None

    config = await get_subscription_pricing()
    assert config.modes == {}
    assert config.reminder_schedule_days is None
    assert config.grace_period_days is None
    for mode in ("demo", "monthly", "yearly", "lifetime"):
        price, _ = await get_mode_price(mode)
        assert price is None


@async_test
async def test_platform_admin_can_configure_pricing_and_accessor_reads_it():
    from subscription_pricing import get_mode_price, get_subscription_pricing

    await _clear_pricing()
    headers = await _platform_admin_headers()

    updated = await _request(
        "PUT",
        "/api/v2/platform/pricing",
        json={
            "modes": {
                "monthly": {
                    "price": 99000,
                    "currency": "IDR",
                    "enabled": True,
                    "feature_limits": {"max_products": 500},
                },
                "yearly": {"price": 990000, "currency": "IDR"},
            },
            "reminder_schedule_days": [7, 3, 1],
            "grace_period_days": 3,
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["modes"]["monthly"]["price"] == 99000
    assert body["modes"]["monthly"]["feature_limits"] == {"max_products": 500}
    assert body["modes"]["yearly"]["price"] == 990000
    assert body["reminder_schedule_days"] == [7, 3, 1]
    assert body["grace_period_days"] == 3
    assert body["updated_at"] is not None

    fetched = await _request("GET", "/api/v2/platform/pricing", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["modes"]["monthly"]["price"] == 99000

    config = await get_subscription_pricing()
    assert config.modes["monthly"].price == 99000
    assert config.grace_period_days == 3
    price, currency = await get_mode_price("monthly")
    assert (price, currency) == (99000, "IDR")
    demo_price, _ = await get_mode_price("demo")
    assert demo_price is None


@async_test
async def test_pricing_rejects_unknown_mode():
    await _clear_pricing()
    headers = await _platform_admin_headers()

    response = await _request(
        "PUT",
        "/api/v2/platform/pricing",
        json={"modes": {"quarterly": {"price": 100}}},
        headers=headers,
    )

    assert response.status_code == 422


@async_test
async def test_pricing_rejects_negative_price():
    await _clear_pricing()
    headers = await _platform_admin_headers()

    response = await _request(
        "PUT",
        "/api/v2/platform/pricing",
        json={"modes": {"monthly": {"price": -1}}},
        headers=headers,
    )

    assert response.status_code == 422


@async_test
async def test_disabled_mode_is_not_offered():
    from subscription_pricing import get_mode_price

    await _clear_pricing()
    headers = await _platform_admin_headers()

    updated = await _request(
        "PUT",
        "/api/v2/platform/pricing",
        json={"modes": {"demo": {"price": 0, "enabled": False}}},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text

    price, _ = await get_mode_price("demo")
    assert price is None


@async_test
async def test_mode_names_are_case_insensitive():
    from subscription_pricing import get_mode_price

    await _clear_pricing()
    headers = await _platform_admin_headers()

    updated = await _request(
        "PUT",
        "/api/v2/platform/pricing",
        json={"modes": {"MONTHLY": {"price": 50000}}},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["modes"]["monthly"]["price"] == 50000

    price, _ = await get_mode_price("Monthly")
    assert price == 50000
