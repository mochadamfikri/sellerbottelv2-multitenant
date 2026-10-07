"""Development-only tenant resolution from the ``X-Tenant-ID`` header."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Mapping

from fastapi import Header, HTTPException

from tenant_db import tenant_database_name, validate_tenant_id


@dataclass(frozen=True)
class TenantContext:
    """A resolved tenant identity and its isolated database handle."""

    tenant_id: str
    database: Any
    status: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


# Legacy hooks remain supported for existing routes and development tests.
_development_tenants: Mapping[str, Mapping[str, Any]] = {}
_development_database_client: Any = None
_tenant_registry: Any = None
_tenant_registry_database_client: Any = None


def configure_development_tenant_resolver(
    tenants: Mapping[str, Mapping[str, Any]], database_client: Any,
) -> None:
    """Configure the legacy mapping source used by the FastAPI dependency."""
    global _development_tenants, _development_database_client
    global _tenant_registry, _tenant_registry_database_client
    _development_tenants = tenants
    _development_database_client = database_client
    _tenant_registry = None
    _tenant_registry_database_client = None


def configure_tenant_registry_resolver(registry: Any, database_client: Any) -> None:
    """Configure a registry object or Mongo collection for tenant resolution."""
    global _tenant_registry, _tenant_registry_database_client
    _tenant_registry = registry
    _tenant_registry_database_client = database_client


def resolve_tenant_context(
    tenant_id: str,
    tenants: Any,
    database_client: Any,
) -> TenantContext | Any:
    """Resolve a tenant record and construct its canonical database handle.
    
    Accepts a mapping, registry object, or Mongo collection. Async sources
    return an awaitable resolving to TenantContext.
    """
    try:
        validated_tenant_id = validate_tenant_id(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID header") from exc

    if isinstance(tenants, Mapping):
        tenant = tenants.get(validated_tenant_id)
    elif hasattr(tenants, "find_one"):
        tenant = tenants.find_one({"slug": validated_tenant_id})
    elif hasattr(tenants, "get_tenant"):
        tenant = tenants.get_tenant(validated_tenant_id)
    else:
        raise TypeError("tenants must be a mapping, registry, or Mongo collection")

    if inspect.isawaitable(tenant):
        return _resolve_async(validated_tenant_id, tenant, database_client)
    return _build_context(validated_tenant_id, tenant, database_client)


async def _resolve_async(
    tenant_id: str, tenant_awaitable: Any, database_client: Any
) -> TenantContext:
    return _build_context(tenant_id, await tenant_awaitable, database_client)


def _build_context(
    tenant_id: str, tenant: Mapping[str, Any] | None, database_client: Any
) -> TenantContext:
    if tenant is None:
        raise HTTPException(status_code=404, detail="Unknown tenant")

    status = tenant.get("status", "")
    if status != "active":
        raise HTTPException(status_code=403, detail="Tenant is not active")

    database_name = tenant.get("database_name") or tenant_database_name(tenant_id)
    return TenantContext(
        tenant_id=tenant_id,
        database=database_client[database_name],
        status=status,
        metadata={
            field: tenant[field]
            for field in ("name", "plan")
            if tenant.get(field) is not None
        },
    )


async def get_tenant_context(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> TenantContext:
    """FastAPI dependency resolving ``X-Tenant-ID`` from its configured source."""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    if _tenant_registry is not None:
        context = resolve_tenant_context(
            x_tenant_id, _tenant_registry, _tenant_registry_database_client
        )
    else:
        if _development_database_client is None:
            from db import client

            database_client = client
        else:
            database_client = _development_database_client
        context = resolve_tenant_context(
            x_tenant_id, _development_tenants, database_client
        )

    return await context if inspect.isawaitable(context) else context
