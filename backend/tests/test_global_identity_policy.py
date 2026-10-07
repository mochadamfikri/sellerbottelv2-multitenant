"""Tests for the global identity migration policy module.

Validates classification of legacy collections into global-identity vs
tenant-owned, and defines the expected behavior for global identity keys
(email, telegram_id) under Owner Decision 1B (Global Unique).
"""

from global_identity_policy import (
    GLOBAL_IDENTITY_COLLECTIONS,
    TENANT_OWNED_COLLECTIONS,
    PLATFORM_COLLECTIONS,
    GLOBAL_IDENTITY_KEYS,
    classify_collection,
    is_global_identity_collection,
    get_global_identity_keys,
    get_uniqueness_scope,
    migration_action,
)


# ---------------------------------------------------------------------------
# 1. Collection classification constants are well-defined
# ---------------------------------------------------------------------------

class TestCollectionSets:
    def test_global_identity_collections_include_bot_users(self):
        assert "bot_users" in GLOBAL_IDENTITY_COLLECTIONS

    def test_global_identity_collections_include_store_customers(self):
        assert "store_customers" in GLOBAL_IDENTITY_COLLECTIONS

    def test_global_identity_collections_do_not_include_products(self):
        assert "products" not in GLOBAL_IDENTITY_COLLECTIONS

    def test_tenant_owned_collections_include_products(self):
        assert "products" in TENANT_OWNED_COLLECTIONS

    def test_tenant_owned_collections_include_inventory_items(self):
        assert "inventory_items" in TENANT_OWNED_COLLECTIONS

    def test_tenant_owned_collections_include_purchases(self):
        assert "purchases" in TENANT_OWNED_COLLECTIONS

    def test_platform_collections_include_settings(self):
        assert "settings" in PLATFORM_COLLECTIONS

    def test_platform_collections_include_counters(self):
        assert "counters" in PLATFORM_COLLECTIONS

    def test_platform_collections_include_admins(self):
        assert "admins" in PLATFORM_COLLECTIONS

    def test_no_collection_appears_in_multiple_categories(self):
        overlap_gi_to = GLOBAL_IDENTITY_COLLECTIONS & TENANT_OWNED_COLLECTIONS
        overlap_gi_pl = GLOBAL_IDENTITY_COLLECTIONS & PLATFORM_COLLECTIONS
        overlap_to_pl = TENANT_OWNED_COLLECTIONS & PLATFORM_COLLECTIONS
        assert not overlap_gi_to, f"global-identity ∩ tenant-owned: {overlap_gi_to}"
        assert not overlap_gi_pl, f"global-identity ∩ platform: {overlap_gi_pl}"
        assert not overlap_to_pl, f"tenant-owned ∩ platform: {overlap_to_pl}"

    def test_every_inventory_collection_has_one_migration_category(self):
        legacy_collections = {
            "admins", "balance_adjustments", "bot2_restock_requests",
            "bot_chat_messages", "bot_message_history", "bot_messages",
            "bot_users", "broadcasts", "counters", "coupons", "daily_recaps",
            "deposits", "discounts", "freeze_log", "gopay_payments",
            "inventory_items", "login_attempts", "outreach_campaigns",
            "outreach_jobs", "post_purchase_actions", "processed_updates",
            "processed_updates_bot2", "products", "promo_campaigns",
            "promo_coupon_redemptions", "promo_coupon_usage", "promo_coupons",
            "promo_events", "promo_suppressions", "prospects", "purchases",
            "required_channels", "reseller_bot_users", "reseller_bots",
            "reseller_commissions", "reseller_contests", "reseller_payments",
            "reseller_payouts", "reseller_updates", "settings", "stock_events",
            "store_customers", "store_email_codes", "tg_accounts", "tg_groups",
            "traffic_sources",
        }
        categories = (
            GLOBAL_IDENTITY_COLLECTIONS
            | TENANT_OWNED_COLLECTIONS
            | PLATFORM_COLLECTIONS
        )
        assert legacy_collections == categories


# ---------------------------------------------------------------------------
# 2. classify_collection returns the correct category string
# ---------------------------------------------------------------------------

class TestClassifyCollection:
    def test_bot_users_classified_as_global_identity(self):
        assert classify_collection("bot_users") == "global_identity"

    def test_store_customers_classified_as_global_identity(self):
        assert classify_collection("store_customers") == "global_identity"

    def test_products_classified_as_tenant_owned(self):
        assert classify_collection("products") == "tenant_owned"

    def test_purchases_classified_as_tenant_owned(self):
        assert classify_collection("purchases") == "tenant_owned"

    def test_inventory_items_classified_as_tenant_owned(self):
        assert classify_collection("inventory_items") == "tenant_owned"

    def test_settings_classified_as_platform(self):
        assert classify_collection("settings") == "platform"

    def test_admins_classified_as_platform(self):
        assert classify_collection("admins") == "platform"

    def test_unknown_collection_classified_as_unknown(self):
        assert classify_collection("nonexistent_collection") == "unknown"


# ---------------------------------------------------------------------------
# 3. is_global_identity_collection helper
# ---------------------------------------------------------------------------

class TestIsGlobalIdentityCollection:
    def test_true_for_bot_users(self):
        assert is_global_identity_collection("bot_users") is True

    def test_true_for_store_customers(self):
        assert is_global_identity_collection("store_customers") is True

    def test_false_for_products(self):
        assert is_global_identity_collection("products") is False

    def test_false_for_unknown_collection(self):
        assert is_global_identity_collection("bogus") is False


# ---------------------------------------------------------------------------
# 4. GLOBAL_IDENTITY_KEYS defines the unique key fields per collection
# ---------------------------------------------------------------------------

class TestGlobalIdentityKeys:
    def test_bot_users_has_telegram_id_key(self):
        assert "telegram_id" in GLOBAL_IDENTITY_KEYS["bot_users"]

    def test_store_customers_has_email_key(self):
        assert "email" in GLOBAL_IDENTITY_KEYS["store_customers"]

    def test_store_customers_has_telegram_id_key(self):
        assert "telegram_id" in GLOBAL_IDENTITY_KEYS["store_customers"]

    def test_keys_dict_only_contains_global_identity_collections(self):
        for collection in GLOBAL_IDENTITY_KEYS:
            assert collection in GLOBAL_IDENTITY_COLLECTIONS, (
                f"{collection} in GLOBAL_IDENTITY_KEYS but not in GLOBAL_IDENTITY_COLLECTIONS"
            )


# ---------------------------------------------------------------------------
# 5. get_global_identity_keys returns key fields for a collection
# ---------------------------------------------------------------------------

class TestGetGlobalIdentityKeys:
    def test_returns_keys_for_bot_users(self):
        keys = get_global_identity_keys("bot_users")
        assert "telegram_id" in keys

    def test_returns_keys_for_store_customers(self):
        keys = get_global_identity_keys("store_customers")
        assert "email" in keys
        assert "telegram_id" in keys

    def test_returns_empty_frozenset_for_tenant_owned(self):
        keys = get_global_identity_keys("products")
        assert keys == frozenset()

    def test_returns_empty_frozenset_for_unknown(self):
        keys = get_global_identity_keys("bogus")
        assert keys == frozenset()


# ---------------------------------------------------------------------------
# 6. get_uniqueness_scope — global keys stay GLOBAL, tenant-owned get TENANT
# ---------------------------------------------------------------------------

class TestGetUniquenessScope:
    def test_bot_users_telegram_id_scope_is_global(self):
        assert get_uniqueness_scope("bot_users", "telegram_id") == "global"

    def test_store_customers_email_scope_is_global(self):
        assert get_uniqueness_scope("store_customers", "email") == "global"

    def test_store_customers_telegram_id_scope_is_global(self):
        assert get_uniqueness_scope("store_customers", "telegram_id") == "global"

    def test_purchases_invoice_id_scope_is_tenant(self):
        assert get_uniqueness_scope("purchases", "invoice_id") == "tenant"

    def test_inventory_items_fingerprint_scope_is_tenant(self):
        assert get_uniqueness_scope("inventory_items", "fingerprint") == "tenant"

    def test_unknown_collection_scope_is_none(self):
        assert get_uniqueness_scope("bogus", "whatever") is None


# ---------------------------------------------------------------------------
# 7. migration_action — what to do during tenant migration for each collection
# ---------------------------------------------------------------------------

class TestMigrationAction:
    def test_global_identity_collection_action_is_share(self):
        action = migration_action("bot_users")
        assert action["action"] == "share"
        assert action["add_tenant_id"] is False

    def test_store_customers_action_is_share(self):
        action = migration_action("store_customers")
        assert action["action"] == "share"
        assert action["add_tenant_id"] is False

    def test_tenant_owned_collection_action_is_assign(self):
        action = migration_action("products")
        assert action["action"] == "assign"
        assert action["add_tenant_id"] is True

    def test_purchases_action_is_assign(self):
        action = migration_action("purchases")
        assert action["action"] == "assign"
        assert action["add_tenant_id"] is True

    def test_platform_collection_action_is_skip(self):
        action = migration_action("settings")
        assert action["action"] == "platform"
        assert action["add_tenant_id"] is False

    def test_unknown_collection_raises_value_error(self):
        try:
            migration_action("nonexistent_xyz")
        except ValueError as exc:
            assert "unknown" in str(exc).lower()
        else:
            raise AssertionError("expected ValueError for unknown collection")

    def test_global_identity_action_preserves_unique_keys(self):
        action = migration_action("bot_users")
        assert "telegram_id" in action["global_unique_keys"]

    def test_tenant_owned_action_has_tenant_scoped_indexes(self):
        action = migration_action("purchases")
        assert action["reindex"] is True
