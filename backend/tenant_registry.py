"""In-memory registry for platform tenant metadata."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


TenantDocument = dict[str, Any]


# Every lifecycle state is reachable so a provisioning workflow can retry or
# recover a tenant after an operational failure.
TENANT_STATUS_TRANSITIONS = {
    status: frozenset({"provisioning", "active", "suspended", "disabled", "failed"})
    for status in ("provisioning", "active", "suspended", "disabled", "failed")
}

from tenant_db import resolve_platform_database_name, tenant_database_name, validate_tenant_id


VALID_STATUSES = frozenset({"active", "suspended"})
VALID_MONGO_STATUSES = frozenset({"provisioning", "active", "suspended", "disabled", "failed"})
VALID_PLANS = frozenset({"demo", "monthly", "yearly", "lifetime"})


def _utc_datetime(value: object) -> object:
    """Restore MongoDB's timezone-stripped UTC timestamps to aware datetimes."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _normalize_timestamps(tenant: TenantDocument | None) -> TenantDocument | None:
    if tenant is None:
        return None
    normalized = tenant.copy()
    for field in ("created_at", "updated_at"):
        normalized[field] = _utc_datetime(normalized.get(field))
    return normalized


class TenantRegistry:
    """Store tenant records in memory for the configured platform database."""

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.platform_database_name = resolve_platform_database_name(environment or {})
        self._tenants: dict[str, dict[str, object]] = {}

    def create_tenant(
        self, slug: str, name: str, plan: str | None = None
    ) -> dict[str, object]:
        if slug in self._tenants:
            raise ValueError(f"tenant slug '{slug}' already exists")

        tenant: dict[str, object] = {
            "_id": str(uuid4()),
            "slug": slug,
            "name": name,
            "status": "active",
            "database_name": tenant_database_name(slug, self.platform_database_name),
            "created_at": datetime.now(timezone.utc),
        }
        if plan is not None:
            tenant["plan"] = plan
        self._tenants[slug] = tenant
        return tenant.copy()

    def get_tenant(self, slug: str) -> dict[str, object] | None:
        tenant = self._tenants.get(slug)
        return tenant.copy() if tenant is not None else None

    def clear(self) -> None:
        """Clear registered tenants; intended for isolated tests."""
        self._tenants.clear()

    def list_tenants(self) -> list[dict[str, object]]:
        return [tenant.copy() for tenant in self._tenants.values()]

    def update_status(self, slug: str, status: str) -> dict[str, object]:
        if status not in VALID_STATUSES:
            raise ValueError(f"unsupported tenant status: {status}")
        tenant = self._tenants.get(slug)
        if tenant is None:
            raise KeyError(f"tenant slug '{slug}' was not found")
        tenant["status"] = status
        return tenant.copy()

    def update_plan(self, slug: str, plan: str, quotas: dict[str, int]) -> dict[str, object]:
        """Update tenant plan and quotas."""
        if plan not in VALID_PLANS:
            raise ValueError(f"invalid plan: {plan}")
        tenant = self._tenants.get(slug)
        if tenant is None:
            raise KeyError(f"tenant slug '{slug}' was not found")
        tenant["plan"] = plan
        tenant["quotas"] = quotas
        return tenant.copy()

    def mark_provisioned(self, slug: str) -> dict[str, object]:
        """Mark tenant as provisioned."""
        tenant = self._tenants.get(slug)
        if tenant is None:
            raise KeyError(f"tenant slug '{slug}' was not found")
        tenant["provisioned"] = True
        return tenant.copy()

    def ensure_indexes(self) -> dict[str, dict[str, bool]]:
        """Return the unique index contract used by this in-memory registry."""
        return {"slug": {"unique": True}}


class MongoTenantRegistry:
    """MongoDB-backed persistent tenant registry with full lifecycle management."""

    def __init__(
        self,
        environment: Mapping[str, str] | None = None,
        client: AsyncIOMotorClient | None = None,
    ) -> None:
        self.platform_database_name = resolve_platform_database_name(environment or {})
        self._environment = environment or {}
        self._client = client

    @property
    def client(self) -> AsyncIOMotorClient:
        if self._client is None:
            mongo_url = self._environment.get("MONGO_URL") or os.environ.get(
                "MONGO_URL", "mongodb://127.0.0.1:27017"
            )
            self._client = AsyncIOMotorClient(mongo_url)
        return self._client

    @property
    def database(self):
        return self.client[self.platform_database_name]

    @property
    def collection(self):
        return self.database["tenants"]

    async def connect(self) -> None:
        """Explicitly touch client and collection; backwards compatibility helper."""
        _ = self.collection

    async def create_tenant(
        self,
        slug: str,
        name: str,
        plan: str,
        quotas: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> TenantDocument:
        """Create a new tenant with all required schema fields."""
        if plan not in VALID_PLANS:
            raise ValueError(f"invalid plan: {plan}")

        validate_tenant_id(slug)

        existing = await self.collection.find_one({"slug": slug})
        if existing is not None:
            raise ValueError(f"tenant slug '{slug}' already exists")

        now = datetime.now(timezone.utc)
        now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        tenant: TenantDocument = {
            "_id": str(uuid4()),
            "slug": slug,
            "name": name,
            "status": "provisioning",
            "plan": plan,
            "quotas": quotas if quotas is not None else {},
            "metadata": metadata if metadata is not None else {},
            "database_name": tenant_database_name(slug, self.platform_database_name),
            "created_at": now,
            "updated_at": now,
        }

        try:
            await self.collection.insert_one(tenant.copy())
        except DuplicateKeyError as error:
            raise ValueError(f"tenant slug '{slug}' already exists") from error

        return tenant

    async def get_tenant(self, slug: str) -> TenantDocument | None:
        """Retrieve a tenant by slug."""
        tenant = await self.collection.find_one({"slug": slug})
        return _normalize_timestamps(tenant)

    async def list_tenants(self) -> list[TenantDocument]:
        """List all tenants in persistence."""
        cursor = self.collection.find({})
        tenants = await cursor.to_list(length=None)
        return [_normalize_timestamps(tenant) for tenant in tenants if tenant is not None]

    async def update_status(self, slug: str, status: str) -> TenantDocument:
        """Update tenant lifecycle status."""
        if status not in VALID_MONGO_STATUSES:
            raise ValueError(f"unsupported tenant status: {status}")

        now = datetime.now(timezone.utc)
        now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        updated = await self.collection.find_one_and_update(
            {"slug": slug},
            {"$set": {"status": status, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise KeyError(f"tenant slug '{slug}' was not found")

        normalized = _normalize_timestamps(updated)
        assert normalized is not None
        return normalized

    async def update_plan(self, slug: str, plan: str) -> TenantDocument:
        """Update tenant pricing plan."""
        if plan not in VALID_PLANS:
            raise ValueError(f"invalid plan: {plan}")

        now = datetime.now(timezone.utc)
        now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        updated = await self.collection.find_one_and_update(
            {"slug": slug},
            {"$set": {"plan": plan, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise KeyError(f"tenant slug '{slug}' was not found")

        normalized = _normalize_timestamps(updated)
        assert normalized is not None
        return normalized

    async def set_quotas(self, slug: str, quotas: dict[str, object]) -> TenantDocument:
        """Set/replace tenant resource quotas."""
        now = datetime.now(timezone.utc)
        now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        updated = await self.collection.find_one_and_update(
            {"slug": slug},
            {"$set": {"quotas": quotas, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise KeyError(f"tenant slug '{slug}' was not found")

        normalized = _normalize_timestamps(updated)
        assert normalized is not None
        return normalized

    async def set_metadata(self, slug: str, metadata: dict[str, object]) -> TenantDocument:
        """Set/replace arbitrary tenant metadata."""
        now = datetime.now(timezone.utc)
        now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        updated = await self.collection.find_one_and_update(
            {"slug": slug},
            {"$set": {"metadata": metadata, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise KeyError(f"tenant slug '{slug}' was not found")

        normalized = _normalize_timestamps(updated)
        assert normalized is not None
        return normalized

    async def ensure_indexes(self) -> None:
        """Create unique index on tenant slug."""
        await self.collection.create_index("slug", unique=True)

    async def clear(self) -> None:
        """Clear all tenant records from MongoDB (for testing)."""
        await self.collection.delete_many({})
