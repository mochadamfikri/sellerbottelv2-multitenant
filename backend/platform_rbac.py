"""Platform and tenant authorization dependencies."""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Depends, HTTPException

from auth import get_current_admin
from db import db
from tenant_context import TenantContext, get_tenant_context

PLATFORM_ADMIN_ROLE = "platform_admin"
LEGACY_ADMIN_ROLE = "admin"
TENANT_ROLES = (
    "tenant_viewer",
    "tenant_operator",
    "tenant_admin",
    "tenant_owner",
)
TENANT_ROLE_LEVELS = {role: level for level, role in enumerate(TENANT_ROLES)}


def is_platform_admin(admin: dict) -> bool:
    """Return whether an authenticated principal has platform-wide access.

    ``role='admin'`` without a ``platform_role`` is accepted temporarily for
    records created before platform roles were introduced. An explicit non-platform
    role always takes precedence and is denied.
    """
    platform_role = admin.get("platform_role")
    if platform_role is not None:
        return platform_role == PLATFORM_ADMIN_ROLE
    return admin.get("role") == LEGACY_ADMIN_ROLE


async def require_platform_admin(
    admin: dict = Depends(get_current_admin),
) -> dict:
    """Require platform-wide administrator privileges."""
    if not is_platform_admin(admin):
        raise HTTPException(status_code=403, detail="Platform admin access required")
    return admin


def _validate_tenant_role(role: str) -> None:
    if role not in TENANT_ROLE_LEVELS:
        raise ValueError(f"Unknown tenant role: {role}")


async def add_tenant_member(db, tenant_id: str, user_id: str, role: str) -> dict:
    """Create or update a user's role in a tenant membership."""
    _validate_tenant_role(role)
    collection = db.tenant_memberships
    now = datetime.now(timezone.utc)
    membership = await collection.find_one({"tenant_id": tenant_id, "user_id": user_id})

    if membership:
        await collection.update_one(
            {"_id": membership["_id"]},
            {"$set": {"role": role, "updated_at": now}},
        )
        return await collection.find_one({"_id": membership["_id"]})

    membership = {
        "_id": str(uuid4()),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role,
        "created_at": now,
        "updated_at": now,
    }
    await collection.insert_one(membership)
    return await collection.find_one({"_id": membership["_id"]}) or membership


async def get_tenant_membership(db, tenant_id: str, user_id: str) -> dict | None:
    """Return one user's membership in a tenant, if it exists."""
    return await db.tenant_memberships.find_one(
        {"tenant_id": tenant_id, "user_id": user_id}
    )


async def list_tenant_members(db, tenant_id: str) -> list[dict]:
    """Return all memberships for a tenant in creation order."""
    return await db.tenant_memberships.find({"tenant_id": tenant_id}).to_list(None)


async def remove_tenant_member(db, tenant_id: str, user_id: str) -> bool:
    """Remove a user's membership from a tenant and report whether one existed."""
    result = await db.tenant_memberships.delete_one(
        {"tenant_id": tenant_id, "user_id": user_id}
    )
    return result.deleted_count == 1


def _principal_user_id(admin: dict) -> str | None:
    """Resolve the stable authenticated identifier used by membership records."""
    return admin.get("_id") or admin.get("user_id") or admin.get("email")


# UUID v4 pattern for distinguishing UUIDs from slugs
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_uuid(value: str) -> bool:
    """Return whether ``value`` looks like a UUID v4 string."""
    return bool(_UUID_PATTERN.fullmatch(value))


async def resolve_tenant_id_or_slug(
    tenant_id_or_slug: str,
    *,
    registry: Any | None = None,
) -> str:
    """Resolve a tenant identifier to its canonical UUID.

    If *tenant_id_or_slug* is already a UUID, return it unchanged.
    Otherwise treat it as a slug and look it up in *registry*.

    When *registry* is None, attempts to discover the configured global
    registry from tenant_context module. If unavailable, passes through
    the value unchanged for backward compatibility.

    Raises:
        HTTPException 404: slug not found in registry.
    """
    if _is_uuid(tenant_id_or_slug):
        return tenant_id_or_slug

    # It's a slug — resolve via registry if available
    if registry is None:
        # Auto-discover from tenant_context if configured
        try:
            from tenant_context import _tenant_registry
            registry = _tenant_registry
        except ImportError:
            pass

    # If still no registry, pass through for backward compatibility
    if registry is None:
        return tenant_id_or_slug

    tenant = await registry.get_tenant(tenant_id_or_slug)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Unknown tenant slug")

    return tenant["_id"]


def require_tenant_role(
    tenant_id: str, min_role: str, *, registry: Any | None = None
) -> Callable:
    """Return a dependency requiring a tenant membership at ``min_role`` or above.

    *tenant_id* may be a UUID (direct membership lookup) or a slug that is
    resolved to a UUID via *registry* before checking memberships.
    """
    _validate_tenant_role(min_role)

    async def tenant_role_required(
        admin: dict = Depends(get_current_admin),
    ) -> dict:
        resolved_id = await resolve_tenant_id_or_slug(tenant_id, registry=registry)
        user_id = _principal_user_id(admin)
        membership = (
            await get_tenant_membership(db, resolved_id, user_id) if user_id is not None else None
        )
        if (
            membership is None
            or TENANT_ROLE_LEVELS.get(membership.get("role"), -1)
            < TENANT_ROLE_LEVELS[min_role]
        ):
            raise HTTPException(status_code=403, detail="Tenant role access required")
        return admin

    return tenant_role_required


def require_tenant_role_dynamic(
    min_role: str, *, _test_platform_db: Any | None = None
) -> Callable:
    """Return a dependency requiring tenant membership at ``min_role`` or above,
    resolved dynamically from injected TenantContext.

    This factory accepts min_role and returns an async dependency that receives
    both TenantContext (via Depends) and current admin, then checks membership
    against the resolved tenant_id from context.

    Args:
        min_role: Minimum tenant role required (tenant_viewer, tenant_operator, etc.)
        _test_platform_db: Test-only override for membership database.

    Returns:
        FastAPI dependency callable.
    """
    _validate_tenant_role(min_role)

    async def dynamic_role_check(
        context: TenantContext = Depends(get_tenant_context),
        admin: dict = Depends(get_current_admin),
    ) -> dict:
        # Resolve tenant_id from context (could be slug, needs canonical UUID)
        resolved_id = await resolve_tenant_id_or_slug(context.tenant_id, registry=None)

        # Check membership in platform database
        platform_db = _test_platform_db if _test_platform_db is not None else db
        user_id = _principal_user_id(admin)
        membership = (
            await get_tenant_membership(platform_db, resolved_id, user_id)
            if user_id is not None
            else None
        )

        if (
            membership is None
            or TENANT_ROLE_LEVELS.get(membership.get("role"), -1)
            < TENANT_ROLE_LEVELS[min_role]
        ):
            raise HTTPException(status_code=403, detail="Tenant role access required")

        return admin

    return dynamic_role_check


def require_tenant_membership(tenant_id: str, *, registry: Any | None = None) -> Callable:
    """Return a dependency requiring at least viewer membership in a tenant."""
    return require_tenant_role(tenant_id, "tenant_viewer", registry=registry)
