"""Pure/injected sandbox payment adapter and reconciliation helper module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Mapping, MutableMapping

from tenant_context import TenantContext


class TenantMismatchError(ValueError):
    """Raised when tenant context does not match resource tenant."""


class SandboxPaymentAdapter:
    """Pure, dependency-injected sandbox payment adapter with strict tenant isolation."""

    def __init__(
        self,
        tenant_context: TenantContext,
        payments: MutableMapping[str, dict[str, Any]],
        id_factory: Callable[[], str],
        clock: Callable[[], datetime],
    ) -> None:
        self.tenant_context = tenant_context
        self._payments = payments
        self._id_factory = id_factory
        self._clock = clock

    def create_payment(self, order: Mapping[str, Any]) -> dict[str, Any]:
        order_tenant_id = order.get("tenant_id")
        if order_tenant_id != self.tenant_context.tenant_id:
            raise TenantMismatchError(
                f"Order tenant_id mismatch: expected '{self.tenant_context.tenant_id}', got '{order_tenant_id}'"
            )
        payment_id = self._id_factory()
        now = self._clock()
        payment = {
            "id": payment_id,
            "tenant_id": self.tenant_context.tenant_id,
            "order_id": order["id"],
            "amount": Decimal(str(order["total"])),
            "currency": str(order["currency"]),
            "status": "pending",
            "created_at": now,
            "finalized_at": None,
        }
        self._payments[payment_id] = payment
        return payment

    def finalize_payment(self, payment_id: str) -> dict[str, Any]:
        payment = self._payments[payment_id]
        _require_tenant(self.tenant_context, payment, "Payment")
        payment["status"] = "paid"
        payment["finalized_at"] = self._clock()
        return payment


def reconcile_payment_with_order(
    payment: Mapping[str, Any], order: Mapping[str, Any], tenant_context: TenantContext
) -> dict[str, Any]:
    """Reconcile a finalized sandbox payment with an order in one tenant."""
    _require_tenant(tenant_context, payment, "Payment")
    _require_tenant(tenant_context, order, "Order")
    order_id_matched = payment.get("order_id") == order.get("id")
    amount_matched = Decimal(str(payment.get("amount"))) == Decimal(str(order.get("total")))
    currency_matched = payment.get("currency") == order.get("currency")
    payment_finalized = payment.get("status") == "paid"
    return {
        "reconciled": order_id_matched and amount_matched and currency_matched and payment_finalized,
        "payment_id": payment.get("id"),
        "order_id": order.get("id"),
        "tenant_matched": True,
        "order_id_matched": order_id_matched,
        "amount_matched": amount_matched,
        "currency_matched": currency_matched,
        "payment_finalized": payment_finalized,
    }


def _require_tenant(
    tenant_context: TenantContext, resource: Mapping[str, Any], resource_name: str
) -> None:
    resource_tenant_id = resource.get("tenant_id")
    if resource_tenant_id != tenant_context.tenant_id:
        raise TenantMismatchError(
            f"{resource_name} tenant_id mismatch: expected '{tenant_context.tenant_id}', got '{resource_tenant_id}'"
        )
