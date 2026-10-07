"""Tests for tenant wallet ledger with immutable debit/credit records."""
import asyncio
from decimal import Decimal

import pytest
from mongomock_motor import AsyncMongoMockClient

from tenant_context import TenantContext
from wallet_ledger import create_ledger_entry, wallet_balance


def async_test(function):
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return wrapper


def _context(tenant_id: str = "tenant-1") -> TenantContext:
    return TenantContext(tenant_id=tenant_id, database=None, status="active")


@async_test
async def test_record_credit_creates_entry_in_injected_db():
    client = AsyncMongoMockClient()
    db = client["isolated_tenant_1"]
    ctx = _context("tenant-1")

    result = await create_ledger_entry(
        db,
        ctx,
        entry_type="credit",
        amount=Decimal("150.25"),
        currency="USD",
        reference_id="ref-100",
        idempotency_key="key-1",
        description="Top-up",
    )

    assert result["replayed"] is False
    assert result["entry"]["amount"] == "150.25"
    assert result["entry"]["tenant_id"] == "tenant-1"
    assert result["entry"]["entry_type"] == "credit"
    stored = await db.wallet_ledger.find_one({"idempotency_key": "key-1"})
    assert stored is not None
    assert stored["reference_id"] == "ref-100"


@async_test
async def test_record_debit_creates_entry_in_injected_db():
    client = AsyncMongoMockClient()
    db = client["isolated_tenant_1"]
    ctx = _context("tenant-1")

    result = await create_ledger_entry(
        db,
        ctx,
        entry_type="debit",
        amount=Decimal("40.00"),
        currency="USD",
        reference_id="ref-101",
        idempotency_key="key-2",
        description="Checkout fee",
    )

    assert result["replayed"] is False
    assert result["entry"]["amount"] == "40.00"
    assert result["entry"]["entry_type"] == "debit"


@async_test
async def test_idempotent_replays_return_existing_entry():
    client = AsyncMongoMockClient()
    db = client["isolated_tenant_1"]
    ctx = _context("tenant-1")

    first = await create_ledger_entry(
        db,
        ctx,
        entry_type="credit",
        amount="50",
        currency="IDR",
        reference_id="inv-1",
        idempotency_key="replayed-key",
    )
    second = await create_ledger_entry(
        db,
        ctx,
        entry_type="credit",
        amount="50",
        currency="IDR",
        reference_id="inv-1",
        idempotency_key="replayed-key",
    )

    assert first["replayed"] is False
    assert second["replayed"] is True
    assert first["entry"]["entry_id"] == second["entry"]["entry_id"]
    count = await db.wallet_ledger.count_documents({"idempotency_key": "replayed-key"})
    assert count == 1


@async_test
async def test_replaying_with_conflicting_payload_raises():
    client = AsyncMongoMockClient()
    db = client["isolated_tenant_1"]
    ctx = _context("tenant-1")

    await create_ledger_entry(
        db,
        ctx,
        entry_type="credit",
        amount="50",
        currency="USD",
        reference_id="ref-a",
        idempotency_key="conflict-key",
    )

    with pytest.raises(ValueError, match="already used with a different request"):
        await create_ledger_entry(
            db,
            ctx,
            entry_type="debit",
            amount="50",
            currency="USD",
            reference_id="ref-a",
            idempotency_key="conflict-key",
        )


@async_test
async def test_tenant_id_must_match_context():
    client = AsyncMongoMockClient()
    db = client["isolated_tenant_1"]
    ctx = _context("tenant-1")

    with pytest.raises(ValueError, match="tenant_id mismatch with tenant context"):
        await create_ledger_entry(
            db,
            ctx,
            tenant_id="tenant-2",
            entry_type="credit",
            amount="10",
            currency="USD",
            reference_id="ref-mismatch",
            idempotency_key="key-mismatch",
        )


@async_test
async def test_requires_valid_positive_amount():
    client = AsyncMongoMockClient()
    db = client["isolated_tenant_1"]
    ctx = _context("tenant-1")

    with pytest.raises(ValueError, match="amount must be a finite positive decimal"):
        await create_ledger_entry(
            db,
            ctx,
            entry_type="credit",
            amount="-10",
            currency="USD",
            reference_id="ref-neg",
            idempotency_key="key-neg",
        )

    with pytest.raises(ValueError, match="amount must be a finite positive decimal"):
        await create_ledger_entry(
            db,
            ctx,
            entry_type="credit",
            amount="0",
            currency="USD",
            reference_id="ref-zero",
            idempotency_key="key-zero",
        )


@async_test
async def test_requires_valid_entry_type():
    client = AsyncMongoMockClient()
    db = client["isolated_tenant_1"]
    ctx = _context("tenant-1")

    with pytest.raises(ValueError, match="entry_type must be 'debit' or 'credit'"):
        await create_ledger_entry(
            db,
            ctx,
            entry_type="refund",  # type: ignore[arg-type]
            amount="10",
            currency="USD",
            reference_id="ref-invalid",
            idempotency_key="key-invalid",
        )


@async_test
async def test_balance_calculation_sums_credits_and_subtracts_debits():
    client = AsyncMongoMockClient()
    db = client["isolated_tenant_1"]
    ctx = _context("tenant-1")

    await create_ledger_entry(
        db, ctx, entry_type="credit", amount="100.50", currency="USD",
        reference_id="1", idempotency_key="b1",
    )
    await create_ledger_entry(
        db, ctx, entry_type="credit", amount="25.00", currency="USD",
        reference_id="2", idempotency_key="b2",
    )
    await create_ledger_entry(
        db, ctx, entry_type="debit", amount="30.25", currency="USD",
        reference_id="3", idempotency_key="b3",
    )

    balance = await wallet_balance(db, ctx, currency="USD")
    assert balance == Decimal("95.25")


@async_test
async def test_balance_is_isolated_by_tenant_and_currency():
    client = AsyncMongoMockClient()
    db = client["isolated_tenant_1"]
    ctx1 = _context("tenant-1")
    ctx2 = _context("tenant-2")

    await create_ledger_entry(
        db, ctx1, entry_type="credit", amount="100.00", currency="USD",
        reference_id="1", idempotency_key="t1-usd",
    )
    await create_ledger_entry(
        db, ctx1, entry_type="credit", amount="50000", currency="IDR",
        reference_id="2", idempotency_key="t1-idr",
    )
    await create_ledger_entry(
        db, ctx2, entry_type="credit", amount="70.00", currency="USD",
        reference_id="3", idempotency_key="t2-usd",
    )

    assert await wallet_balance(db, ctx1, currency="USD") == Decimal("100.00")
    assert await wallet_balance(db, ctx1, currency="IDR") == Decimal("50000")
    assert await wallet_balance(db, ctx2, currency="USD") == Decimal("70.00")
    assert await wallet_balance(db, ctx2, currency="EUR") == Decimal("0")
