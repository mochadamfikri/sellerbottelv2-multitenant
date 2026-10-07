"""Tenant-scoped inventory repository and reservation primitives.

Enforces strict tenant isolation per Owner Decision 3:
- Inventory items belong to a single tenant and are NEVER shared across tenants.
- All operations reject mismatched tenant IDs.
- Available inventory selection and reservations are strictly scoped to the context tenant.
- Cross-tenant inventory allocation or transfer is strictly prohibited.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from tenant_db import validate_tenant_id


class TenantInventoryScopeError(ValueError):
    """Raised when an operation attempts cross-tenant access or provides a mismatched tenant_id."""


def now_iso() -> str:
    """Return current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def validate_tenant_scope(context_tenant_id: str, candidate_tenant_id: str | None = None) -> str:
    """Validate tenant identity and assert candidate matches context if provided."""
    validated_context = validate_tenant_id(context_tenant_id)
    if candidate_tenant_id is not None:
        try:
            validated_candidate = validate_tenant_id(candidate_tenant_id)
        except ValueError as exc:
            raise TenantInventoryScopeError(
                f"Candidate tenant_id '{candidate_tenant_id}' is invalid"
            ) from exc
        if validated_candidate != validated_context:
            raise TenantInventoryScopeError(
                f"Tenant scope mismatch: context tenant_id '{validated_context}' does not match "
                f"candidate tenant_id '{validated_candidate}'"
            )
    return validated_context


class TenantInventoryRepository:
    """Repository managing tenant-scoped inventory storage and reservations with an injected DB."""

    def __init__(self, context: Any, database: Any = None) -> None:
        if database is None:
            if hasattr(context, "database") and context.database is not None:
                self._database = context.database
            else:
                raise ValueError("A database instance must be injected")
        else:
            self._database = database

        if hasattr(context, "tenant_id"):
            raw_tenant_id = context.tenant_id
        elif isinstance(context, str):
            raw_tenant_id = context
        else:
            raise ValueError("context must provide tenant_id or be a tenant slug string")

        self._tenant_id = validate_tenant_id(raw_tenant_id)

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def database(self) -> Any:
        return self._database

    @property
    def collection(self) -> Any:
        return self._database.inventory_items

    async def add_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        """Add a single inventory item to the tenant's pool.

        Rejects items with a mismatched tenant_id. Tags untagged items with the context tenant_id.
        """
        item_tenant = item.get("tenant_id")
        validate_tenant_scope(self._tenant_id, item_tenant)

        doc = dict(item)
        doc["tenant_id"] = self._tenant_id
        if "_id" not in doc:
            doc["_id"] = str(uuid.uuid4())
        if "status" not in doc:
            doc["status"] = "available"
        if "created_at" not in doc:
            doc["created_at"] = now_iso()

        await self.collection.insert_one(doc)
        return doc

    async def available_items(
        self, product_id: str, limit: int | None = None, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return available inventory items for product strictly within the context tenant."""
        validate_tenant_scope(self._tenant_id, tenant_id)

        query = {
            "tenant_id": self._tenant_id,
            "product_id": product_id,
            "status": "available",
        }
        cursor = self.collection.find(query).sort("_id", 1)
        if limit is not None and limit > 0:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=limit)

    async def reserve_items(
        self,
        product_id: str,
        quantity: int,
        reservation_id: str,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Atomically reserve available items for product strictly within context tenant.

        If available items within the tenant are insufficient, any reserved items in this batch
        are rolled back and an empty list is returned. Never allocates inventory across tenants.
        """
        validate_tenant_scope(self._tenant_id, tenant_id)

        if not reservation_id or not isinstance(reservation_id, str):
            raise ValueError("reservation_id must be a non-empty string")
        if quantity < 1:
            return []

        reserved: list[dict[str, Any]] = []
        for _ in range(quantity):
            item = await self.collection.find_one_and_update(
                {
                    "tenant_id": self._tenant_id,
                    "product_id": product_id,
                    "status": "available",
                },
                {
                    "$set": {
                        "status": "reserved",
                        "reservation_id": reservation_id,
                        "reserved_at": now_iso(),
                    }
                },
                sort=[("_id", 1)],
            )
            if not item:
                await self.release_items(reservation_id)
                return []
            reserved.append(item)

        return reserved

    async def release_items(
        self, reservation_id: str, tenant_id: str | None = None
    ) -> int:
        """Release reserved items back to available, strictly scoped to context tenant."""
        validate_tenant_scope(self._tenant_id, tenant_id)

        if not reservation_id:
            raise ValueError("reservation_id must be a non-empty string")

        result = await self.collection.update_many(
            {
                "tenant_id": self._tenant_id,
                "reservation_id": reservation_id,
                "status": "reserved",
            },
            {
                "$set": {
                    "status": "available",
                    "reservation_id": None,
                    "reserved_at": None,
                }
            },
        )
        return getattr(result, "modified_count", 0)

    async def commit_items(
        self,
        reservation_id: str,
        order_id: str,
        user_tid: int | None = None,
        customer_id: str | None = None,
        tenant_id: str | None = None,
    ) -> int:
        """Commit reserved items to sold, strictly scoped to context tenant."""
        validate_tenant_scope(self._tenant_id, tenant_id)

        if not reservation_id:
            raise ValueError("reservation_id must be a non-empty string")
        if not order_id:
            raise ValueError("order_id must be a non-empty string")

        result = await self.collection.update_many(
            {
                "tenant_id": self._tenant_id,
                "reservation_id": reservation_id,
                "status": "reserved",
            },
            {
                "$set": {
                    "status": "sold",
                    "reservation_id": None,
                    "order_id": order_id,
                    "user_tid": user_tid,
                    "customer_id": customer_id,
                    "sold_at": now_iso(),
                }
            },
        )
        return getattr(result, "modified_count", 0)
