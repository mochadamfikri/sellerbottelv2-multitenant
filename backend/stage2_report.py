"""Stage 2 dry-run verification report generator.

Produces read-only analysis of tenant database provisioning without migrating documents.
"""

from datetime import datetime, timezone
from typing import Any


ESSENTIAL_COLLECTIONS = {
    "settings",
    "_meta",
    "products",
    "inventory_items",
    "purchases",
    "deposits",
    "store_customers",
    "bot_users",
}


def generate_verification_report(
    source_counts: dict[str, int],
    tenant_id: str,
    tenant_db_name: str,
    tenant_collections: list[str],
    tenant_indexes: dict[str, list[str]],
    clock: datetime | None = None,
    mongo_version: str = "unknown",
) -> dict[str, Any]:
    """Generate read-only verification report for Stage 2 tenant provisioning.
    
    Args:
        source_counts: Document counts from source database collections
        tenant_id: Target tenant identifier
        tenant_db_name: Tenant database name
        tenant_collections: List of initialized collections in tenant database
        tenant_indexes: Index names per collection in tenant database
        clock: Optional timestamp for report generation
        mongo_version: MongoDB version string
    
    Returns:
        Verification report dictionary with source/tenant state and audit metadata
    """
    if clock is None:
        clock = datetime.now(timezone.utc)
    
    tenant_collections_set = set(tenant_collections)
    missing = ESSENTIAL_COLLECTIONS - tenant_collections_set
    essential_present = len(missing) == 0
    
    return {
        "source_database": "sellerbottel_dev",
        "source_counts": source_counts,
        "tenant_id": tenant_id,
        "tenant_database": tenant_db_name,
        "tenant_collections": tenant_collections,
        "tenant_collections_initialized": len(tenant_collections),
        "tenant_indexes": tenant_indexes,
        "essential_collections_present": essential_present,
        "missing_collections": sorted(missing),
        "read_only": True,
        "documents_migrated": 0,
        "verification_type": "read_only",
        "status": "verification_only",
        "generated_at": clock.isoformat(),
        "mongo_version": mongo_version,
    }
