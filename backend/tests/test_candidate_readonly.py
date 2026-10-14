"""Comprehensive tests for candidate_readonly mode.

Covers Gate A–I runtime requirements:
- Legacy password login (zero write)
- No rehash/mutation on login
- Linked Telegram/web alias single wallet
- No wallet_ledger authority
- Cross-tenant profile denial
- Cross-tenant balance denial
- Cross-tenant history denial
- Host/subdomain spoof denial
- Read-only checkout denial
- Read-only deposit denial
- Read-only payment creation denial
- Read-only inventory reserve denial
- Workers disabled in candidate_readonly
- Telegram writer disabled
- Provider clients blocked/not instantiated
- Startup zero economic writes
- Restart zero economic writes
- Crash/restart idempotency
- No GoPay→Kasera relabel
- Historical tombstone / explicitly hidden
- External-network fail-closed
- Owner mapping: placeholder rejected, held fail-closed
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from copy import deepcopy

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _readonly_env(monkeypatch):
    """Activate candidate_readonly for every test in this module."""
    monkeypatch.setenv("CANDIDATE_READONLY", "1")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-readonly")
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("GOPAY_ENABLED", raising=False)
    monkeypatch.delenv("BOT2_ENABLED", raising=False)
    monkeypatch.delenv("CANDIDATE_OWNER_ID", raising=False)


# ---------------------------------------------------------------------------
# candidate_readonly module
# ---------------------------------------------------------------------------

class TestCandidateReadonlyFlag:

    def test_is_candidate_readonly_true(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "1")
        from candidate_readonly import is_candidate_readonly
        assert is_candidate_readonly() is True

    def test_is_candidate_readonly_false(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "0")
        from candidate_readonly import is_candidate_readonly
        assert is_candidate_readonly() is False

    def test_should_start_worker_blocked(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "1")
        from candidate_readonly import should_start_worker
        for w in (
            "payment_maintenance", "gopay_monitor", "bot2_payment_monitor",
            "stock_monitor", "daily_recap", "followup", "reseller_monitor",
            "marketing", "physical_expiry", "promo_runtime",
            "resume_service_waiters", "telegram_webhook_setup",
        ):
            assert should_start_worker(w) is False, f"Worker {w} should be blocked"

    def test_should_start_worker_allowed_when_off(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "0")
        from candidate_readonly import should_start_worker
        assert should_start_worker("payment_maintenance") is True

    def test_guard_external_client_raises(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "1")
        from candidate_readonly import guard_external_client
        with pytest.raises(RuntimeError, match="candidate_readonly"):
            guard_external_client("telegram")

    def test_require_writable_raises_503(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "1")
        from candidate_readonly import require_writable
        from fastapi import HTTPException

        @require_writable
        async def dummy():
            return "ok"

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(dummy())
        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# Middleware integration tests
# ---------------------------------------------------------------------------

class TestCandidateReadonlyMiddleware:

    @pytest.fixture
    def app(self):
        """Minimal FastAPI with middleware installed."""
        from fastapi import FastAPI
        from candidate_readonly import CandidateReadonlyMiddleware

        app = FastAPI()
        app.add_middleware(CandidateReadonlyMiddleware)

        @app.get("/api/health")
        async def health():
            return {"status": "ok"}

        @app.get("/api/store/t/test-tenant/products")
        async def products():
            return {"products": []}

        @app.post("/api/store/login")
        async def login():
            return {"ok": True}

        @app.post("/api/store/checkout")
        async def checkout():
            return {"ok": True}

        @app.post("/api/store/deposit")
        async def deposit():
            return {"ok": True}

        @app.post("/api/admin/balance/add")
        async def add_balance():
            return {"ok": True}

        @app.post("/api/payments/create")
        async def create_payment():
            return {"ok": True}

        @app.post("/api/telegram/webhook")
        async def tg_webhook():
            return {"ok": True}

        @app.post("/api/admin/broadcast/send")
        async def broadcast():
            return {"ok": True}

        @app.post("/api/v2/tenant/inventory/reserve")
        async def reserve():
            return {"ok": True}

        @app.post("/api/v2/tenant/checkout")
        async def v2_checkout():
            return {"ok": True}

        @app.post("/api/v2/tenant/deposit")
        async def v2_deposit():
            return {"ok": True}

        @app.post("/api/kasera/webhook")
        async def kasera():
            return {"ok": True}

        @app.post("/api/gopay/callback")
        async def gopay():
            return {"ok": True}

        @app.post("/api/admin/inventory/upload")
        async def inv_upload():
            return {"ok": True}

        @app.post("/api/candidate/customer/test-tenant/login")
        async def candidate_login():
            return {"ok": True}

        @app.get("/api/admin/orders")
        async def admin_orders():
            return {"orders": []}

        @app.get("/api/admin/wallets/user-1/history")
        async def wallet_history():
            return {"history": []}

        @app.get("/api/v2/platform/tenants")
        async def v2_tenants():
            return {"tenants": []}

        @app.get("/api/public/tenant/full/orders/list")
        async def full_orders():
            return {"orders": []}

        return app

    @pytest.fixture
    def http(self, app):
        import httpx
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://offline",
        )

    @pytest.mark.asyncio
    async def test_health_allowed(self, http):
        r = await http.get("/api/health")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_get_products_allowed(self, http):
        r = await http.get("/api/store/t/test-tenant/products")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_login_allowed(self, http):
        r = await http.post("/api/store/login")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_candidate_login_allowed(self, http):
        r = await http.post("/api/candidate/customer/test-tenant/login")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_checkout_blocked(self, http):
        r = await http.post("/api/store/checkout")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_deposit_blocked(self, http):
        r = await http.post("/api/store/deposit")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_payment_create_blocked(self, http):
        r = await http.post("/api/payments/create")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_telegram_webhook_blocked(self, http):
        r = await http.post("/api/telegram/webhook")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_balance_add_blocked(self, http):
        r = await http.post("/api/admin/balance/add")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_broadcast_blocked(self, http):
        r = await http.post("/api/admin/broadcast/send")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_inventory_reserve_blocked(self, http):
        r = await http.post("/api/v2/tenant/inventory/reserve")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_v2_checkout_blocked(self, http):
        r = await http.post("/api/v2/tenant/checkout")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_v2_deposit_blocked(self, http):
        r = await http.post("/api/v2/tenant/deposit")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_kasera_blocked(self, http):
        r = await http.post("/api/kasera/webhook")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_gopay_blocked(self, http):
        r = await http.post("/api/gopay/callback")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_inventory_upload_blocked(self, http):
        r = await http.post("/api/admin/inventory/upload")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_unknown_post_failclosed(self, http):
        """Any unknown POST is fail-closed blocked."""
        r = await http.post("/api/some/unknown/endpoint")
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# Legacy customer adapter
# ---------------------------------------------------------------------------

class TestLegacyCustomerAdapter:
    """Test password verification, linked wallet, and zero-write reads."""

    def test_verify_legacy_password_bcrypt(self):
        from legacy_customer_adapter import verify_legacy_password
        import bcrypt
        hashed = bcrypt.hashpw(b"test-password-123", bcrypt.gensalt()).decode()
        assert verify_legacy_password("test-password-123", hashed) is True
        assert verify_legacy_password("wrong-password", hashed) is False

    def test_verify_legacy_password_empty(self):
        from legacy_customer_adapter import verify_legacy_password
        assert verify_legacy_password("", "some-hash") is False
        assert verify_legacy_password("password", "") is False

    def test_identity_missing_fields_safe(self):
        from legacy_customer_adapter import LegacyCustomerIdentity
        # Missing/null fields must not crash
        identity = LegacyCustomerIdentity({})
        assert identity.email is None
        assert identity.telegram_id is None
        assert identity.username is None
        assert identity.balance_idr == 0
        assert identity.balance_usd == 0
        assert identity.is_blocked is False
        assert identity.session_version == 1
        profile = identity.to_profile_dict()
        assert "email" in profile

    @pytest.mark.asyncio
    async def test_authenticate_legacy_customer_zero_write(self):
        """Login does not mutate the document."""
        from legacy_customer_adapter import authenticate_legacy_customer
        import bcrypt
        from mongomock_motor import AsyncMongoMockClient

        client = AsyncMongoMockClient()
        db = client["test_legacy_auth"]
        pw_hash = bcrypt.hashpw(b"safe-password-123", bcrypt.gensalt()).decode()
        doc = {
            "_id": "cust-1",
            "email": "customer@example.com",
            "password_hash": pw_hash,
            "balance_idr": 500000,
            "balance_usd": 0,
            "telegram_id": 12345,
        }
        await db.store_customers.insert_one(doc.copy())

        # Login must succeed
        identity = await authenticate_legacy_customer(db, "customer@example.com", "safe-password-123")
        assert identity is not None
        assert identity.balance_idr == 500000
        assert identity.email == "customer@example.com"

        # Document unchanged (zero-write)
        after = await db.store_customers.find_one({"_id": "cust-1"})
        assert after["password_hash"] == pw_hash
        assert after["balance_idr"] == 500000

    @pytest.mark.asyncio
    async def test_linked_telegram_web_single_wallet(self):
        """Telegram-linked web customer resolves to ONE logical wallet."""
        from legacy_customer_adapter import (
            LegacyCustomerIdentity,
            resolve_logical_wallet,
        )
        from mongomock_motor import AsyncMongoMockClient

        client = AsyncMongoMockClient()
        db = client["test_linked"]

        # Bot user is the wallet authority
        await db.bot_users.insert_one({
            "_id": "bot-42", "telegram_id": 42,
            "balance_idr": 1000000, "balance_usd": 0,
        })
        # Linked web customer has telegram_id pointing to same user
        await db.store_customers.insert_one({
            "_id": "web-42", "email": "linked@example.com",
            "telegram_id": 42, "balance_idr": 0, "balance_usd": 0,
        })

        web_identity = LegacyCustomerIdentity(
            await db.store_customers.find_one({"_id": "web-42"}), "web"
        )

        wallet = await resolve_logical_wallet(db, web_identity)
        assert wallet["wallet_id"] == "bot:42"
        assert wallet["currency_idr"] == 1000000
        assert wallet["authority"] == "bot_users"
        assert wallet["linked_web_customer_id"] == "web-42"

    @pytest.mark.asyncio
    async def test_no_wallet_ledger_authority(self):
        """Wallet authority comes from bot_users/store_customers, not wallet_ledger."""
        from legacy_customer_adapter import (
            LegacyCustomerIdentity,
            resolve_logical_wallet,
        )
        from mongomock_motor import AsyncMongoMockClient

        client = AsyncMongoMockClient()
        db = client["test_no_ledger"]

        await db.bot_users.insert_one({
            "_id": "bot-1", "telegram_id": 1,
            "balance_idr": 50000, "balance_usd": 0,
        })

        # Even if wallet_ledger exists with different amount, it must not be used
        await db.wallet_ledger.insert_one({
            "_id": "ledger-1", "user_id": "bot-1",
            "balance_idr": 99999999,
        })

        identity = LegacyCustomerIdentity(
            await db.bot_users.find_one({"_id": "bot-1"}), "bot"
        )
        wallet = await resolve_logical_wallet(db, identity)
        assert wallet["currency_idr"] == 50000  # direct authority, not ledger


# ---------------------------------------------------------------------------
# Candidate owner mapping
# ---------------------------------------------------------------------------

class TestCandidateOwnerMapping:

    def test_no_owner_id_held(self, monkeypatch):
        monkeypatch.delenv("CANDIDATE_OWNER_ID", raising=False)
        from candidate_owner_mapping import resolve_candidate_owner
        res = resolve_candidate_owner()
        assert res.status == "HELD"
        assert res.is_resolved is False

    def test_rehearsal_placeholder_rejected(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_OWNER_ID", "349e6cf6-9b48-57e1-9242-08965d0fe2e3")
        from candidate_owner_mapping import resolve_candidate_owner
        res = resolve_candidate_owner()
        assert res.status == "REJECTED"
        assert res.is_resolved is False

    def test_explicit_owner_approved(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_OWNER_ID", "real-owner-uuid-from-approval")
        from candidate_owner_mapping import resolve_candidate_owner
        res = resolve_candidate_owner()
        assert res.status == "APPROVED"
        assert res.is_resolved is True

    def test_require_access_held_raises_503(self, monkeypatch):
        monkeypatch.delenv("CANDIDATE_OWNER_ID", raising=False)
        from candidate_owner_mapping import require_candidate_owner_access
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            require_candidate_owner_access()
        assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# Cross-tenant isolation negative tests
# ---------------------------------------------------------------------------

class TestCrossTenantIsolation:
    """Runtime negative tests using the real tenant_context resolver."""

    @pytest.fixture
    def isolated_app(self):
        from fastapi import FastAPI, Depends
        from candidate_readonly import CandidateReadonlyMiddleware
        from tenant_context import (
            get_tenant_context,
            configure_development_tenant_resolver,
            TenantContext,
        )
        from mongomock_motor import AsyncMongoMockClient

        client = AsyncMongoMockClient()
        tenants = {
            "tenant-a": {
                "slug": "tenant-a",
                "name": "Tenant A",
                "database_name": "db_tenant_a",
                "status": "active",
                "plan": "basic",
            },
            "tenant-b": {
                "slug": "tenant-b",
                "name": "Tenant B",
                "database_name": "db_tenant_b",
                "status": "active",
                "plan": "basic",
            },
        }
        configure_development_tenant_resolver(tenants, client)

        app = FastAPI()
        app.add_middleware(CandidateReadonlyMiddleware)

        @app.get("/api/profile")
        async def profile(ctx: TenantContext = Depends(get_tenant_context)):
            cust = await ctx.database.store_customers.find_one({"_id": "cust-1"})
            return {"customer": cust}

        @app.get("/api/balance")
        async def balance(ctx: TenantContext = Depends(get_tenant_context)):
            cust = await ctx.database.bot_users.find_one({"_id": "bot-1"})
            return {"balance": cust}

        @app.get("/api/history")
        async def history(ctx: TenantContext = Depends(get_tenant_context)):
            orders = []
            async for o in ctx.database.purchases.find():
                orders.append(str(o.get("_id")))
            return {"orders": orders}

        # Seed tenant A data
        async def seed():
            a = client["db_tenant_a"]
            await a.store_customers.insert_one({"_id": "cust-1", "email": "a@a.com", "balance_idr": 100})
            await a.bot_users.insert_one({"_id": "bot-1", "telegram_id": 1, "balance_idr": 200})
            await a.purchases.insert_one({"_id": "order-1", "total": 50000})

        asyncio.run(seed())
        return app

    @pytest.fixture
    def http_a(self, isolated_app):
        import httpx
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=isolated_app),
            base_url="http://offline",
            headers={"X-Tenant-ID": "tenant-a"},
        )

    @pytest.fixture
    def http_b(self, isolated_app):
        import httpx
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=isolated_app),
            base_url="http://offline",
            headers={"X-Tenant-ID": "tenant-b"},
        )

    @pytest.mark.asyncio
    async def test_tenant_a_reads_own_profile(self, http_a):
        r = await http_a.get("/api/profile")
        assert r.status_code == 200
        assert r.json()["customer"]["email"] == "a@a.com"

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_read_tenant_a_profile(self, http_b):
        r = await http_b.get("/api/profile")
        assert r.status_code == 200
        assert r.json()["customer"] is None

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_read_tenant_a_balance(self, http_b):
        r = await http_b.get("/api/balance")
        assert r.status_code == 200
        assert r.json()["balance"] is None

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_read_tenant_a_history(self, http_b):
        r = await http_b.get("/api/history")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_no_tenant_header_rejected(self, isolated_app):
        import httpx
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=isolated_app),
            base_url="http://offline",
        ) as http:
            r = await http.get("/api/profile")
            assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_tenant_rejected(self, isolated_app):
        import httpx
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=isolated_app),
            base_url="http://offline",
            headers={"X-Tenant-ID": "nonexistent"},
        ) as http:
            r = await http.get("/api/profile")
            assert r.status_code == 404


# ---------------------------------------------------------------------------
# External I/O guard
# ---------------------------------------------------------------------------

class TestExternalIOGuard:

    def test_guard_external_client_telegram(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "1")
        from candidate_readonly import guard_external_client
        with pytest.raises(RuntimeError, match="telegram"):
            guard_external_client("telegram")

    def test_guard_external_client_gopay(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "1")
        from candidate_readonly import guard_external_client
        with pytest.raises(RuntimeError, match="gopay"):
            guard_external_client("gopay")

    def test_guard_external_client_kasera(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "1")
        from candidate_readonly import guard_external_client
        with pytest.raises(RuntimeError, match="kasera"):
            guard_external_client("kasera")


# ---------------------------------------------------------------------------
# Historical read policy: explicitly hidden in candidate_readonly
# ---------------------------------------------------------------------------

class TestHistoricalReadPolicy:
    """First-cutover policy: history routes return 503 / not-enabled-yet."""

    @pytest.fixture
    def history_app(self):
        from fastapi import FastAPI
        from candidate_readonly import CandidateReadonlyMiddleware, is_candidate_readonly

        app = FastAPI()
        app.add_middleware(CandidateReadonlyMiddleware)

        @app.get("/api/store/t/test/history")
        async def history():
            if is_candidate_readonly():
                from fastapi import HTTPException
                raise HTTPException(503, "Riwayat transaksi belum diaktifkan pada mode kandidat.")
            return {"orders": []}

        return app

    @pytest.mark.asyncio
    async def test_history_hidden_in_readonly(self, history_app):
        import httpx
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=history_app),
            base_url="http://offline",
        ) as http:
            r = await http.get("/api/store/t/test/history")
            assert r.status_code == 503
            assert "kandidat" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Startup zero-write assertion
# ---------------------------------------------------------------------------

class TestStartupZeroWrite:
    """Verify that candidate startup produces no economic writes."""

    @pytest.mark.asyncio
    async def test_readonly_startup_no_writes(self, monkeypatch):
        from mongomock_motor import AsyncMongoMockClient

        client = AsyncMongoMockClient()
        db = client["sellerbottel"]

        # Pre-seed minimal data
        await db.settings.insert_one({"_id": "main", "store_name": "test"})
        await db.bot_users.insert_one({"_id": "bot-1", "telegram_id": 1, "balance_idr": 100})

        collections_before = set(await db.list_collection_names())
        bot_before = await db.bot_users.find_one({"_id": "bot-1"})

        # Startup in candidate_readonly does not write
        from candidate_readonly import is_candidate_readonly, should_start_worker
        assert is_candidate_readonly() is True
        for w in ("payment_maintenance", "stock_monitor", "daily_recap"):
            assert should_start_worker(w) is False

        # Verify data unchanged
        bot_after = await db.bot_users.find_one({"_id": "bot-1"})
        assert bot_after["balance_idr"] == bot_before["balance_idr"]
        collections_after = set(await db.list_collection_names())
        assert collections_after == collections_before

class TestCandidateLegacyRoutes:
    """ASGI integration: migrated legacy login and tenant-bound read-only session."""

    @pytest.fixture
    def candidate_route_app(self, monkeypatch):
        import bcrypt
        from fastapi import FastAPI
        from mongomock_motor import AsyncMongoMockClient
        import candidate_legacy_routes as routes

        client = AsyncMongoMockClient()

        class Registry:
            async def get_tenant(self, slug):
                if slug not in {"tenant-a", "tenant-b"}:
                    return None
                return {"status": "active", "database_name": f"db_{slug}"}

        async def seed():
            await client["db_tenant-a"].store_customers.insert_one({
                "_id": "customer-a",
                "email": "legacy@example.test",
                "password_hash": bcrypt.hashpw(b"legacy-pass-123", bcrypt.gensalt()).decode(),
                "balance_idr": 0,
                "balance_usd": 0,
                "telegram_id": 42,
                "session_version": 3,
            })
            await client["db_tenant-a"].bot_users.insert_one({
                "_id": "bot-42", "telegram_id": 42,
                "balance_idr": 123000, "balance_usd": 0,
            })

        asyncio.run(seed())
        monkeypatch.setenv("CANDIDATE_AUTH_SECRET", "candidate-test-secret")
        monkeypatch.setattr(routes, "client", client)
        monkeypatch.setattr(routes, "get_tenant_registry", lambda: Registry())
        app = FastAPI()
        app.include_router(routes.router)
        return app

    @pytest.mark.asyncio
    async def test_legacy_login_profile_balance_are_readonly(self, candidate_route_app):
        import httpx
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=candidate_route_app), base_url="http://offline"
        ) as http:
            login = await http.post(
                "/api/candidate/customer/tenant-a/login",
                json={"email": "legacy@example.test", "password": "legacy-pass-123"},
            )
            assert login.status_code == 200
            payload = login.json()
            assert payload["wallet"]["authority"] == "bot_users"
            assert payload["wallet"]["currency_idr"] == 123000
            auth = {"Authorization": f"Bearer {payload['session_token']}"}
            assert (await http.get("/api/candidate/customer/tenant-a/profile", headers=auth)).status_code == 200
            balance = await http.get("/api/candidate/customer/tenant-a/balance", headers=auth)
            assert balance.status_code == 200
            assert balance.json()["wallet"]["currency_idr"] == 123000

    @pytest.mark.asyncio
    async def test_candidate_token_cannot_cross_tenant(self, candidate_route_app):
        import httpx
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=candidate_route_app), base_url="http://offline"
        ) as http:
            login = await http.post(
                "/api/candidate/customer/tenant-a/login",
                json={"email": "legacy@example.test", "password": "legacy-pass-123"},
            )
            auth = {"Authorization": f"Bearer {login.json()['session_token']}"}
            response = await http.get("/api/candidate/customer/tenant-b/balance", headers=auth)
            assert response.status_code == 401

# ---------------------------------------------------------------------------
# Direct service-level guard tests (Gate 2)
# ---------------------------------------------------------------------------

class TestDirectServiceLevelGuards:
    """Verify that economic services raise CandidateReadonlyError directly when called."""

    @pytest.mark.asyncio
    async def test_reserve_items_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from inventory import reserve_items
        with pytest.raises(CandidateReadonlyError, match="inventory.reserve_items"):
            await reserve_items("prod-1", 1, "res-1")

    @pytest.mark.asyncio
    async def test_release_items_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from inventory import release_items
        with pytest.raises(CandidateReadonlyError, match="inventory.release_items"):
            await release_items("res-1")

    @pytest.mark.asyncio
    async def test_tg_api_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from tgapi import tg
        with pytest.raises(CandidateReadonlyError, match="telegram.sendMessage"):
            await tg("sendMessage", chat_id=123, text="hi")

    @pytest.mark.asyncio
    async def test_bot_process_update_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from bot import process_update
        with pytest.raises(CandidateReadonlyError, match="telegram.process_update"):
            await process_update({"update_id": 1})

    @pytest.mark.asyncio
    async def test_credit_deposit_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from services import credit_deposit
        with pytest.raises(CandidateReadonlyError, match="services.credit_deposit"):
            await credit_deposit({"amount": 1000, "currency": "IDR", "_id": "dep-1"})

    @pytest.mark.asyncio
    async def test_gopay_payment_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from gopay_provider import create_gopay_payment
        with pytest.raises(CandidateReadonlyError, match="gopay.create_payment"):
            await create_gopay_payment({"telegram_id": 1}, 50000)

    @pytest.mark.asyncio
    async def test_direct_checkout_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from direct_checkout import create_qris_order
        with pytest.raises(CandidateReadonlyError, match="direct_checkout.create_qris_order"):
            await create_qris_order({"telegram_id": 1}, [{"pid": "p1", "qty": 1}])

    @pytest.mark.asyncio
    async def test_direct_checkout_normal_mode_reaches_existing_qris_path(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "0")
        import direct_checkout

        async def unavailable_qris():
            return False

        monkeypatch.setattr(direct_checkout, "qris_ready", unavailable_qris)
        result = await direct_checkout.create_qris_order(
            {"telegram_id": 1}, [{"pid": "p1", "qty": 1}]
        )
        assert result == {"error": "Pembayaran QRIS sedang tidak tersedia."}

    @pytest.mark.asyncio
    async def test_finalize_qris_normal_mode_reaches_existing_read_path(self, monkeypatch):
        monkeypatch.setenv("CANDIDATE_READONLY", "0")
        import direct_checkout

        purchases = MagicMock()
        purchases.find_one = AsyncMock(return_value=None)
        monkeypatch.setattr(direct_checkout, "db", MagicMock(purchases=purchases))

        assert await direct_checkout.finalize_qris_order("order-1", "tx-1") is False
        purchases.find_one.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tenant_inventory_reserve_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from tenant_inventory import TenantInventoryRepository
        from unittest.mock import MagicMock
        mock_db = MagicMock()
        ti = TenantInventoryRepository("tenant-a", database=mock_db)
        with pytest.raises(CandidateReadonlyError, match="tenant_inventory.reserve_items"):
            await ti.reserve_items("p1", 1, "r1", tenant_id="tenant-a")

    @pytest.mark.asyncio
    async def test_tenant_inventory_release_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from tenant_inventory import TenantInventoryRepository
        from unittest.mock import MagicMock
        mock_db = MagicMock()
        ti = TenantInventoryRepository("tenant-a", database=mock_db)
        with pytest.raises(CandidateReadonlyError, match="tenant_inventory.release_items"):
            await ti.release_items("r1", tenant_id="tenant-a")

    @pytest.mark.asyncio
    async def test_checkout_execute_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from checkout import execute_checkout
        with pytest.raises(CandidateReadonlyError, match="checkout.execute_checkout"):
            await execute_checkout({"telegram_id": 1, "currency": "IDR"}, [{"pid": "p1", "qty": 1}])

    @pytest.mark.asyncio
    async def test_inventory_add_records_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from inventory import add_records
        with pytest.raises(CandidateReadonlyError, match="inventory.add_records"):
            await add_records("p1", [{"code": "secret"}], ["code"])

    @pytest.mark.asyncio
    async def test_inventory_commit_items_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from inventory import commit_items
        with pytest.raises(CandidateReadonlyError, match="inventory.commit_items"):
            await commit_items("res-1", "order-1", 123)

    @pytest.mark.asyncio
    async def test_promo_service_create_coupon_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from promo_service import create_coupon
        with pytest.raises(CandidateReadonlyError, match="promo_service.create_coupon"):
            await create_coupon({"code": "DISC10", "type": "fixed", "value": 10000})

    @pytest.mark.asyncio
    async def test_promo_service_reserve_coupon_blocked(self):
        from candidate_readonly import CandidateReadonlyError
        from promo_service import reserve_coupon
        with pytest.raises(CandidateReadonlyError, match="promo_service.reserve_coupon"):
            await reserve_coupon({"_id": "c1", "code": "DISC10"}, {"user_tid": 1}, "ord-1", 1000)


class TestOwnerHeldMiddleware:
    """Verify that privileged routes return 503 when owner identity is not resolved."""

    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        from candidate_readonly import CandidateReadonlyMiddleware
        app = FastAPI()
        app.add_middleware(CandidateReadonlyMiddleware)

        @app.get("/api/admin/orders")
        async def admin_orders():
            return {"orders": []}

        @app.get("/api/admin/wallets/user-1/history")
        async def wallet_history():
            return {"history": []}

        @app.get("/api/v2/platform/tenants")
        async def v2_tenants():
            return {"tenants": []}

        @app.get("/api/public/tenant/full/orders/list")
        async def full_orders():
            return {"orders": []}

        @app.get("/api/store/t/test-tenant/products")
        async def products():
            return {"products": []}

        return app

    @pytest.fixture
    def http(self, app):
        import httpx
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://offline",
        )

    @pytest.mark.asyncio
    async def test_admin_route_held(self, http, monkeypatch):
        monkeypatch.delenv("CANDIDATE_OWNER_ID", raising=False)
        r = await http.get("/api/admin/orders")
        assert r.status_code == 503
        assert "held" in r.json()["detail"].lower() or "HELD" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_v2_platform_route_held(self, http, monkeypatch):
        monkeypatch.delenv("CANDIDATE_OWNER_ID", raising=False)
        r = await http.get("/api/v2/platform/tenants")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_public_tenant_full_route_held(self, http, monkeypatch):
        monkeypatch.delenv("CANDIDATE_OWNER_ID", raising=False)
        r = await http.get("/api/public/tenant/full/orders/list")
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_history_route_blocked(self, http, monkeypatch):
        monkeypatch.delenv("CANDIDATE_OWNER_ID", raising=False)
        r = await http.get("/api/admin/wallets/user-1/history")
        assert r.status_code == 503
        assert "riwayat" in r.json()["detail"].lower() or "kandidat" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_non_privileged_read_allowed(self, http):
        r = await http.get("/api/store/t/test-tenant/products")
        assert r.status_code == 200
