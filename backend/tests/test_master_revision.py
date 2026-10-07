"""Synthetic fixtures only; run with the network-disabled offline runner."""
import asyncio
from datetime import datetime, timedelta, timezone
import httpx
import jwt
import pytest
from fastapi import FastAPI
import storefront_routes
import admin_user_routes
from auth import get_current_admin, get_jwt_secret
from db import db


@pytest.fixture(autouse=True)
def database():
    async def reset():
        for name in ("store_customers", "bot_users", "purchases", "deposits", "tg_accounts", "settings"):
            await db[name].delete_many({})
        await db.settings.insert_one({"_id": "main", "stats_reset_at": "2026-01-01T00:00:00Z"})
        await db.bot_users.insert_many([
            {"_id": "tg1", "telegram_id": 1, "first_name": "Telegram Linked", "username": "linked_handle", "balance_idr": 0, "balance_usd": 20, "state_data": {"secret": "hidden"}},
            {"_id": "tg2", "telegram_id": 2, "first_name": "Telegram Only", "balance_idr": 20000, "balance_usd": 4},
        ])
        await db.store_customers.insert_many([
            {"_id": "linked", "email": "linked@example.test", "telegram_id": 1, "balance_idr": 9999, "balance_usd": 0, "password_hash": "secret", "session_version": 3, "wallet_merge": {"status": "pending"}},
            {"_id": "web", "email": "web@example.test", "balance_idr": 90000, "balance_usd": 3, "password_hash": "secret", "session_version": 0},
        ])
        await db.purchases.insert_many([
            {"_id": "both", "customer_id": "linked", "user_tid": 1, "total": 15000, "status": "delivered"},
            {"_id": "old-web", "customer_id": "linked", "total": 20000, "status": "delivered"},
            {"_id": "old-tg", "user_tid": 1, "total": 30000, "status": "delivered"},
            {"_id": "web-order", "customer_id": "web", "total": 40000, "status": "paid"},
            {"_id": "tg-order", "user_tid": 2, "total": 50000, "status": "pending_payment"},
        ])
        await db.deposits.insert_one({"_id": "dep", "user_tid": 1, "amount": 123456, "status": "approved"})
    asyncio.run(reset())


def app(admin=False):
    application = FastAPI()
    application.include_router(storefront_routes.router)
    application.include_router(admin_user_routes.router)
    if admin:
        application.dependency_overrides[get_current_admin] = lambda: {"_id": "admin"}
    return application


def cookie(customer="web", version=0):
    return {"customer_access_token": jwt.encode({"sub": customer, "type": "customer", "sv": version, "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, get_jwt_secret(), algorithm="HS256")}


async def snapshot():
    return {name: await db[name].find({}).sort("_id", 1).to_list(None) for name in ("purchases", "deposits", "bot_users", "settings")}


@pytest.mark.parametrize("customer,version", [("web", 0), ("linked", 3)])
def test_profile_preserves_finances_identity_and_other_customer(customer, version):
    async def run():
        before = await db.store_customers.find_one({"_id": customer})
        other = await db.store_customers.find_one({"_id": "web" if customer == "linked" else "linked"})
        finances = await snapshot()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://offline", cookies=cookie(customer, version)) as client:
            response = await client.patch("/api/store/me", json={"display_name": "  Nama   Baru  ", "phone": "+62 812-3456-7890"})
            assert response.status_code == 200, response.text
            assert response.json()["display_name"] == "Nama Baru"
            assert "no-store" in response.headers["cache-control"]
            assert "password_hash" not in response.json()
            assert response.json()["balance_idr"] == (0 if customer == "linked" else 90000)
        after = await db.store_customers.find_one({"_id": customer})
        assert {key: after[key] for key in before} == before
        assert set(after) - set(before) == {"display_name", "phone", "profile_updated_at"}
        assert await db.store_customers.find_one({"_id": other["_id"]}) == other
        assert await snapshot() == finances
    asyncio.run(run())


@pytest.mark.parametrize("extra", [{"balance_idr": 1}, {"email": "other@example.test"}, {"telegram_id": 2}, {"_id": "linked"}, {"session_version": 123}, {"password_hash": "bad"}, {"display_name": "   "}, {"phone": "abc"}])
def test_profile_rejects_privileged_and_invalid_fields(extra):
    async def run():
        before = await db.store_customers.find_one({"_id": "web"})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://offline", cookies=cookie()) as client:
            response = await client.patch("/api/store/me", json={"display_name": "Valid name", **extra})
            assert response.status_code == 422, response.text
        assert await db.store_customers.find_one({"_id": "web"}) == before
    asyncio.run(run())


def test_authentication_and_session_version_required():
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://offline") as client:
            assert (await client.patch("/api/store/me", json={"display_name": "Name"})).status_code == 401
            assert (await client.get("/api/admin/user-directory")).status_code == 401
            client.cookies.update(cookie("linked", 2))
            assert (await client.patch("/api/store/me", json={"display_name": "Name"})).status_code == 401
    asyncio.run(run())


def test_directory_sources_search_paging_unique_orders_and_no_writes():
    async def run():
        before = await snapshot()
        customers = await db.store_customers.find({}).to_list(None)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app(admin=True)), base_url="http://offline") as client:
            response = await client.get("/api/admin/user-directory")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["total"] == 3
            assert data["source_counts"] == {"all": 3, "telegram": 1, "web": 1, "linked": 1}
            linked = next(row for row in data["items"] if row["source"] == "linked")
            assert linked["purchase_count"] == 3
            assert linked["balance_idr"] == 0
            assert "password_hash" not in response.text and "state_data" not in response.text
            for source in ("telegram", "web", "linked"):
                result = (await client.get("/api/admin/user-directory", params={"source": source})).json()
                assert result["total"] == 1 and result["items"][0]["source"] == source
            for search in ("linked@example", "@linked_handle", "Telegram Linked"):
                result = (await client.get("/api/admin/user-directory", params={"search": search})).json()
                assert result["total"] == 1 and result["items"][0]["source"] == "linked"
            paged = (await client.get("/api/admin/user-directory?page=9&page_size=1")).json()
            assert paged["page"] == 3 and paged["pages"] == 3 and len(paged["items"]) == 1
            assert (await client.get("/api/admin/user-directory?source=unknown")).status_code == 422
        assert await snapshot() == before
        assert await db.store_customers.find({}).to_list(None) == customers
    asyncio.run(run())
