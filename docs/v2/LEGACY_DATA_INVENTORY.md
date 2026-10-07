# Legacy Data Inventory — Verified

Status: **Complete**. Database restored to Development environment and verified against production manifest. All collections and indexes confirmed intact.

## Restoration Details

**Source**: Production MongoDB 7.0.43 dump from `sellerbottel` database  
**Target**: `mongodb://127.0.0.1:27018/sellerbottel_dev`  
**Verification timestamp**: 2026-10-03T19:04:48Z  
**Verification status**: ✅ **PASS** — All collections, document counts, and indexes match

## Complete Collection Inventory

| Collection | Documents | Purpose | Critical Constraints |
|---|---:|---|---|
| admins | 1 | Admin user accounts | Authentication |
| balance_adjustments | 4 | Manual balance corrections | Financial audit trail |
| bot2_restock_requests | 0 | Restock notification queue | — |
| bot_chat_messages | 476 | Telegram message history | `(chat_id, message_id)` unique |
| bot_message_history | 0 | Historical message archive | — |
| bot_messages | 0 | Outbound message queue | — |
| bot_users | 41 | Telegram bot subscribers | `telegram_id` unique |
| broadcasts | 43 | Marketing broadcast history | Campaign tracking |
| counters | 10 | ID sequence generators | Concurrency-safe increment |
| coupons | 0 | Legacy coupon codes | — |
| daily_recaps | 5 | Daily summary reports | Analytics |
| deposits | 15 | Wallet deposit records | **Financial records** |
| discounts | 0 | Active discount rules | — |
| freeze_log | 4 | Account freeze audit log | Security/compliance |
| gopay_payments | 19 | GoPay payment transactions | **Payment reconciliation** |
| inventory_items | 1,080 | Digital inventory pool | `(product_id, fingerprint)` unique |
| login_attempts | 4 | Failed login tracking | Security |
| outreach_campaigns | 1 | Outreach campaign config | Marketing |
| outreach_jobs | 88 | Scheduled outreach tasks | Marketing execution |
| post_purchase_actions | 20 | Post-sale automation | Customer lifecycle |
| processed_updates | 1,223 | Telegram update deduplication | `update_id` unique |
| processed_updates_bot2 | 42 | Bot2 update deduplication | `update_id` unique |
| products | 37 | Product catalog | Catalog management |
| promo_campaigns | 0 | Promotion campaign definitions | — |
| promo_coupon_redemptions | 4 | Coupon redemption events | Usage tracking |
| promo_coupon_usage | 4 | Coupon usage limits | Quota enforcement |
| promo_coupons | 4 | Active promotion coupons | Discount application |
| promo_events | 13 | Promotion lifecycle events | Event sourcing |
| promo_suppressions | 6 | Promotion opt-out list | Compliance |
| prospects | 385 | Marketing prospects | `(owner_account_id, tg_user_id)` unique |
| purchases | 71 | **Order/purchase records** | **`invoice_id` unique**, `(customer_id, idempotency_key)` unique |
| required_channels | 0 | Mandatory subscription channels | Access control |
| reseller_bot_users | 3 | Reseller bot subscribers | Reseller program |
| reseller_bots | 1 | Reseller bot instances | `telegram_bot_id` unique |
| reseller_commissions | 18 | **Commission records** | **Financial records** |
| reseller_contests | 3 | Reseller competition events | Incentive program |
| reseller_payments | 1 | **Reseller payment records** | **Financial records** |
| reseller_payouts | 1 | **Commission payout records** | **Financial records** |
| reseller_updates | 61 | Reseller Telegram updates | Deduplication |
| settings | 1 | Global application settings | Configuration |
| stock_events | 42 | Inventory event log | Audit trail |
| store_customers | 5 | Web storefront customers | `email` unique, `telegram_id` unique |
| store_email_codes | 0 | Email verification codes | Authentication |
| tg_accounts | 4 | Telegram account pool | `tg_user_id` unique |
| tg_groups | 64 | Managed Telegram groups | `(account_id, chat_id)` unique |
| traffic_sources | 0 | Marketing attribution | Analytics |

**Total**: 46 collections, 3,804 documents

## Index Verification

All critical indexes verified present and correct:

### Financial Integrity Indexes
- `purchases.invoice_id` (unique) — Prevents duplicate orders
- `purchases.customer_id + idempotency_key` (unique) — Idempotent payment processing
- `deposits` — Financial audit trail
- `reseller_commissions`, `reseller_payments`, `reseller_payouts` — Commission tracking

### Identity and Deduplication
- `bot_users.telegram_id` (unique)
- `store_customers.email` (unique)
- `store_customers.telegram_id` (unique)
- `tg_accounts.tg_user_id` (unique)
- `processed_updates.update_id` (unique)
- `reseller_bots.telegram_bot_id` (unique)

### Inventory Management
- `inventory_items.product_id + fingerprint` (unique) — Prevents duplicate items
- `inventory_items.marketing.event_id` (unique) — Marketing attribution
- `inventory_items.product_id + status` — Stock queries

### Relationship Indexes
- `bot_chat_messages.chat_id + message_id` (unique)
- `tg_groups.account_id + chat_id` (unique)
- `prospects.owner_account_id + tg_user_id` (unique)
- `purchases.user_tid + created_at` — User purchase history
- `purchases.reseller_bot_id + created_at` — Reseller analytics

## Data Domain Classification

### Financial Records (71 + 19 + 15 + 18 + 1 + 1 = 125 documents)
**Critical for audit and reconciliation**
- `purchases` (71) — Order records with amounts, payment status
- `gopay_payments` (19) — Payment provider transactions
- `deposits` (15) — Wallet deposits
- `reseller_commissions` (18) — Earned commissions
- `reseller_payments` (1) — Commission payments
- `reseller_payouts` (1) — Payout records
- `balance_adjustments` (4) — Manual corrections

**Requirements**: Preserve all IDs, amounts, timestamps; maintain referential integrity; support reconciliation queries.

### Customer Identity (41 + 5 + 385 = 431 documents)
**PII present**
- `bot_users` (41) — Telegram subscribers with user IDs, names
- `store_customers` (5) — Email addresses, contact info
- `prospects` (385) — Marketing leads

**Requirements**: Privacy policy, consent tracking, data retention rules, opt-out handling.

### Inventory and Catalog (1,080 + 37 = 1,117 documents)
- `inventory_items` (1,080) — Digital credentials/codes
- `products` (37) — Product definitions

**Requirements**: Prevent duplicate item allocation, track item status lifecycle.

### Communications (476 + 43 + 1 + 88 = 608 documents)
- `bot_chat_messages` (476) — Telegram message history
- `broadcasts` (43) — Marketing campaigns
- `outreach_campaigns` (1)
- `outreach_jobs` (88)

**Requirements**: Consent management, opt-out enforcement.

### Integration State (1,223 + 42 + 61 = 1,326 documents)
**Operational, not business-critical**
- `processed_updates` (1,223) — Telegram deduplication
- `processed_updates_bot2` (42)
- `reseller_updates` (61)

**Requirements**: Safe to reset/rebuild if needed.

### System Configuration (1 + 10 = 11 documents)
- `settings` (1) — Global config
- `counters` (10) — ID sequences

**Requirements**: Careful counter migration to avoid ID collisions.

## Tenant Classification Guidance

**Recommendation**: Classify entire dataset as **IDSE first-party tenant** records until multi-tenant migration is explicitly authorized.

### Current State
- No tenant_id field on any collection
- All records belong to single production deployment
- No multi-tenant authorization or scoping

### Migration Approach
1. Assign `tenant_id: "idse"` to all existing records
2. Add tenant context enforcement to all queries
3. Implement tenant-scoped authorization
4. Add tenant boundary tests
5. Only then: consider additional tenants

### Financial Record Preservation
- Keep original `_id` values
- Maintain invoice_id → purchase mapping
- Preserve all amounts, timestamps, status values
- Link deposits ↔ purchases ↔ commissions

## Persistent Files

Archive manifest shows:
- `backend/assets/brands/` — Brand logos (in source tree)
- `persistent-data/inventory.json` — Inventory file reference list

Frontend build artifacts and production-only files were **excluded** from Development environment.

## Data Quality Notes

### Empty Collections (13)
These collections exist in schema but contain no documents:
- bot2_restock_requests, bot_message_history, bot_messages
- coupons, discounts, promo_campaigns, required_channels
- store_email_codes, traffic_sources

Migration can safely skip or preserve empty collections.

### Low Volume Collections (< 10 documents)
- admins (1), settings (1), reseller_bots (1), reseller_payments (1), reseller_payouts (1)
- outreach_campaigns (1)
- reseller_bot_users (3), promo_coupons (4), tg_accounts (4)
- Various logs/events with < 10 entries

Suitable for manual inspection and validation.

## Verification Summary

✅ **All 46 collections restored**  
✅ **3,804 documents verified**  
✅ **0 discrepancies detected**  
✅ **All critical indexes present**  
✅ **Financial records intact**  
✅ **Ready for schema analysis and tenant migration planning**

## Next Steps

1. Schema analysis — document structure for each domain
2. Relationship mapping — foreign key equivalents
3. Tenant migration — add `tenant_id` to all collections
4. Authorization model — enforce tenant scoping
5. Data validation — business rule compliance checks
