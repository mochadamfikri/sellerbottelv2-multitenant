"""Injected repository for tenant-scoped purchase orders."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from tenant_db import validate_tenant_id


class TenantOrdersScopeError(ValueError):
    """Raised when an order operation crosses tenant scope."""


def _tenant_id_from_context(context: Any) -> str:
    if hasattr(context, "tenant_id"):
        return validate_tenant_id(context.tenant_id)
    if isinstance(context, str):
        return validate_tenant_id(context)
    raise ValueError("context must provide tenant_id or be a tenant slug string")


class TenantOrdersRepository:
    """Create and retrieve orders within one injected tenant database."""

    def __init__(self, context: Any, database: Any = None) -> None:
        if database is None:
            database = getattr(context, "database", None)
        if database is None:
            raise ValueError("database is required")

        self._tenant_id = _tenant_id_from_context(context)
        self._database = database

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def database(self) -> Any:
        return self._database

    @property
    def collection(self) -> Any:
        return self._database.purchases

    def _validate_tenant(self, candidate_tenant_id: str | None) -> None:
        if candidate_tenant_id is None:
            return
        try:
            candidate = validate_tenant_id(candidate_tenant_id)
        except ValueError as exc:
            raise TenantOrdersScopeError("Tenant mismatch") from exc
        if candidate != self._tenant_id:
            raise TenantOrdersScopeError(
                f"Tenant mismatch: expected '{self._tenant_id}', got '{candidate}'"
            )

    async def find_order_by_idempotency(
        self, *, customer_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Return this tenant's order for one customer idempotency key."""
        return await self.collection.find_one(
            {
                "tenant_id": self._tenant_id,
                "customer_id": customer_id,
                "idempotency_key": idempotency_key,
            }
        )

    async def create_order(
        self,
        *,
        customer_id: str,
        invoice_id: str,
        idempotency_key: str | None = None,
        order_data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an order, returning the original order for an idempotent retry."""
        if not customer_id:
            raise ValueError("customer_id is required")
        if not invoice_id:
            raise ValueError("invoice_id is required")

        data = dict(order_data or {})
        self._validate_tenant(data.get("tenant_id"))

        if idempotency_key:
            existing = await self.find_order_by_idempotency(
                customer_id=customer_id, idempotency_key=idempotency_key
            )
            if existing is not None:
                return existing

        order = {
            **data,
            "_id": data.get("_id", str(uuid4())),
            "tenant_id": self._tenant_id,
            "customer_id": customer_id,
            "invoice_id": invoice_id,
            "created_at": data.get("created_at", datetime.now(timezone.utc)),
        }
        if idempotency_key is not None:
            order["idempotency_key"] = idempotency_key

        try:
            await self.collection.insert_one(order)
        except Exception as exc:
            if idempotency_key and "duplicate key" in str(exc).lower():
                existing = await self.find_order_by_idempotency(
                    customer_id=customer_id, idempotency_key=idempotency_key
                )
                if existing is not None:
                    return existing
            raise

        return order

    async def get_order_by_id(self, order_id: str) -> dict[str, Any] | None:
        """Return an order only if it belongs to this tenant."""
        return await self.collection.find_one(
            {"_id": order_id, "tenant_id": self._tenant_id}
        )

    async def get_order_by_invoice_id(self, invoice_id: str) -> dict[str, Any] | None:
        """Return an invoice's order only if it belongs to this tenant."""
        return await self.collection.find_one(
            {"invoice_id": invoice_id, "tenant_id": self._tenant_id}
        )
