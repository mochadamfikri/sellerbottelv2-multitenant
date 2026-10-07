"""Offline tests for the tenant-scoped sandbox payment adapter."""

from datetime import datetime, timezone
from decimal import Decimal

from sandbox_payment import SandboxPaymentAdapter
from tenant_context import TenantContext


def context(tenant_id: str) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, database=None, status="active")


def test_create_payment_records_pending_payment_for_context_tenant():
    adapter = SandboxPaymentAdapter(
        tenant_context=context("acme"),
        payments={},
        id_factory=lambda: "sandbox-pay-1",
        clock=lambda: datetime(2026, 10, 4, tzinfo=timezone.utc),
    )

    payment = adapter.create_payment(
        {"id": "order-1", "tenant_id": "acme", "total": Decimal("12500.00"), "currency": "IDR"}
    )

    assert payment == {
        "id": "sandbox-pay-1",
        "tenant_id": "acme",
        "order_id": "order-1",
        "amount": Decimal("12500.00"),
        "currency": "IDR",
        "status": "pending",
        "created_at": datetime(2026, 10, 4, tzinfo=timezone.utc),
        "finalized_at": None,
    }


def test_finalize_payment_marks_pending_payment_as_paid():
    finalized_at = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    adapter = SandboxPaymentAdapter(
        tenant_context=context("acme"),
        payments={
            "sandbox-pay-1": {
                "id": "sandbox-pay-1", "tenant_id": "acme", "order_id": "order-1",
                "amount": Decimal("12500.00"), "currency": "IDR", "status": "pending",
                "created_at": finalized_at, "finalized_at": None,
            }
        },
        id_factory=lambda: "unused",
        clock=lambda: finalized_at,
    )

    payment = adapter.finalize_payment("sandbox-pay-1")

    assert payment["status"] == "paid"
    assert payment["finalized_at"] == finalized_at


def test_create_payment_rejects_order_from_different_tenant():
    import pytest
    from sandbox_payment import TenantMismatchError

    adapter = SandboxPaymentAdapter(
        tenant_context=context("acme"),
        payments={},
        id_factory=lambda: "unused",
        clock=lambda: datetime(2026, 10, 4, tzinfo=timezone.utc),
    )

    with pytest.raises(TenantMismatchError, match="tenant_id mismatch"):
        adapter.create_payment(
            {"id": "order-1", "tenant_id": "evil-tenant", "total": Decimal("100.00"), "currency": "IDR"}
        )


def test_reconcile_payment_matches_order_amount_and_tenant():
    from sandbox_payment import reconcile_payment_with_order

    payment = {
        "id": "sandbox-pay-1",
        "tenant_id": "acme",
        "order_id": "order-1",
        "amount": Decimal("12500.00"),
        "currency": "IDR",
        "status": "paid",
    }
    order = {
        "id": "order-1",
        "tenant_id": "acme",
        "total": Decimal("12500.00"),
        "currency": "IDR",
    }

    result = reconcile_payment_with_order(
        payment=payment,
        order=order,
        tenant_context=context("acme"),
    )

    assert result["reconciled"] is True
    assert result["payment_id"] == "sandbox-pay-1"
    assert result["order_id"] == "order-1"
    assert result["amount_matched"] is True
    assert result["tenant_matched"] is True


def test_reconcile_payment_fails_when_amount_mismatches():
    from sandbox_payment import reconcile_payment_with_order

    payment = {
        "id": "sandbox-pay-1",
        "tenant_id": "acme",
        "order_id": "order-1",
        "amount": Decimal("12500.00"),
        "currency": "IDR",
        "status": "paid",
    }
    order = {
        "id": "order-1",
        "tenant_id": "acme",
        "total": Decimal("15000.00"),
        "currency": "IDR",
    }

    result = reconcile_payment_with_order(
        payment=payment,
        order=order,
        tenant_context=context("acme"),
    )

    assert result["reconciled"] is False
    assert result["amount_matched"] is False


def test_reconcile_payment_rejects_tenant_mismatch_in_payment():
    import pytest
    from sandbox_payment import reconcile_payment_with_order, TenantMismatchError

    payment = {
        "id": "sandbox-pay-1",
        "tenant_id": "evil-tenant",
        "order_id": "order-1",
        "amount": Decimal("12500.00"),
        "currency": "IDR",
        "status": "paid",
    }
    order = {
        "id": "order-1",
        "tenant_id": "acme",
        "total": Decimal("12500.00"),
        "currency": "IDR",
    }

    with pytest.raises(TenantMismatchError, match="Payment tenant_id mismatch"):
        reconcile_payment_with_order(
            payment=payment,
            order=order,
            tenant_context=context("acme"),
        )


def test_reconcile_payment_rejects_tenant_mismatch_in_order():
    import pytest
    from sandbox_payment import reconcile_payment_with_order, TenantMismatchError

    payment = {
        "id": "sandbox-pay-1",
        "tenant_id": "acme",
        "order_id": "order-1",
        "amount": Decimal("12500.00"),
        "currency": "IDR",
        "status": "paid",
    }
    order = {
        "id": "order-1",
        "tenant_id": "evil-tenant",
        "total": Decimal("12500.00"),
        "currency": "IDR",
    }

    with pytest.raises(TenantMismatchError, match="Order tenant_id mismatch"):
        reconcile_payment_with_order(
            payment=payment,
            order=order,
            tenant_context=context("acme"),
        )


def test_create_payment_stores_payment_in_injected_storage():
    storage = {}
    adapter = SandboxPaymentAdapter(
        tenant_context=context("acme"),
        payments=storage,
        id_factory=lambda: "sandbox-pay-1",
        clock=lambda: datetime(2026, 10, 4, tzinfo=timezone.utc),
    )

    adapter.create_payment(
        {"id": "order-1", "tenant_id": "acme", "total": Decimal("12500.00"), "currency": "IDR"}
    )

    assert "sandbox-pay-1" in storage
    assert storage["sandbox-pay-1"]["status"] == "pending"


def test_finalize_payment_validates_payment_tenant():
    import pytest
    from sandbox_payment import TenantMismatchError

    adapter = SandboxPaymentAdapter(
        tenant_context=context("acme"),
        payments={
            "sandbox-pay-1": {
                "id": "sandbox-pay-1", "tenant_id": "other-tenant", "order_id": "order-1",
                "amount": Decimal("12500.00"), "currency": "IDR", "status": "pending",
                "created_at": datetime(2026, 10, 4, tzinfo=timezone.utc), "finalized_at": None,
            }
        },
        id_factory=lambda: "unused",
        clock=lambda: datetime(2026, 10, 4, 12, tzinfo=timezone.utc),
    )

    with pytest.raises(TenantMismatchError, match="Payment tenant_id mismatch"):
        adapter.finalize_payment("sandbox-pay-1")


def test_reconcile_payment_fails_when_payment_not_finalized():
    from sandbox_payment import reconcile_payment_with_order

    payment = {
        "id": "sandbox-pay-1",
        "tenant_id": "acme",
        "order_id": "order-1",
        "amount": Decimal("12500.00"),
        "currency": "IDR",
        "status": "pending",
    }
    order = {
        "id": "order-1",
        "tenant_id": "acme",
        "total": Decimal("12500.00"),
        "currency": "IDR",
    }

    result = reconcile_payment_with_order(
        payment=payment,
        order=order,
        tenant_context=context("acme"),
    )

    assert result["reconciled"] is False
    assert result["payment_finalized"] is False
