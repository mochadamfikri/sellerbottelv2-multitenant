"""Platform database index management for the control plane.

Creates and maintains indexes on the tenants and tenant_memberships
collections in the platform database (sellerbottel_platform).

Usage:
    from platform_indexes import ensure_platform_indexes

    await ensure_platform_indexes(db)

All create_index calls are idempotent — safe to run on every startup.
"""
from __future__ import annotations

from typing import Any


async def ensure_platform_indexes(db: Any) -> None:
    """Create required indexes on platform-level collections.

    ``db`` is the platform database handle (e.g. ``client["sellerbottel_platform"]``).
    Every call is idempotent: MongoDB ignores duplicate index definitions
    that match an existing index.
    """
    # --- tenants collection ---
    await db.tenants.create_index(
        "slug", unique=True, name="tenant_slug_unique"
    )
    await db.tenants.create_index(
        "database_name", unique=True, name="tenant_database_name_unique"
    )
    await db.tenants.create_index(
        [("status", 1), ("created_at", -1)]
    )

    # --- tenant_memberships collection ---
    await db.tenant_memberships.create_index(
        [("tenant_id", 1), ("user_id", 1)],
        unique=True,
        name="tenant_user_unique",
    )
    await db.tenant_memberships.create_index(
        [("tenant_id", 1), ("created_at", 1)]
    )
    await db.tenant_memberships.create_index("user_id")
