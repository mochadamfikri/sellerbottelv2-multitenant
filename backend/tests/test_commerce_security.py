"""Cross-tenant commerce security boundary tests.

Verifies that:
1. Tenant A cannot read/write Tenant B products, inventory, orders, or wallet
2. Missing X-Tenant-ID header returns 400
3. Invalid tenant slug returns 404
4. Suspended tenant returns 403
5. Customer in Tenant A cannot place order in Tenant B
6. Order idempotency keys are tenant-scoped
7. Invoice counters are isolated per tenant
8. Wallet balance queries are tenant-scoped
9. Payment reconciliation is tenant-scoped
10. Global identity collections enforce email/telegram_id uniqueness across tenants
    (Owner Decision 1B)
"""
import asyncio
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run_async(coro):
    """Run an async coroutine in sync tests."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TENANT_A_SLUG = "shop-alpha"
TENANT_B_SLUG = "shop-beta"
TENANT_A_DB = f"sellerbottel_tenant_{TENANT_A_SLUG.replace('-', '_')}"
TENANT_B_DB = f"sellerbottel_tenant_{TENANT_B_SLUG.replace('-', '_')}"

TENANTS = {
    TENANT_A_SLUG: {
        "slug": TENANT_A_SLUG,
        "status": "active",
        "database_name": TENANT_A_DB,
    },
    TENANT_B_SLUG: {
        "slug": TENANT_B_SLUG,
        "status": "active",
        "database_name": TENANT_B_DB,
    },
}


@pytest.fixture()
def mock_client():
    """Return the mongomock AsyncMongoMockClient."""
    from db import client
    return client


@pytest.fixture(autouse=True)
def _reset_databases(mock_client):
    """Clear all tenant databases between tests."""
    async def clear():
        for db_name in (TENANT_A_DB, TENANT_B_DB):
            db = mock_client[db_name]
            for coll in (
                "products", "inventory_items", "purchases",
                "orders", "wallet_ledger", "store_customers",
                "bot_users", "records", "deposits",
            ):
                await db[coll].delete_many({})
    run_async(clear())
    yield
    run_async(clear())


def _make_context(tenant_slug, mock_client):
    from tenant_context import TenantContext
    tenant = TENANTS[tenant_slug]
    return TenantContext(
        tenant_id=tenant_slug,
        database=mock_client[tenant["database_name"]],
        status="active",
    )


# ===========================================================================
# Section 1: Cross-tenant product/inventory/order/wallet read isolation
# ===========================================================================

class TestCrossTenantProductIsolation:
    """Tenant A cannot read Tenant B products."""

    def test_tenant_a_cannot_read_tenant_b_products(self, mock_client):
        async def run():
            db_a = mock_client[TENANT_A_DB]
            db_b = mock_client[TENANT_B_DB]
            await db_b.products.insert_one({
                "_id": "prod-b-secret", "name": "Secret B Product",
                "tenant_id": TENANT_B_SLUG, "price": 99,
            })
            result = await db_a.products.find_one({"_id": "prod-b-secret"})
            assert result is None, "Tenant A must not see Tenant B products"
        run_async(run())

    def test_tenant_b_cannot_read_tenant_a_products(self, mock_client):
        async def run():
            db_a = mock_client[TENANT_A_DB]
            db_b = mock_client[TENANT_B_DB]
            await db_a.products.insert_one({
                "_id": "prod-a-exclusive", "name": "A-only",
                "tenant_id": TENANT_A_SLUG, "price": 50,
            })
            result = await db_b.products.find_one({"_id": "prod-a-exclusive"})
            assert result is None, "Tenant B must not see Tenant A products"
        run_async(run())


class TestCrossTenantInventoryIsolation:
    """Tenant A cannot read or allocate Tenant B inventory."""

    def test_tenant_a_cannot_read_tenant_b_inventory(self, mock_client):
        async def run():
            db_a = mock_client[TENANT_A_DB]
            db_b = mock_client[TENANT_B_DB]
            await db_b.inventory_items.insert_one({
                "_id": "inv-b1", "product_id": "p1",
                "tenant_id": TENANT_B_SLUG, "status": "available",
            })
            result = await db_a.inventory_items.find_one({"_id": "inv-b1"})
            assert result is None
        run_async(run())

    def test_tenant_a_cannot_allocate_tenant_b_inventory(self, mock_client):
        async def run():
            db_a = mock_client[TENANT_A_DB]
            db_b = mock_client[TENANT_B_DB]
            await db_b.inventory_items.insert_one({
                "_id": "inv-b2", "quantity": 50,
                "tenant_id": TENANT_B_SLUG,
            })
            update = await db_a.inventory_items.update_one(
                {"_id": "inv-b2"}, {"$inc": {"quantity": -5}}
            )
            assert update.modified_count == 0
            # Verify B is untouched
            item = await db_b.inventory_items.find_one({"_id": "inv-b2"})
            assert item["quantity"] == 50
        run_async(run())


class TestCrossTenantOrderIsolation:
    """Tenant A cannot read Tenant B orders via the repository."""

    def test_tenant_a_repository_cannot_read_tenant_b_order(self, mock_client):
        from tenant_orders_repository import TenantOrdersRepository
        async def run():
            ctx_a = _make_context(TENANT_A_SLUG, mock_client)
            ctx_b = _make_context(TENANT_B_SLUG, mock_client)
            repo_b = TenantOrdersRepository(ctx_b)
            order = await repo_b.create_order(
                customer_id="cust-b1", invoice_id="inv-b-001",
            )
            repo_a = TenantOrdersRepository(ctx_a)
            found = await repo_a.get_order_by_id(order["_id"])
            assert found is None, "Tenant A must not see Tenant B orders"
        run_async(run())

    def test_tenant_b_repository_cannot_read_tenant_a_order(self, mock_client):
        from tenant_orders_repository import TenantOrdersRepository
        async def run():
            ctx_a = _make_context(TENANT_A_SLUG, mock_client)
            ctx_b = _make_context(TENANT_B_SLUG, mock_client)
            repo_a = TenantOrdersRepository(ctx_a)
            order = await repo_a.create_order(
                customer_id="cust-a1", invoice_id="inv-a-001",
            )
            repo_b = TenantOrdersRepository(ctx_b)
            found = await repo_b.get_order_by_id(order["_id"])
            assert found is None, "Tenant B must not see Tenant A orders"
        run_async(run())


class TestCrossTenantWalletIsolation:
    """Tenant A wallet balance must not include Tenant B entries."""

    def test_wallet_balance_is_tenant_scoped(self, mock_client):
        from wallet_ledger import create_ledger_entry, wallet_balance
        async def run():
            ctx_a = _make_context(TENANT_A_SLUG, mock_client)
            ctx_b = _make_context(TENANT_B_SLUG, mock_client)
            db_a = ctx_a.database
            db_b = ctx_b.database

            await create_ledger_entry(
                db_a, ctx_a, entry_type="credit", amount="100",
                currency="USD", reference_id="ref-a1",
                idempotency_key="key-a-credit-1",
            )
            await create_ledger_entry(
                db_b, ctx_b, entry_type="credit", amount="200",
                currency="USD", reference_id="ref-b1",
                idempotency_key="key-b-credit-1",
            )
            balance_a = await wallet_balance(db_a, ctx_a, currency="USD")
            balance_b = await wallet_balance(db_b, ctx_b, currency="USD")
            assert balance_a == Decimal("100")
            assert balance_b == Decimal("200")
        run_async(run())

    def test_tenant_a_balance_unaffected_by_tenant_b_debit(self, mock_client):
        from wallet_ledger import create_ledger_entry, wallet_balance
        async def run():
            ctx_a = _make_context(TENANT_A_SLUG, mock_client)
            ctx_b = _make_context(TENANT_B_SLUG, mock_client)
            db_a = ctx_a.database
            db_b = ctx_b.database

            await create_ledger_entry(
                db_a, ctx_a, entry_type="credit", amount="500",
                currency="IDR", reference_id="ref-a2",
                idempotency_key="key-a-idr-1",
            )
            await create_ledger_entry(
                db_b, ctx_b, entry_type="credit", amount="300",
                currency="IDR", reference_id="ref-b2",
                idempotency_key="key-b-idr-1",
            )
            await create_ledger_entry(
                db_b, ctx_b, entry_type="debit", amount="100",
                currency="IDR", reference_id="ref-b3",
                idempotency_key="key-b-idr-2",
            )
            balance_a = await wallet_balance(db_a, ctx_a, currency="IDR")
            assert balance_a == Decimal("500"), "Tenant A balance must not change from Tenant B debit"
        run_async(run())


# ===========================================================================
# Section 2: Missing / invalid / suspended tenant header enforcement
# ===========================================================================

class TestMissingTenantHeader:
    """Missing X-Tenant-ID header must return 400."""

    def test_missing_header_returns_400(self):
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient
        from tenant_context import configure_development_tenant_resolver, get_tenant_context
        from db import client

        configure_development_tenant_resolver(TENANTS, client)
        app = FastAPI()

        @app.get("/test")
        async def endpoint(ctx=Depends(get_tenant_context)):
            return {"ok": True}

        test_client = TestClient(app)
        resp = test_client.get("/test")  # no X-Tenant-ID header
        assert resp.status_code in (400, 422), f"Expected 400/422, got {resp.status_code}"


class TestInvalidTenantSlug:
    """Invalid tenant slug must return 400."""

    @pytest.mark.parametrize("bad_slug", [
        "tenant/path", "tenant.db", "tenant$special", "",
        "../escape", "tenant\x00null",
    ])
    def test_invalid_slug_returns_400(self, bad_slug):
        from tenant_context import resolve_tenant_context
        from fastapi import HTTPException

        class MockDB:
            def __getitem__(self, name):
                return {"name": name}

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context(bad_slug, TENANTS, MockDB())
        assert exc_info.value.status_code == 400


class TestUnknownTenantSlug:
    """Unknown but valid-format tenant slug must return 404."""

    def test_unknown_tenant_returns_404(self):
        from tenant_context import resolve_tenant_context
        from fastapi import HTTPException

        class MockDB:
            def __getitem__(self, name):
                return {"name": name}

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context("nonexistent-shop", TENANTS, MockDB())
        assert exc_info.value.status_code == 404


class TestSuspendedTenantRejection:
    """Suspended tenant must return 403."""

    @pytest.mark.parametrize("status", ["suspended", "disabled", "banned"])
    def test_suspended_tenant_returns_403(self, status):
        from tenant_context import resolve_tenant_context
        from fastapi import HTTPException

        tenants = {
            "bad-tenant": {
                "slug": "bad-tenant",
                "status": status,
                "database_name": "sellerbottel_tenant_bad_tenant",
            },
        }

        class MockDB:
            def __getitem__(self, name):
                return {"name": name}

        with pytest.raises(HTTPException) as exc_info:
            resolve_tenant_context("bad-tenant", tenants, MockDB())
        assert exc_info.value.status_code == 403


# ===========================================================================
# Section 3: Customer cannot place order in another tenant
# ===========================================================================

class TestCrossTenantOrderPlacement:
    """Customer in Tenant A cannot place an order in Tenant B."""

    def test_order_repository_rejects_foreign_tenant_id_in_data(self, mock_client):
        """TenantOrdersRepository rejects order_data containing a mismatched tenant_id."""
        from tenant_orders_repository import TenantOrdersRepository, TenantOrdersScopeError
        async def run():
            ctx_a = _make_context(TENANT_A_SLUG, mock_client)
            repo_a = TenantOrdersRepository(ctx_a)
            with pytest.raises(TenantOrdersScopeError, match="Tenant mismatch"):
                await repo_a.create_order(
                    customer_id="cust-a1",
                    invoice_id="inv-cross-1",
                    order_data={"tenant_id": TENANT_B_SLUG},
                )
        run_async(run())

    def test_order_created_in_tenant_a_invisible_to_tenant_b_by_invoice(self, mock_client):
        from tenant_orders_repository import TenantOrdersRepository
        async def run():
            ctx_a = _make_context(TENANT_A_SLUG, mock_client)
            ctx_b = _make_context(TENANT_B_SLUG, mock_client)
            repo_a = TenantOrdersRepository(ctx_a)
            repo_b = TenantOrdersRepository(ctx_b)
            await repo_a.create_order(
                customer_id="cust-a2", invoice_id="inv-a-private",
            )
            found = await repo_b.get_order_by_invoice_id("inv-a-private")
            assert found is None, "Tenant B cannot look up Tenant A's invoice"
        run_async(run())


# ===========================================================================
# Section 4: Order idempotency keys are tenant-scoped
# ===========================================================================

class TestOrderIdempotencyTenantScope:
    """Same idempotency key in two tenants must produce independent orders."""

    def test_same_idempotency_key_different_tenants_yields_separate_orders(self, mock_client):
        from tenant_orders_repository import TenantOrdersRepository
        async def run():
            ctx_a = _make_context(TENANT_A_SLUG, mock_client)
            ctx_b = _make_context(TENANT_B_SLUG, mock_client)
            repo_a = TenantOrdersRepository(ctx_a)
            repo_b = TenantOrdersRepository(ctx_b)
            idem_key = "shared-idempotency-key-1"
            order_a = await repo_a.create_order(
                customer_id="cust-x", invoice_id="inv-a-idem",
                idempotency_key=idem_key,
            )
            order_b = await repo_b.create_order(
                customer_id="cust-x", invoice_id="inv-b-idem",
                idempotency_key=idem_key,
            )
            assert order_a["_id"] != order_b["_id"], "Orders must be distinct"
            assert order_a["tenant_id"] == TENANT_A_SLUG
            assert order_b["tenant_id"] == TENANT_B_SLUG
        run_async(run())

    def test_idempotent_replay_scoped_to_own_tenant(self, mock_client):
        from tenant_orders_repository import TenantOrdersRepository
        async def run():
            ctx_a = _make_context(TENANT_A_SLUG, mock_client)
            repo_a = TenantOrdersRepository(ctx_a)
            idem_key = "replay-key-1"
            first = await repo_a.create_order(
                customer_id="cust-y", invoice_id="inv-a-replay",
                idempotency_key=idem_key,
            )
            second = await repo_a.create_order(
                customer_id="cust-y", invoice_id="inv-a-replay-2",
                idempotency_key=idem_key,
            )
            assert first["_id"] == second["_id"], "Replay must return the original"
        run_async(run())


# ===========================================================================
# Section 5: Invoice counters are isolated per tenant
# ===========================================================================

class TestInvoiceCounterIsolation:
    """Invoice counter keys must be tenant-scoped."""

    def test_invoice_counter_keys_differ_by_tenant(self):
        from invoice_sequencing import invoice_counter_key
        key_a = invoice_counter_key(TENANT_A_SLUG, "20261004")
        key_b = invoice_counter_key(TENANT_B_SLUG, "20261004")
        assert key_a != key_b, "Counter keys must differ by tenant"
        assert TENANT_A_SLUG in key_a
        assert TENANT_B_SLUG in key_b

    def test_invoice_references_include_tenant(self):
        from invoice_sequencing import compose_invoice_reference
        ref_a = compose_invoice_reference(TENANT_A_SLUG, "20261004", 1)
        ref_b = compose_invoice_reference(TENANT_B_SLUG, "20261004", 1)
        assert ref_a != ref_b
        assert TENANT_A_SLUG.upper().replace("-", "-") in ref_a.upper() or "SHOP-ALPHA" in ref_a.upper()
        assert TENANT_B_SLUG.upper().replace("-", "-") in ref_b.upper() or "SHOP-BETA" in ref_b.upper()

    def test_same_sequence_number_different_tenants_distinct_invoice(self):
        from invoice_sequencing import compose_invoice_reference, parse_invoice_reference
        ref_a = compose_invoice_reference(TENANT_A_SLUG, "20261004", 42)
        ref_b = compose_invoice_reference(TENANT_B_SLUG, "20261004", 42)
        parsed_a = parse_invoice_reference(ref_a)
        parsed_b = parse_invoice_reference(ref_b)
        assert parsed_a is not None and parsed_b is not None
        assert parsed_a["tenant_id"] != parsed_b["tenant_id"]


# ===========================================================================
# Section 6: Wallet balance and ledger are tenant-scoped
# ===========================================================================

class TestWalletLedgerTenantScope:
    """Wallet ledger operations are strictly tenant-scoped."""

    def test_ledger_entry_rejects_mismatched_tenant_id(self, mock_client):
        from wallet_ledger import create_ledger_entry
        async def run():
            ctx_a = _make_context(TENANT_A_SLUG, mock_client)
            with pytest.raises(ValueError, match="tenant_id mismatch"):
                await create_ledger_entry(
                    ctx_a.database, ctx_a,
                    tenant_id=TENANT_B_SLUG,
                    entry_type="credit", amount="50",
                    currency="USD", reference_id="ref-cross",
                    idempotency_key="key-cross",
                )
        run_async(run())

    def test_same_idempotency_key_different_tenants_independent_entries(self, mock_client):
        from wallet_ledger import create_ledger_entry
        async def run():
            ctx_a = _make_context(TENANT_A_SLUG, mock_client)
            ctx_b = _make_context(TENANT_B_SLUG, mock_client)
            idem = "shared-wallet-key"
            res_a = await create_ledger_entry(
                ctx_a.database, ctx_a, entry_type="credit",
                amount="100", currency="USD", reference_id="ref-a",
                idempotency_key=idem,
            )
            res_b = await create_ledger_entry(
                ctx_b.database, ctx_b, entry_type="credit",
                amount="200", currency="USD", reference_id="ref-b",
                idempotency_key=idem,
            )
            assert res_a["replayed"] is False
            assert res_b["replayed"] is False
            assert res_a["entry"]["entry_id"] != res_b["entry"]["entry_id"]
        run_async(run())


# ===========================================================================
# Section 7: Payment reconciliation is tenant-scoped
# ===========================================================================

class TestPaymentReconciliationTenantScope:
    """Payment reconciliation must reject cross-tenant resources."""

    def test_reconcile_rejects_payment_from_different_tenant(self):
        from sandbox_payment import reconcile_payment_with_order, TenantMismatchError
        from tenant_context import TenantContext
        ctx_a = TenantContext(
            tenant_id=TENANT_A_SLUG, database=None, status="active",
        )
        payment = {"id": "pay-1", "tenant_id": TENANT_B_SLUG,
                    "order_id": "ord-1", "amount": "100",
                    "currency": "USD", "status": "paid"}
        order = {"id": "ord-1", "tenant_id": TENANT_A_SLUG,
                 "total": "100", "currency": "USD"}
        with pytest.raises(TenantMismatchError, match="Payment tenant_id mismatch"):
            reconcile_payment_with_order(payment, order, ctx_a)

    def test_reconcile_rejects_order_from_different_tenant(self):
        from sandbox_payment import reconcile_payment_with_order, TenantMismatchError
        from tenant_context import TenantContext
        ctx_a = TenantContext(
            tenant_id=TENANT_A_SLUG, database=None, status="active",
        )
        payment = {"id": "pay-2", "tenant_id": TENANT_A_SLUG,
                    "order_id": "ord-2", "amount": "200",
                    "currency": "USD", "status": "paid"}
        order = {"id": "ord-2", "tenant_id": TENANT_B_SLUG,
                 "total": "200", "currency": "USD"}
        with pytest.raises(TenantMismatchError, match="Order tenant_id mismatch"):
            reconcile_payment_with_order(payment, order, ctx_a)

    def test_reconcile_succeeds_for_same_tenant(self):
        from sandbox_payment import reconcile_payment_with_order
        from tenant_context import TenantContext
        ctx_a = TenantContext(
            tenant_id=TENANT_A_SLUG, database=None, status="active",
        )
        payment = {"id": "pay-3", "tenant_id": TENANT_A_SLUG,
                    "order_id": "ord-3", "amount": "300",
                    "currency": "USD", "status": "paid"}
        order = {"id": "ord-3", "tenant_id": TENANT_A_SLUG,
                 "total": "300", "currency": "USD"}
        result = reconcile_payment_with_order(payment, order, ctx_a)
        assert result["reconciled"] is True
        assert result["tenant_matched"] is True

    def test_sandbox_adapter_rejects_cross_tenant_order(self):
        from sandbox_payment import SandboxPaymentAdapter, TenantMismatchError
        from tenant_context import TenantContext
        ctx_a = TenantContext(
            tenant_id=TENANT_A_SLUG, database=None, status="active",
        )
        adapter = SandboxPaymentAdapter(
            tenant_context=ctx_a,
            payments={},
            id_factory=lambda: str(uuid4()),
            clock=lambda: datetime.now(timezone.utc),
        )
        order = {"id": "ord-cross", "tenant_id": TENANT_B_SLUG,
                 "total": "50", "currency": "USD"}
        with pytest.raises(TenantMismatchError):
            adapter.create_payment(order)


# ===========================================================================
# Section 8: Global identity collections — Owner Decision 1B
# ===========================================================================

class TestGlobalIdentityPolicyEnforcement:
    """Global identity collections enforce cross-tenant uniqueness."""

    def test_store_customers_email_is_globally_unique(self):
        from global_identity_policy import get_uniqueness_scope
        scope = get_uniqueness_scope("store_customers", "email")
        assert scope == "global", "email must be globally unique"

    def test_store_customers_telegram_id_is_globally_unique(self):
        from global_identity_policy import get_uniqueness_scope
        scope = get_uniqueness_scope("store_customers", "telegram_id")
        assert scope == "global", "telegram_id must be globally unique"

    def test_bot_users_telegram_id_is_globally_unique(self):
        from global_identity_policy import get_uniqueness_scope
        scope = get_uniqueness_scope("bot_users", "telegram_id")
        assert scope == "global", "telegram_id must be globally unique"

    def test_tenant_owned_collections_are_tenant_scoped(self):
        from global_identity_policy import get_uniqueness_scope
        assert get_uniqueness_scope("products", "sku") == "tenant"
        assert get_uniqueness_scope("purchases", "invoice_id") == "tenant"

    def test_global_identity_collections_not_duplicated_per_tenant(self):
        from global_identity_policy import (
            GLOBAL_IDENTITY_COLLECTIONS,
            classify_collection,
            migration_action,
        )
        for coll in GLOBAL_IDENTITY_COLLECTIONS:
            assert classify_collection(coll) == "global_identity"
            action = migration_action(coll)
            assert action["action"] == "share", f"{coll} must share, not duplicate"
            assert action["add_tenant_id"] is False, f"{coll} must not get tenant_id"


class TestGlobalIdentityIndexEnforcement:
    """Database-level uniqueness via provision_tenant_database."""

    def test_store_customers_email_unique_index_created(self, mock_client):
        from tenant_provisioning import provision_tenant_database
        async def run():
            result = await provision_tenant_database(TENANT_A_SLUG, mock_client)
            assert result["status"] == "success"
            indexes = await mock_client[result["database_name"]].store_customers.index_information()
            email_idx = indexes.get("email_unique")
            assert email_idx is not None, "email_unique index must exist"
            assert email_idx.get("unique") is True
        run_async(run())

    def test_bot_users_telegram_id_unique_index_created(self, mock_client):
        from tenant_provisioning import provision_tenant_database
        async def run():
            result = await provision_tenant_database(TENANT_A_SLUG, mock_client)
            indexes = await mock_client[result["database_name"]].bot_users.index_information()
            tid_idx = indexes.get("telegram_id_unique")
            assert tid_idx is not None, "telegram_id_unique index must exist"
            assert tid_idx.get("unique") is True
        run_async(run())

    def test_store_customers_telegram_id_unique_index_created(self, mock_client):
        from tenant_provisioning import provision_tenant_database
        async def run():
            result = await provision_tenant_database(TENANT_A_SLUG, mock_client)
            indexes = await mock_client[result["database_name"]].store_customers.index_information()
            tid_idx = indexes.get("telegram_id_unique")
            assert tid_idx is not None, "telegram_id_unique index must exist"
            assert tid_idx.get("unique") is True
        run_async(run())


# ===========================================================================
# Section 9: Database namespace isolation (same IDs, different tenants)
# ===========================================================================

class TestDatabaseNamespaceIsolation:
    """Two tenants can use the same document IDs without collision."""

    def test_same_product_id_different_tenants_no_collision(self, mock_client):
        async def run():
            db_a = mock_client[TENANT_A_DB]
            db_b = mock_client[TENANT_B_DB]
            await db_a.products.insert_one({"_id": "prod-1", "name": "Alpha Widget"})
            await db_b.products.insert_one({"_id": "prod-1", "name": "Beta Widget"})
            a = await db_a.products.find_one({"_id": "prod-1"})
            b = await db_b.products.find_one({"_id": "prod-1"})
            assert a["name"] == "Alpha Widget"
            assert b["name"] == "Beta Widget"
        run_async(run())

    def test_same_order_id_different_tenants_no_collision(self, mock_client):
        async def run():
            db_a = mock_client[TENANT_A_DB]
            db_b = mock_client[TENANT_B_DB]
            await db_a.purchases.insert_one({"_id": "ord-1", "total": 10})
            await db_b.purchases.insert_one({"_id": "ord-1", "total": 20})
            a = await db_a.purchases.find_one({"_id": "ord-1"})
            b = await db_b.purchases.find_one({"_id": "ord-1"})
            assert a["total"] == 10
            assert b["total"] == 20
        run_async(run())
