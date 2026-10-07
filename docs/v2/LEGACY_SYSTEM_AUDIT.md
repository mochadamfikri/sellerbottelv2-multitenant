# Legacy System Audit — Discovery Complete

Status: **Discovery phase complete**. Active source audit, database restore verification, and integrity validation complete. Architecture and migration documents ready for Owner review.

## Evidence and Scope

- **Archive verified**: `/opt/sellerbottel-v2/_incoming/sellerbottel-full-migration-20261003-113201.tar.gz`  
  SHA256: `ca74ff070c82dec5d0f66e7b5ea38afcb24748cd935db01c84382d9444c1ab39`
- **Extracted to**: `/opt/sellerbottel-v2/_staging/discovery-20261003`  
  Internal `SHA256SUMS` verification: **PASS**
- **Development repository**: `/opt/sellerbottel-v2/repo`  
  Branch: `renovation/sellerbottel-v2-platform`  
  Baseline commit: `3a75b1cc2ab2fbe297556e098bba90d635d631a8`  
  Status: Clean, matches `origin/main`
- **Database restored**: `mongodb://127.0.0.1:27018/sellerbottel_dev`  
  46 collections, 3,804 documents  
  Collection count verification: **PASS**  
  Index verification: **PASS**  
  Timestamp: 2026-10-03T19:04:48Z

## Source Code Baseline

Active Development checkout and archived production snapshot share identical 226 tracked paths at commit `3a75b1cc2ab2fbe297556e098bba90d635d631a8`. Archive snapshot additionally contains production-only untracked/ignored files:
- `backend/.env` (production secrets)
- `frontend/.env` (production config)
- `backend/gobiz/.gopay_cache.json` (payment provider cache)
- `backend/migrations/` (historical migration artifacts)
- `frontend/build/` (compiled assets)
- `frontend/src/storefront/` (storefront components)

**These production files were NOT copied into Development.**

Snapshot working tree shows uncommitted changes:
- `backend/bot.py`: 23 additions / 2 deletions
- `backend/tests/test_direct_checkout.py`: 54 additions / 1 deletion

These changes were preserved in staging but NOT applied to the clean Development branch. Review separately if required.

## Architecture Observations

### Backend Architecture
- **Framework**: Python FastAPI (`backend/server.py`)
- **API**: 19 mounted routers, some conditionally activated for promotions
- **Database**: MongoDB via Motor async driver
- **Configuration**: Environment-selected via `MONGO_URL` / `DB_NAME` (`backend/db.py`)
- **Data access**: Direct collection access throughout application modules
- **Tenant isolation**: **None evidenced** — no explicit `tenant_id` scoping found in backend/frontend source

### Bot Layer
- **Platform**: Telegram Bot API
- **Implementation**: Backend modules `bot.py`, `bot2.py`, reseller and promotion modules
- **Credentials**: Production tokens in archived config (not activated in Development)

### Frontend
- **Framework**: React (`frontend/src/App.js`)
- **Components**: Admin pages, storefront UI, API integration layer
- **Build artifacts**: Included in production snapshot

### Commerce Domains
Code and database evidence shows:
- Product catalog and inventory management
- Checkout, orders, purchase fulfillment
- Wallet system with deposits and balance adjustments
- Discounts, coupons, promotion campaigns
- Broadcast and outreach campaigns
- Reseller program with commissions and payouts
- Telegram accounts and group management
- Reporting and analytics
- Web storefront with customer accounts

### Deployment Evidence
Production snapshot includes:
- Nginx configuration and certificates
- systemd service definitions
- Docker inspection artifacts

**These are reference only — production values must be replaced before any Development/staging deployment.**

### Test Coverage
- 16 test files identified (backend tests + frontend)
- Backend includes offline MongoDB mock tests
- Tests were not executed during Discovery audit

## Database Verification Results

**Restoration Status**: ✅ Complete and verified

All 46 collections restored with exact document counts matching production manifest:

| Collection | Documents | Critical Indexes |
|---|---:|---|
| admins | 1 | Primary |
| balance_adjustments | 4 | Financial audit trail |
| bot_users | 41 | `telegram_id` (unique) |
| bot_chat_messages | 476 | `(chat_id, message_id)` (unique) |
| broadcasts | 43 | Marketing history |
| counters | 10 | Sequence generation |
| deposits | 15 | Financial records |
| gopay_payments | 19 | Payment provider reconciliation |
| inventory_items | 1,080 | `(product_id, fingerprint)` (unique) |
| products | 37 | Product catalog |
| purchases | 71 | `invoice_id` (unique), `(customer_id, idempotency_key)` (unique) |
| prospects | 385 | `(owner_account_id, tg_user_id)` (unique) |
| reseller_bots | 1 | `telegram_bot_id` (unique) |
| reseller_bot_users | 3 | Reseller program |
| reseller_commissions | 18 | Financial records |
| store_customers | 5 | `email` (unique), `telegram_id` (unique) |
| tg_accounts | 4 | `tg_user_id` (unique) |
| tg_groups | 64 | `(account_id, chat_id)` (unique) |
| *(other collections)* | *(various)* | *(standard indexes)* |

**Total verified**: 3,804 documents across 46 collections  
**Discrepancies**: 0  
**Index integrity**: ✅ All critical indexes present

## Key Findings and Risks

### Critical Gaps
1. **No tenant isolation**: Single database, direct collection access, no tenant boundary enforcement
2. **Production secrets exposed**: Configuration files and credentials in archive — kept private in staging, never deployed to Development
3. **Uncommitted production changes**: Working tree patch preserved for review but not applied

### Architecture Limitations
- Database-per-tenant versus shared-database-with-tenant-keys decision pending
- No evidence of multi-tenant authorization or data scoping
- Direct collection access pattern makes tenant key enforcement retrofit complex

### Data Integrity Considerations
- Financial records (purchases, deposits, commissions, payments) require preservation of IDs and referential integrity
- Unique constraints on invoices, idempotency keys, and customer identifiers must be maintained
- Counter sequences need careful migration to avoid collisions

### Security and Privacy
- PII present in bot_users, prospects, store_customers, bot_chat_messages
- Production Telegram tokens, payment provider credentials in archived config
- Analytics and marketing consent model undefined

## Owner Decision Points

1. **Tenant isolation model**  
   - Database-per-tenant (strong isolation, higher operational cost)  
   - Shared database with enforced `tenant_id` keys (lower cost, requires comprehensive authorization layer)

2. **IDSE as first-party tenant**  
   - Classify existing production data as IDSE first-party tenant records
   - Establish tenant mapping before any future multi-tenant migration

3. **Licensing and commercial transfer**  
   - Define subscription/licensing model (plans, quotas, billing)
   - Source code transfer/ownership workflow
   - Demo versus production tenant lifecycle

4. **Privacy and consent**  
   - Analytics data collection and usage
   - Marketing/outreach consent and opt-out handling
   - Cross-tenant analytics aggregation policy

5. **Payment reconciliation**  
   - Per-tenant payment provider credentials and reconciliation
   - Historical payment record preservation and audit requirements

## Next Steps

1. **Owner review**: Architecture document, phase plan, and risk register
2. **Foundation phase authorization**: Once Owner approves tenant isolation model and phase plan
3. **Production credential rotation**: Exposed secrets in archive should be rotated
4. **Integration configuration**: Telegram and payment provider sandbox credentials for Development

## Status Summary

✅ Development repository established  
✅ Production baseline verified and clean  
✅ Database restored and verified  
✅ Source-to-DB mapping complete  
✅ Architecture documented  
⏳ Awaiting Owner decisions and phase authorization  
🚫 **No production systems touched**  
🚫 **No production credentials activated**
