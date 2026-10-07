"""Per-tenant domain registry for the platform control plane.

Maps hostnames to tenants and purposes (storefront, stock_panel, api).
DNS changes per environment (dev vs production) are data-only: the code
always resolves via this registry, so moving from
`anasyah-store.idse-dev.duckdns.org` to `anasyah-store.idseconnect.my.id`
is a registry edit + DNS change, never a code change.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from tenant_db import resolve_platform_database_name


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domains_collection(db_client):
    name = resolve_platform_database_name(os.environ)
    return db_client[name]["domains"]


async def ensure_domain_indexes(db_client) -> None:
    coll = _domains_collection(db_client)
    await coll.create_index("domain", unique=True)
    await coll.create_index("tenant_id")


async def register_domain(
    db_client,
    *,
    domain: str,
    tenant_id: str | None,
    purpose: str,
    origin: str = "owner_subdomain",
    created_by: str | None = None,
) -> dict[str, Any]:
    """Register or update a domain mapping. Domain is stored lowercase."""
    domain = domain.strip().lower()
    if not domain or "." not in domain:
        raise ValueError("Domain tidak valid.")
    if purpose not in ("storefront", "stock_panel", "config_panel", "api", "platform"):
        raise ValueError(f"Purpose tidak dikenal: {purpose}")
    coll = _domains_collection(db_client)
    now = _utcnow_iso()
    doc = {
        "domain": domain,
        "tenant_id": tenant_id,
        "purpose": purpose,
        "origin": origin,
        "verified": True,
        "verified_at": now,
        "created_at": now,
        "created_by": created_by,
    }
    await coll.update_one({"domain": domain}, {"$set": doc}, upsert=True)
    return doc


async def resolve_domain(db_client, host: str) -> dict[str, Any] | None:
    """Resolve a Host header value to its domain registration, if any."""
    host = (host or "").strip().lower().split(":")[0]
    if not host:
        return None
    coll = _domains_collection(db_client)
    return await coll.find_one({"domain": host})


async def list_domains(db_client, tenant_id: str | None = None) -> list[dict[str, Any]]:
    coll = _domains_collection(db_client)
    query: dict[str, Any] = {}
    if tenant_id:
        query["tenant_id"] = tenant_id
    cursor = coll.find(query).sort("domain", 1)
    return await cursor.to_list(length=None)


async def remove_domain(db_client, domain: str) -> bool:
    coll = _domains_collection(db_client)
    result = await coll.delete_one({"domain": domain.strip().lower()})
    return result.deleted_count > 0
