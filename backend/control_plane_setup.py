"""Injected-repository helpers for Stage 1 platform control-plane setup."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from idse_tenant import IDSE_DEFAULT_PLAN, IDSE_TENANT_ID, IDSE_TENANT_NAME
from tenant_db import tenant_database_name

PLATFORM_ADMIN_ROLE = "platform_admin"
TENANT_OWNER_ROLE = "tenant_owner"


async def setup_idse_control_plane(
    database: Any, admin_identifier: str
) -> dict[str, dict[str, Any]]:
    """Idempotently create IDSE and assign an existing admin its control-plane roles.

    ``database`` is injected so callers choose the development control-plane
    database explicitly; this helper never constructs a database client.
    """
    admin = await database.admins.find_one(
        {"$or": [{"_id": admin_identifier}, {"email": admin_identifier}]}
    )
    if admin is None:
        raise LookupError(f"admin '{admin_identifier}' was not found")

    admin_id = admin["_id"]

    tenant = await database.tenants.find_one({"slug": IDSE_TENANT_ID})
    if tenant is None:
        now = datetime.now(timezone.utc)
        tenant = {
            "_id": str(uuid4()),
            "slug": IDSE_TENANT_ID,
            "name": IDSE_TENANT_NAME,
            "status": "active",
            "plan": IDSE_DEFAULT_PLAN,
            "quotas": {},
            "metadata": {},
            "database_name": tenant_database_name(IDSE_TENANT_ID),
            "created_at": now,
            "updated_at": now,
        }
        await database.tenants.insert_one(tenant)
        tenant = await database.tenants.find_one({"_id": tenant["_id"]})
        assert tenant is not None

    await database.admins.update_one(
        {"_id": admin_id}, {"$set": {"platform_role": PLATFORM_ADMIN_ROLE}}
    )
    admin = await database.admins.find_one({"_id": admin_id})
    assert admin is not None

    membership = await database.tenant_memberships.find_one(
        {"tenant_id": tenant["_id"], "user_id": admin_id}
    )
    if membership is None:
        now = datetime.now(timezone.utc)
        membership = {
            "_id": str(uuid4()),
            "tenant_id": tenant["_id"],
            "user_id": admin_id,
            "role": TENANT_OWNER_ROLE,
            "created_at": now,
            "updated_at": now,
        }
        await database.tenant_memberships.insert_one(membership)
        membership = await database.tenant_memberships.find_one({"_id": membership["_id"]})
        assert membership is not None
    elif membership.get("role") != TENANT_OWNER_ROLE:
        await database.tenant_memberships.update_one(
            {"_id": membership["_id"]},
            {"$set": {"role": TENANT_OWNER_ROLE, "updated_at": datetime.now(timezone.utc)}},
        )
        membership = await database.tenant_memberships.find_one({"_id": membership["_id"]})
        assert membership is not None

    return {"tenant": tenant, "admin": admin, "membership": membership}
