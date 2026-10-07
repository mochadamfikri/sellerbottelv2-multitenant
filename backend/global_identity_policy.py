"""Global identity migration policy for legacy collection classification.

Implements Owner Decision 1B (Global Unique Identity):
- Email and Telegram ID are globally unique across all tenants
- Global identity collections (bot_users, store_customers) are SHARED, not duplicated
- Tenant-owned collections (products, purchases, etc.) get tenant_id assigned
- Platform collections (settings, counters, admins) remain unchanged

This is a pure policy module with NO database writes or side effects.
"""

from typing import FrozenSet

# ---------------------------------------------------------------------------
# Collection Classification — Owner Decision 1B
# ---------------------------------------------------------------------------

# Global identity: shared across tenants, unique keys remain globally unique
GLOBAL_IDENTITY_COLLECTIONS: FrozenSet[str] = frozenset({
    "bot_users",         # telegram_id globally unique
    "store_customers",   # email, telegram_id globally unique
})

# Tenant-owned: business data that belongs to a single tenant
TENANT_OWNED_COLLECTIONS: FrozenSet[str] = frozenset({
    # Financial records
    "balance_adjustments",
    "deposits",
    "gopay_payments",
    "purchases",
    "reseller_commissions",
    "reseller_payments",
    "reseller_payouts",
    
    # Catalog and inventory
    "products",
    "inventory_items",
    "login_attempts",
    "stock_events",
    
    # Communications
    "bot_chat_messages",
    "bot_message_history",
    "bot_messages",
    "broadcasts",
    "outreach_campaigns",
    "outreach_jobs",
    "promo_suppressions",
    
    # Promotions
    "coupons",
    "discounts",
    "promo_campaigns",
    "promo_coupon_redemptions",
    "promo_coupon_usage",
    "promo_coupons",
    "promo_events",
    
    # Reseller program
    "reseller_bot_users",
    "reseller_bots",
    "reseller_contests",
    "reseller_updates",
    
    # Customer lifecycle
    "daily_recaps",
    "freeze_log",
    "post_purchase_actions",
    "prospects",
    "required_channels",
    "store_email_codes",
    "traffic_sources",
    
    # Telegram state
    "bot2_restock_requests",
    "processed_updates",
    "processed_updates_bot2",
    "tg_accounts",
    "tg_groups",
})

# Platform-level: control plane data, not tenant-specific
PLATFORM_COLLECTIONS: FrozenSet[str] = frozenset({
    "admins",       # Platform administrators
    "settings",     # Global application settings
    "counters",     # ID sequence generators
})

# Global identity key fields per collection (Owner Decision 1B)
GLOBAL_IDENTITY_KEYS: dict[str, FrozenSet[str]] = {
    "bot_users": frozenset({"telegram_id"}),
    "store_customers": frozenset({"email", "telegram_id"}),
}


# ---------------------------------------------------------------------------
# Policy Functions
# ---------------------------------------------------------------------------

def classify_collection(name: str) -> str:
    """Classify a collection as global_identity, tenant_owned, platform, or unknown.
    
    Args:
        name: Collection name
        
    Returns:
        One of: "global_identity", "tenant_owned", "platform", "unknown"
    """
    if name in GLOBAL_IDENTITY_COLLECTIONS:
        return "global_identity"
    if name in TENANT_OWNED_COLLECTIONS:
        return "tenant_owned"
    if name in PLATFORM_COLLECTIONS:
        return "platform"
    return "unknown"


def is_global_identity_collection(name: str) -> bool:
    """Check if a collection contains global identity records.
    
    Args:
        name: Collection name
        
    Returns:
        True if collection is a global identity collection
    """
    return name in GLOBAL_IDENTITY_COLLECTIONS


def get_global_identity_keys(name: str) -> FrozenSet[str]:
    """Get the globally unique key fields for a collection.
    
    Args:
        name: Collection name
        
    Returns:
        Frozenset of field names that are globally unique, empty if none
    """
    return GLOBAL_IDENTITY_KEYS.get(name, frozenset())


def get_uniqueness_scope(collection: str, field: str) -> str | None:
    """Determine if a field's uniqueness is global or tenant-scoped.
    
    Args:
        collection: Collection name
        field: Field name
        
    Returns:
        "global" if field is globally unique across all tenants
        "tenant" if field is unique within a tenant only
        None if collection is unknown or field is not a unique key
    """
    category = classify_collection(collection)
    
    if category == "unknown":
        return None
    
    # Global identity keys are globally unique (Owner Decision 1B)
    if field in get_global_identity_keys(collection):
        return "global"
    
    # Tenant-owned collections have tenant-scoped uniqueness
    if category == "tenant_owned":
        return "tenant"
    
    return None


def migration_action(name: str) -> dict:
    """Determine the migration action for a collection.
    
    Args:
        name: Collection name
        
    Returns:
        Dictionary with:
        - action: "share" (global identity), "assign" (add tenant_id), or "platform"
        - add_tenant_id: bool, whether to add tenant_id field
        - global_unique_keys: frozenset of globally unique fields
        - reindex: bool, whether indexes need rebuilding
        
    Raises:
        ValueError: If collection is unknown
    """
    category = classify_collection(name)
    
    if category == "unknown":
        raise ValueError(f"Unknown collection: {name}")
    
    if category == "global_identity":
        # Global identity: shared across tenants, preserve global uniqueness
        return {
            "action": "share",
            "add_tenant_id": False,
            "global_unique_keys": get_global_identity_keys(name),
            "reindex": False,
        }
    
    if category == "tenant_owned":
        # Tenant-owned: assign tenant_id, rebuild indexes for tenant scoping
        return {
            "action": "assign",
            "add_tenant_id": True,
            "global_unique_keys": frozenset(),
            "reindex": True,
        }
    
    if category == "platform":
        # Platform: no changes needed
        return {
            "action": "platform",
            "add_tenant_id": False,
            "global_unique_keys": frozenset(),
            "reindex": False,
        }
    
    # Should never reach here due to unknown check above
    raise ValueError(f"Unhandled category: {category}")
