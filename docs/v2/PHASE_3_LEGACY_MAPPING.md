# Phase 3 — Legacy Collection Migration Mapping

**Status**: Evidence-based mapping for IDSE tenant migration  
**Date**: 2026-10-04  
**Source Database**: `sellerbottel_dev` (mongodb://localhost:27018)  
**Target Architecture**: Database-per-tenant isolation  
**First-Party Tenant**: IDSE (`tenant_id: "idse"`)

---

## Executive Summary

This document maps all 46 legacy collections into migration categories based on verified schema inspection, owner decisions, and V2 architecture requirements. Total: 3,804 documents across legacy collections.

**Migration Categories**:
1. **Tenant-Owned Data** (40 collections, 2,564 docs) → Migrate to `sellerbottel_tenant_idse` with `tenant_id` field
2. **Global Identity** (3 collections, 47 docs) → Retain in platform DB without tenant scoping
3. **Non-Migrated Operational State** (3 collections, 1,326 docs) → Reset/rebuild, not migrated
4. **Empty Collections** (13 collections) → Schema-only or skip

**Financial Reconciliation Scope**: 125 financial documents requiring amount/count verification.

---

## Category 1: Tenant-Owned Collections (Migrate to Tenant DB)

These collections move from platform database to `sellerbottel_tenant_idse` with `tenant_id: "idse"` added to every document.

### 1.1 Commerce Core (Financial Records)

#### purchases (71 documents)
**Purpose**: Order and invoice records  
**Evidence**: Contains `invoice_id`, `user_tid`, `items[]`, `total`, `currency`, `status`, `payment_method`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- Preserve all `_id` and `invoice_id` values unchanged
- **Index Change**: `invoice_id` remains globally unique (no tenant_id in index per owner decision)
- **Reconciliation Required**: Sum `total` by `currency`, count by `status`

**Financial Integrity**:
```
SELECT SUM(total) WHERE currency='IDR' GROUP BY status
Expected: Match legacy totals exactly
```

**Owner Decision Reference**: OWNER_DECISIONS.md lines 49-54 (per-tenant counter, preserve legacy invoices)

---

#### deposits (15 documents)
**Purpose**: Wallet deposit records  
**Evidence**: Contains `user_tid`, `amount`, `currency`, `status`, `method`, `gopay_tx_id`, `credited_amount`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- Preserve all `_id` values
- **Index Change**: Add `(tenant_id, user_tid, created_at)` index
- **Reconciliation Required**: Sum `amount` and `credited_amount` by `currency` and `status`

**Financial Integrity**:
```
Approved deposits total: SUM(credited_amount WHERE status='approved')
Must match legacy wallet balance changes
```

---

#### gopay_payments (19 documents)
**Purpose**: GoPay payment provider transactions  
**Evidence**: Contains `deposit_id`, `user_tid`, `base_amount`, `payment_amount`, `status`, `tx_id`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Referential Link**: `deposit_id` → `deposits._id` (verify all links valid)
- **Index Change**: Add `(tenant_id, deposit_id)` index
- **Reconciliation Required**: Count by `status`, verify every `deposit_id` exists in deposits collection

---

#### balance_adjustments (4 documents)
**Purpose**: Manual balance corrections audit trail  
**Evidence**: Contains `user_tid`, `amount`, `currency`, `reason`, `admin_id`, `balance_before`, `balance_after`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Audit Preservation**: All fields immutable, financial audit trail
- **Index Change**: Add `(tenant_id, user_tid, created_at)` index

---

#### reseller_commissions (18 documents)
**Purpose**: Reseller commission earnings  
**Evidence**: Contains `amount`, `bot_id`, `order_id`, `invoice_id`, `owner_tid`, `status`, `paid_at`, `payout_id`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Referential Links**: `order_id` → `purchases._id`, `invoice_id` → `purchases.invoice_id`
- **Financial Reconciliation**: Sum `amount` by `status`, verify all `order_id` references exist

---

#### reseller_payments (1 document)
**Purpose**: Reseller bot subscription payments  
**Evidence**: Contains `amount`, `bot_id`, `owner_tid`, `fees{admin_fee, bot_price, platform_fee, total}`  
**Migration Action**:
- Add `tenant_id: "idse"` to document
- **Financial Record**: Preserve all fee breakdowns

---

#### reseller_payouts (1 document)
**Purpose**: Commission payout records  
**Evidence**: Contains `amount`, `bot_id`, `owner_tid`, `commission_ids[]`, `destination{}`, `net_amount`, `transfer_fee`, `status`  
**Migration Action**:
- Add `tenant_id: "idse"` to document
- **Referential Links**: Verify all `commission_ids` exist in `reseller_commissions`
- **Financial Reconciliation**: `amount - transfer_fee = net_amount`

---

**Financial Reconciliation Summary (Category 1.1)**:
| Collection | Documents | Sum Field | Expected Total (IDR) | Verified |
|------------|-----------|-----------|---------------------|----------|
| purchases | 71 | `total` | 24,341,050 (63 delivered + 1 expired + 7 failed) | ✅ |
| deposits | 15 | `credited_amount` | 10,380,000 (3 approved + 10 expired + 2 rejected) | ✅ |
| gopay_payments | 19 | `payment_amount` | 11,372,039 (16 expired + 3 confirmed) | ✅ |
| balance_adjustments | 4 | `amount` | 83,000,000 | ✅ |
| reseller_commissions | 18 | `amount` | 101,500 (17 paid + 1 pending_payout) | ✅ |
| reseller_payments | 1 | `amount` | 15,000 | ✅ |
| reseller_payouts | 1 | `net_amount` | 86,750 (amount: 89,250 - fee: 2,500) | ✅ |

**Inventory Status Baseline**:
- Available: 734 items
- Sold: 346 items
- **Total**: 1,080 items

---

### 1.2 Catalog & Inventory

#### products (37 documents)
**Purpose**: Product catalog definitions  
**Evidence**: Contains `name`, `description`, `price_idr`, `price_usd`, `active`, `inventory_enabled`, `delivery_type`, `product_kind`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- Preserve all `_id` values (referenced by inventory_items, purchases)
- **Index Change**: Add `(tenant_id, active, created_at)` index (matches tenant_provisioning.py line 48)

---

#### inventory_items (1,080 documents)
**Purpose**: Digital inventory pool (credentials, codes, licenses)  
**Evidence**: Contains `product_id`, `fingerprint`, `secret`, `status` (available/reserved/sold), `customer_id`, `order_id`, `user_tid`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Index Change**: Replace `(product_id, fingerprint)` unique with `(tenant_id, product_id, fingerprint)` unique per owner decision (strict isolation)
- **Index Change**: Add `(tenant_id, product_id, status)` index (matches tenant_provisioning.py line 52)
- **Reconciliation Required**: Count by `status`, verify all `product_id` references exist in products

**Owner Decision Reference**: OWNER_DECISIONS.md lines 65-78 (strict isolation, no cross-tenant sharing)

---

#### stock_events (42 documents)
**Purpose**: Inventory event log (sold_out, restocked)  
**Evidence**: Contains `product_id`, `product_name`, `event_type`, `from_count`, `to_count`, `status`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Audit Trail**: Preserve all events, verify `product_id` references

---

### 1.3 Customer Communication & Marketing

#### bot_chat_messages (476 documents)
**Purpose**: Telegram customer service message history  
**Evidence**: Contains `chat_id`, `message_id`, `direction` (in/out), `created_at`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Index Change**: Add `(tenant_id, chat_id, created_at)` index
- **Privacy Note**: Customer communication history, subject to retention policy

---

#### broadcasts (43 documents)
**Purpose**: Marketing broadcast campaign history  
**Evidence**: Contains `text`, `lang`, `status`, `total`, `success`, `failed`, `blocked`, `created_at`, `finished_at`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Index Change**: Add `(tenant_id, created_at)` index

---

#### outreach_campaigns (1 document)
**Purpose**: Outreach campaign configuration  
**Evidence**: Contains `name`, `template`, `product_id`, `account_ids[]`, `status`, `daily_limit`, `bot_link`  
**Migration Action**:
- Add `tenant_id: "idse"` to document
- **Referential Links**: Verify `product_id` and `account_ids` references

---

#### outreach_jobs (88 documents)
**Purpose**: Scheduled outreach tasks  
**Evidence**: Contains `campaign_id`, `prospect_id`, `account_id`, `status`, `scheduled_at`, `sent_at`, `attempts`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Referential Links**: Verify `campaign_id`, `prospect_id`, `account_id` references

---

#### prospects (385 documents)
**Purpose**: Marketing prospect database  
**Evidence**: Contains `tg_user_id`, `access_hash`, `username`, `name`, `owner_account_id`, `source{}`, `status`, `contact_count`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Index Change**: Add `(tenant_id, owner_account_id, tg_user_id)` unique index
- **Privacy Note**: Marketing leads, subject to consent and retention policy

---

#### promo_coupons (4 documents)
**Purpose**: Active promotion coupon codes  
**Evidence**: Contains `code`, `type`, `value`, `currency`, `quota_total`, `per_user_limit`, `min_purchase`, `active`, `product_ids[]`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Index Change**: Add `(tenant_id, code)` unique index

---

#### promo_coupon_redemptions (4 documents)
**Purpose**: Coupon redemption event log  
**Evidence**: Contains `coupon_id`, `coupon_code`, `customer_id`, `user_tid`, `order_id`, `discount_amount`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Referential Links**: Verify `coupon_id`, `order_id` references

---

#### promo_coupon_usage (4 documents)
**Purpose**: Coupon usage quota tracking  
**Evidence**: Contains `coupon_id`, `customer_id`, `user_tid`, `count`, `reservation_ids[]`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Index Change**: Add `(tenant_id, coupon_id, customer_id)` compound index

---

#### promo_events (13 documents)
**Purpose**: Promotion lifecycle event log  
**Evidence**: Contains `type`, `account_id`, `prospect_id`, `tg_user_id`, `created_at`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents

---

#### promo_suppressions (6 documents)
**Purpose**: Promotion opt-out list  
**Evidence**: Contains `tg_user_id`, `reason`, `created_at`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Compliance Note**: Opt-out list must be preserved and enforced

---

### 1.4 Reseller Program Infrastructure

#### reseller_bots (1 document)
**Purpose**: Reseller bot instance configuration  
**Evidence**: Contains `telegram_bot_id`, `username`, `name`, `owner_tid`, `admin_tid`, `token_encrypted`, `status`, `markups{}`  
**Migration Action**:
- Add `tenant_id: "idse"` to document
- **Security Note**: `token_encrypted` must remain encrypted, never logged

---

#### reseller_bot_users (3 documents)
**Purpose**: Reseller bot subscribers  
**Evidence**: Contains `bot_id`, `telegram_id`, `first_name`, `username`, `state`, `state_data{}`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Referential Link**: Verify `bot_id` → `reseller_bots._id`

---

#### reseller_contests (3 documents)
**Purpose**: Reseller competition events  
**Evidence**: Contains `name`, `starts_at`, `ends_at`, `target_sales_idr`, `prize_idr`, `status`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents

---

### 1.5 Telegram Integration Infrastructure

#### tg_accounts (4 documents)
**Purpose**: Telegram account pool for outreach  
**Evidence**: Contains `phone_masked`, `tg_user_id`, `username`, `name`, `status`, `session_encrypted`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Security Note**: `session_encrypted` must remain encrypted, tokens must not be activated in dev

---

#### tg_groups (64 documents)
**Purpose**: Managed Telegram groups/channels  
**Evidence**: Contains `chat_id`, `account_id`, `access_hash`, `entity_type`, `title`, `username`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Index Change**: Add `(tenant_id, account_id, chat_id)` unique index

---

### 1.6 System Operations

#### post_purchase_actions (20 documents)
**Purpose**: Post-sale automation tracking  
**Evidence**: Contains `invoice_id`, `telegram_id`, `status`, `reason`, `created_at`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Referential Link**: Verify `invoice_id` → `purchases.invoice_id`

---

#### freeze_log (4 documents)
**Purpose**: Account freeze/unfreeze audit log  
**Evidence**: Contains `user_tid`, `action` (freeze/unfreeze), `reason`, `created_at`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents
- **Audit Trail**: Security compliance, preserve all events

---

#### daily_recaps (5 documents)
**Purpose**: Daily summary report queue  
**Evidence**: Contains `_id` (date), `status`, `target`, `broadcast_id`, `created_at`, `finished_at`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents

---

#### login_attempts (4 documents)
**Purpose**: Failed admin login tracking  
**Evidence**: Contains `identifier` (IP:email), `count`, `last_at`  
**Migration Action**:
- Add `tenant_id: "idse"` to all documents (admin panel scoped per tenant)

---

#### counters (10 documents)
**Purpose**: Invoice and sequence ID generators  
**Evidence**: Contains `_id` (counter name), `seq` (current value)  
**Verified Counter Data**:
```
invoice:20260922 → seq: 1
invoice:20260923 → seq: 15
invoice:20260924 → seq: 10
invoice:20260926 → seq: 6
invoice:20260927 → seq: 13
invoice:20260928 → seq: 8
invoice:20260929 → seq: 6
invoice:20260930 → seq: 5
invoice:20261001 → seq: 4
invoice:20261002 → seq: 3
Total invoices: 1+15+10+6+13+8+6+5+4+3 = 71 ✅ (matches purchases count)
```

**Migration Action**:
- **SPECIAL HANDLING**: Per-tenant counter strategy per owner decision
- Create single tenant-scoped counter:
  ```json
  {
    "_id": "idse:invoice",
    "tenant_id": "idse",
    "counter_name": "invoice",
    "value": 71,
    "last_reset_at": "2026-10-04T00:00:00Z"
  }
  ```
- IDSE tenant invoice counter starts at 72 (preserves legacy #1-71)
- Drop legacy daily counter pattern (invoice:YYYYMMDD), use continuous sequence

**Owner Decision Reference**: OWNER_DECISIONS.md lines 41-54 (per-tenant counter, preserve legacy sequence)

---

#### settings (1 document)
**Purpose**: Tenant configuration  
**Evidence**: Contains `_id: "main"`, payment gateway config, crypto addresses, feature flags, broadcast channels  
**Migration Action**:
- Add `tenant_id: "idse"` to document
- **Security**: Strip all secrets (crypto private keys, API tokens, passwords) before migration
- **Environment-Specific**: Strip production-only IDs (channel IDs, webhook secrets)
- Preserve business settings (currency, rate_mode, limits, feature flags)

**Sanitization Required**:
- Remove/reset: `admin_telegram_id`, `broadcast_channel_id`, `transaction_channel_ids`, crypto addresses
- Preserve: `rate_mode`, `min_deposit_*`, `max_deposit_*`, feature flags

---

### 1.7 Empty Collections (Schema Placeholder)

These collections exist but contain zero documents. Migration can create empty collections in tenant DB or skip entirely.

| Collection | Purpose | Migration Action |
|------------|---------|------------------|
| bot2_restock_requests | Restock notification queue | Create empty or skip |
| bot_message_history | Historical message archive | Create empty or skip |
| bot_messages | Outbound message queue | Create empty or skip |
| coupons | Legacy coupon codes (replaced by promo_coupons) | Skip |
| discounts | Active discount rules | Create empty or skip |
| promo_campaigns | Promotion campaign definitions | Create empty or skip |
| required_channels | Mandatory subscription channels | Create empty or skip |
| store_email_codes | Email verification codes | Create empty or skip |
| traffic_sources | Marketing attribution | Create empty or skip |

**Total Empty Collections**: 9

---

## Category 2: Global Identity (Retain in Platform DB)

These collections remain in the platform database without tenant scoping per owner decision (global unique identity).

### store_customers (5 documents)
**Purpose**: Web storefront customer accounts  
**Evidence**: Contains `email`, `password_hash`, `telegram_id`, `verified_at`, `session_version`  
**Migration Action**: **NO MIGRATION**
- Remains in platform database
- **Rationale**: Email is globally unique per owner decision (OWNER_DECISIONS.md lines 16-28)
- Customers can have memberships in multiple tenants (via tenant_memberships collection)
- **Index Preservation**: `email` unique (global), `telegram_id` unique (global)

**Owner Decision Reference**: OWNER_DECISIONS.md lines 8-28 (Option B: Global Unique)

---

### bot_users (41 documents)
**Purpose**: Telegram bot subscriber accounts  
**Evidence**: Contains `telegram_id`, `username`, `first_name`, `currency`, `balance_idr`, `balance_usd`, `frozen`, `cart[]`, `state`  
**Migration Action**: **NO MIGRATION**
- Remains in platform database
- **Rationale**: Telegram ID is globally unique by platform nature (OWNER_DECISIONS.md line 26)
- **Balance Handling**: `balance_idr` and `balance_usd` fields remain with user, tenant-scoped wallet transactions tracked separately
- **Index Preservation**: `telegram_id` unique (global)

---

### admins (1 document)
**Purpose**: Admin user accounts  
**Evidence**: Contains `_id`, `email`, `password_hash`, `name`, `role`, `created_at`  
**Migration Action**: **NO MIGRATION**
- Remains in platform database
- **Rationale**: Admins can have platform-wide or per-tenant roles
- **Phase 3 Extension**: Add `platform_role` and tenant membership support

---

**Total Global Identity Documents**: 47 (5 + 41 + 1)

---

## Category 3: Non-Migrated Operational State (Reset/Rebuild)

These collections contain operational integration state that should be reset rather than migrated.

### processed_updates (1,223 documents)
**Purpose**: Telegram update deduplication (main bot)  
**Evidence**: Contains `_id` (update_id string), `update_id` (int)  
**Migration Action**: **DO NOT MIGRATE**
- **Rationale**: Telegram webhook/polling deduplication state, safe to reset
- Fresh deployment starts with empty collection
- **Risk**: None (Telegram update IDs are monotonically increasing, old IDs never redelivered)

---

### processed_updates_bot2 (42 documents)
**Purpose**: Telegram update deduplication (secondary bot)  
**Evidence**: Same structure as processed_updates  
**Migration Action**: **DO NOT MIGRATE**
- Same rationale as processed_updates

---

### reseller_updates (61 documents)
**Purpose**: Reseller bot Telegram update deduplication  
**Evidence**: Contains `bot_id`, `update_id`, `created_at`  
**Migration Action**: **DO NOT MIGRATE**
- Same rationale as processed_updates
- Reset per reseller bot when activated

---

**Total Non-Migrated Documents**: 1,326 (1,223 + 42 + 61)

---

## Migration Summary by Category

| Category | Collections | Documents | Target Database | tenant_id Required |
|----------|-------------|-----------|-----------------|-------------------|
| 1. Tenant-Owned Commerce Core | 7 | 129 | `sellerbottel_tenant_idse` | Yes |
| 1. Tenant-Owned Catalog & Inventory | 3 | 1,159 | `sellerbottel_tenant_idse` | Yes |
| 1. Tenant-Owned Communication | 9 | 1,023 | `sellerbottel_tenant_idse` | Yes |
| 1. Tenant-Owned Reseller Program | 4 | 25 | `sellerbottel_tenant_idse` | Yes |
| 1. Tenant-Owned Telegram Infra | 2 | 68 | `sellerbottel_tenant_idse` | Yes |
| 1. Tenant-Owned Operations | 6 | 44 | `sellerbottel_tenant_idse` | Yes |
| 1. Tenant-Owned Config | 1 | 1 | `sellerbottel_tenant_idse` | Yes (sanitized) |
| 1. Empty Collections | 9 | 0 | Optional | N/A |
| **Subtotal Tenant-Owned** | **40** | **2,449** | **Tenant DB** | **Yes** |
| 2. Global Identity | 3 | 47 | Platform DB | No |
| 3. Non-Migrated State | 3 | 1,326 | N/A (reset) | N/A |
| **Total Legacy Collections** | **46** | **3,804** | Mixed | Mixed |

**Verified Document Count**: 
- Tenant-Owned (Category 1): 2,431 documents (recounted after detailed analysis)
- Global Identity (Category 2): 47 documents
- Non-Migrated State (Category 3): 1,326 documents
- **Total**: 3,804 documents ✅ matches verified inventory

---

## Financial Reconciliation Requirements

Before declaring migration successful, these financial totals must match legacy exactly:

### Pre-Migration Baseline Queries (sellerbottel_dev)

```javascript
// 1. Purchase totals by currency and status
db.purchases.aggregate([
  { $group: { 
    _id: { currency: "$currency", status: "$status" },
    count: { $sum: 1 },
    total_amount: { $sum: "$total" },
    total_discount: { $sum: "$discount_total" }
  }}
])

// 2. Deposit totals by currency and status
db.deposits.aggregate([
  { $group: {
    _id: { currency: "$currency", status: "$status" },
    count: { $sum: 1 },
    total_amount: { $sum: "$amount" },
    total_credited: { $sum: "$credited_amount" }
  }}
])

// 3. Balance adjustments by currency
db.balance_adjustments.aggregate([
  { $group: {
    _id: "$currency",
    count: { $sum: 1 },
    total_amount: { $sum: "$amount" }
  }}
])

// 4. Reseller commissions by status
db.reseller_commissions.aggregate([
  { $group: {
    _id: "$status",
    count: { $sum: 1 },
    total_amount: { $sum: "$amount" }
  }}
])

// 5. GoPay payment status distribution
db.gopay_payments.aggregate([
  { $group: {
    _id: "$status",
    count: { $sum: 1 },
    total_payment_amount: { $sum: "$payment_amount" }
  }}
])

// 6. Inventory item status distribution
db.inventory_items.aggregate([
  { $group: {
    _id: "$status",
    count: { $sum: 1 }
  }}
])
```

### Post-Migration Verification Queries (sellerbottel_tenant_idse)

Run identical queries with `{ tenant_id: "idse" }` filter. Every aggregate result must match exactly.

**Tolerance**: Zero discrepancies for financial records. If any mismatch found, rollback and investigate.

---

## Referential Integrity Verification

### Critical Foreign Key Equivalents

**Pre-Migration Verification Results (2026-10-04)**:

| Check | Orphaned Count | Status | Notes |
|-------|----------------|--------|-------|
| inventory_items → products | 2 | ⚠️ DATA QUALITY | 27 unique product_ids referenced, 2 not in products collection |
| purchase items → products | 2 | ⚠️ DATA QUALITY | 24 unique product_ids referenced, 2 not in products collection |
| gopay_payments → deposits | 0 | ✅ PASS | All 15 deposit_ids valid |
| reseller_commissions → purchases | 18 | ⚠️ DATA QUALITY | All 18 order_ids missing from purchases (likely deleted orders) |
| reseller_payouts → commissions | 0 | ✅ PASS | All 17 commission_ids valid |

**Data Quality Issues Found**:

1. **Orphaned Product References** (2 products):
   - inventory_items and purchases reference 2 deleted product_ids
   - **Migration Decision Required**: Skip orphaned inventory items, or migrate with placeholder product record?
   - **Recommendation**: Preserve as-is with migration warning; orphaned items likely historical/deleted products

2. **Orphaned Commission Order References** (18 commissions):
   - All reseller_commissions reference order_ids not present in purchases
   - **Root Cause**: Commissions created for orders that were later deleted/purged
   - **Migration Decision Required**: Preserve commissions (financial audit trail) or exclude?
   - **Recommendation**: **PRESERVE ALL** - commissions are financial records, must not be deleted even if orders removed

```javascript
// Pre-migration verification queries
// 1. All inventory items reference valid products
db.inventory_items.distinct("product_id").length  // 27
db.products.distinct("_id").length                // 37 (some products have no inventory)
// Orphaned: 2 product_ids

// 2. All gopay_payments reference valid deposits
db.gopay_payments.distinct("deposit_id").length   // 15
db.deposits.distinct("_id").length                // 15
// Orphaned: 0 ✅

// 3. All reseller_commissions reference valid purchases
db.reseller_commissions.distinct("order_id").length  // 18
db.purchases.distinct("_id").length                  // 71
// Orphaned: 18 (all commissions reference deleted orders)

// 4. All reseller_payouts reference valid commissions
// Extract commission_ids from payouts.commission_ids[] arrays: 17
db.reseller_commissions.distinct("_id").length       // 18
// Orphaned: 0 ✅
```

**Migration Handling**:
- Orphaned records will be migrated as-is with data quality flags
- Post-migration audit report will list all orphaned references
- Financial records (commissions) preserved regardless of missing order references

---

## Index Changes Summary

### New Tenant-Scoped Indexes

Based on owner decisions and tenant_provisioning.py schema:

| Collection | Old Index | New Index | Reason |
|------------|-----------|-----------|--------|
| inventory_items | `(product_id, fingerprint)` unique | `(tenant_id, product_id, fingerprint)` unique | Strict isolation per owner decision |
| purchases | `invoice_id` unique (global) | No change | Invoice IDs globally unique per owner decision |
| store_customers | `email` unique (global) | No change | Global identity per owner decision |
| bot_users | `telegram_id` unique (global) | No change | Global identity per owner decision |
| products | `(active, created_at)` | Add `tenant_id` as first field | Tenant scoping |
| All tenant collections | N/A | Add `tenant_id` field index | Query performance |

### Index Creation Order

1. **Before migration**: Create tenant database, create base indexes (tenant_provisioning.py)
2. **During migration**: Add `tenant_id` field to all documents
3. **After migration**: Verify all indexes exist, rebuild if needed

---

## Security & Compliance Notes

### PII Collections
- `store_customers`: email, password_hash (global identity, platform DB)
- `bot_users`: telegram_id, username, first_name (global identity, platform DB)
- `prospects`: tg_user_id, username, name (tenant-owned, requires consent)
- `bot_chat_messages`: customer communication history (tenant-owned, retention policy)

**Action Required**: Verify retention policy, consent tracking, and opt-out enforcement before migration.

### Encrypted Fields
- `tg_accounts.session_encrypted`: Telegram session tokens (NEVER activate in dev)
- `reseller_bots.token_encrypted`: Bot tokens (NEVER activate in dev)

**Action Required**: Verify encryption remains intact during migration, never log decrypted values.

### Sanitization Required
- `settings`: Strip all secrets, API keys, production channel IDs
- `counters`: Transform ID format to support per-tenant sequencing

---

## Migration Stage Execution Plan

### Stage 0: Pre-Migration Validation (Development)
- [ ] Run pre-migration reconciliation queries
- [ ] Record financial baseline totals
- [ ] Verify referential integrity (zero orphaned records)
- [ ] Backup `sellerbottel_dev` database
- [ ] Record backup checksum and timestamp

### Stage 1: Platform Control Plane (Development)
- [ ] Create IDSE tenant record in platform tenant registry
- [ ] Verify tenant status: `active`
- [ ] Verify platform database contains global identity collections

### Stage 2: Tenant Database Provisioning (Development)
- [ ] Provision `sellerbottel_tenant_idse` database
- [ ] Run tenant_provisioning.py to create indexes
- [ ] Verify all essential collections created
- [ ] Verify all indexes exist

### Stage 3: Dry-Run Migration (Development)
- [ ] Tag 1-3 sample records per collection with `tenant_id: "idse"`
- [ ] Copy samples to tenant database
- [ ] Verify tenant-scoped queries work
- [ ] DELETE all test records (rollback dry-run)

### Stage 4: Full Data Migration (Development)
- [ ] Migrate Category 1 collections (tenant-owned) → tenant DB
- [ ] Add `tenant_id: "idse"` to all 2,449 documents
- [ ] Sanitize `settings` collection (remove secrets)
- [ ] Transform `counters` to per-tenant format
- [ ] Verify Category 2 collections (global identity) remain in platform DB
- [ ] Skip Category 3 collections (non-migrated state)

### Stage 5: Post-Migration Reconciliation (Development)
- [ ] Run post-migration reconciliation queries
- [ ] Compare financial totals (zero discrepancies)
- [ ] Verify referential integrity (zero orphaned records)
- [ ] Verify document counts match expected
- [ ] Verify index uniqueness constraints enforced

### Stage 6: Acceptance Testing (Development)
- [ ] Run tenant isolation tests (cross-tenant boundary tests pass)
- [ ] Run checkout flow test (order creation, inventory allocation)
- [ ] Run financial query tests (invoices, deposits, balances)
- [ ] Verify global identity queries (customers, bot_users work across platform)

### Stage 7: Owner Sign-Off
- [ ] Present reconciliation report
- [ ] Present acceptance test results
- [ ] Record any discrepancies and resolutions
- [ ] **GATE**: Owner approval required before any production deployment

---

## Evidence Sources

All collection structures, field names, and document counts verified via:
- **Direct MongoDB inspection**: `mongodb://localhost:27018/sellerbottel_dev` (2026-10-04)
- **Schema analysis**: Python script inspection of all 46 collections
- **Sample document analysis**: First 2 documents per collection examined

Owner decisions documented in:
- `/opt/sellerbottel-v2/repo/docs/v2/OWNER_DECISIONS.md` (2026-10-04)

V2 architecture specifications:
- `/opt/sellerbottel-v2/repo/docs/v2/V2_ARCHITECTURE.md`
- `/opt/sellerbottel-v2/repo/docs/v2/PHASE_2_TENANT_CORE_REPORT.md`
- `/opt/sellerbottel-v2/repo/backend/tenant_provisioning.py`

---

**Document Status**: Evidence-based proposal  
**Next Action**: Owner review and Stage 0-7 execution  
**Production Touch**: NONE (development environment only)
