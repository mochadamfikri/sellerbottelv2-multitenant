# Legacy Broadcast & Outreach Architecture Audit

**Audit Date:** 2026-10-03  
**Repository:** /opt/sellerbottel-v2/repo  
**Purpose:** Map existing broadcast, campaign, and customer acquisition systems for consolidation planning

---

## Executive Summary

The system operates **TWO SEPARATE BROADCAST MODULES** with overlapping functionality:

1. **"Broadcast" (admin_routes.py)** - User-facing broadcasts to bot users
2. **"Broadcast Terpusat" / Marketing Campaigns (marketing_campaigns.py)** - Channel broadcasts with inventory allocation

Additionally, a **THIRD MODULE** exists for **outreach/prospecting** (promo_* files) that handles customer acquisition through Telegram direct messaging.

**Current State:**
- 43 broadcasts in database
- 1 outreach_campaign 
- 88 outreach_jobs
- 385 prospects
- 6 promo_suppressions (opt-out list)

**Owner Requirement:** Merge Broadcast + Broadcast Terpusat into one unified module.

---

## System 1: Broadcast (User-Facing)

### Backend Implementation
**File:** `backend/admin_routes.py` (lines 1862-2241)

**Purpose:** Send promotional messages to bot users (customers who have used the bot)

### Collections
- `broadcasts` (kind != "marketing_campaign")
  - Stores broadcast jobs with status, recipient counts, completion tracking
  - Fields: `_id`, `text`, `lang`, `status`, `success`, `failed`, `blocked`, `total`, `created_at`, `finished_at`, `product_id`, `auto_image`

### Key Features
1. **Broadcast to Bot Users**
   - Target: All bot users in `bot_users` collection
   - Filters: language (id/en), account status (active/frozen), search by name/username
   - Silent block filtering: excludes `silent_blocked: true` users

2. **Message Types**
   - Text-only messages
   - Photo broadcasts (upload or auto-generated)
   - Product broadcasts with auto-generated images
   - Inline button support (text + URL)

3. **Auto-Generated Images**
   - Uses `broadcast_image.py` to render product visuals
   - Requires `broadcast_auto_image_enabled` setting
   - Product name, price, stock, description overlay

4. **Broadcast Modes**
   - Manual: Admin writes custom message
   - Product list: All active products with stock
   - Auto (discount/stock/both): Dynamic content generation

5. **Worker Pattern**
   - `_broadcast_worker()` - async background task
   - Processes user queue with 0.08s sleep between sends
   - Updates progress every 20 messages
   - Handles Telegram 403 errors (blocked users)

### API Endpoints
- `POST /api/admin/broadcasts/preview` - Count recipients
- `POST /api/admin/broadcasts` - Create user broadcast
- `POST /api/admin/broadcasts/channel` - Send to channel/users
- `GET /api/admin/broadcasts` - List history (excludes marketing_campaign kind)

### Frontend
**File:** `frontend/src/pages/Broadcasts.jsx`

**Route:** `/broadcasts` ("Broadcast")

**UI Sections:**
1. Marketing Campaigns component (embedded)
2. Broadcast composer with 3 types:
   - Message & Products (custom + up to 10 products)
   - Best Sellers (7d/30d/all time leaderboard)
   - Daily Recap (yesterday's sales summary)
3. Product selection with catalog filter
4. Preview & send controls
5. Broadcast history list
6. Daily recap scheduler

---

## System 2: Broadcast Terpusat / Marketing Campaigns

### Backend Implementation
**File:** `backend/marketing_campaigns.py`

**Purpose:** Automated channel broadcasts with inventory allocation and persistent campaign tracking

### Collections
- `broadcasts` (kind = "marketing_campaign")
  - Campaigns with event arrays, lease locking, scheduling
  - Fields: `_id`, `kind`, `name`, `channel`, `minimum_interval`, `maximum_interval`, `count`, `product_ids`, `status`, `sent`, `cursor`, `events[]`, `next_scheduled_at`, `lease_owner`, `lease_until`

- `inventory_items` (marketing integration)
  - `status: "marketing_allocated"` - items reserved for campaigns
  - `marketing.event_id`, `marketing.campaign_id`, `marketing.allocated_at`
  - `marketing_audit[]` - receipt trail for allocations/restores

- `stock_events` - audit projections from inventory operations

### Key Features
1. **Persistent Campaigns**
   - Create campaigns with 1-500 message events
   - Each event allocates one inventory item
   - Random intervals between sends (1-10,080 minutes)
   - Product rotation (avoids same product consecutively)
   - Idempotency via request_id

2. **Inventory Integration**
   - Allocates inventory items before sending
   - `allocate()` - reserve item, write audit receipt
   - `restore()` - return unsent/stopped allocations to available pool
   - Stock audit repair on startup

3. **Lease-Based Concurrency**
   - `lock()` - 3-minute lease with UUID token
   - Prevents concurrent admin/worker modifications
   - Manual actions (pause/resume/stop/confirm_sent) require lease

4. **Campaign States**
   - `active` - running, next_scheduled_at set
   - `paused` - stopped by admin, can resume
   - `stopped` - cancelled, restore needed to reclaim stock
   - `completed` - all events sent
   - `failed` - Telegram error, manual intervention required

5. **Event States**
   - `pending` → `allocated` → `sending` → `sent`
   - `unknown` - uncertain delivery, requires manual confirmation
   - `failed` - explicit Telegram rejection, retryable
   - `cancelled` - stopped before send

6. **Worker Loop**
   - `run_marketing()` - polls every 15 seconds
   - Processes due campaigns (`status=active`, `next_scheduled_at <= now`)
   - Repairs stock audits on each cycle
   - No automatic retry for uncertain sends (no idempotency key)

### API Endpoints
- `POST /api/admin/broadcasts/campaigns` - Create campaign
- `GET /api/admin/broadcasts/campaigns` - List campaigns
- `GET /api/admin/broadcasts/campaigns/{id}` - Campaign detail with events
- `POST /api/admin/broadcasts/campaigns/{id}/action` - pause/resume/stop/confirm_sent
- `GET /api/admin/broadcasts/campaigns/{id}/allocations` - Reserved inventory
- `POST /api/admin/broadcasts/campaigns/{id}/restore` - Return stock to pool

### Frontend
**File:** `frontend/src/pages/CentralBroadcasts.jsx`

**Route:** `/central-broadcasts` ("Broadcast Terpusat")

**Component:** Also embedded in Broadcasts.jsx via `MarketingCampaigns.jsx`

**UI Features:**
1. Campaign creation form with options picker
2. 8 topic types (reseller_guide, contest, discount, coupon, product_update, restock, deposit_guide, announcement)
3. Auto-generated images for all topics
4. Reference selection (contest/discount/coupon/product data)
5. Target selection (chats/users/both)
6. Preview with image + text
7. Test send to admin
8. Broadcast history

**Note:** Despite the name "Broadcast Terpusat", this page sends one-off system update broadcasts, NOT the persistent marketing campaigns. The marketing campaigns are managed through a component embedded in the main Broadcasts page.

---

## System 3: Outreach / Customer Acquisition (Promo Module)

### Backend Implementation
**Files:**
- `promo_campaign.py` - Core campaign/job/prospect logic
- `promo_campaign_routes.py` - HTTP API
- `promo_routes.py` - Prospects, coupons, sources
- `promo_routes_accounts.py` - Telegram account management
- `promo_reply_routes.py` - Event logs
- `promo_runtime.py` - Reply listener + job queue worker
- `promo_telegram.py` - MTProto client wrapper

**Feature Flag:** `PROMOTION_ENABLED` environment variable

### Collections
1. **prospects**
   - Potential customers from Telegram (private chats, groups, manual)
   - Fields: `_id`, `tg_user_id`, `username`, `name`, `owner_account_id`, `source`, `status`, `contact_allowed`, `contact_count`, `last_contacted_at`, `bot_user_tid`, `notes`
   - Statuses: `new`, `contacted`, `replied`, `interested`, `customer`, `opt_out`

2. **outreach_campaigns**
   - Cold outreach campaigns with templates
   - Fields: `_id`, `name`, `template`, `source_code`, `bot_link`, `product_id`, `account_ids[]`, `status`, `approval_required`, `daily_limit`, `min_interval_seconds`, `send_window_start`, `send_window_end`

3. **outreach_jobs**
   - Individual message send jobs
   - Fields: `_id`, `campaign_id`, `prospect_id`, `account_id`, `status`, `scheduled_at`, `attempts`, `last_error`, `sent_at`, `manual`
   - Statuses: `queued`, `approved`, `sending`, `sent`, `failed`, `cancelled`

4. **tg_accounts**
   - Telegram user accounts for sending (NOT bot accounts)
   - Session storage: `session_encrypted` (AES cipher)
   - Statuses: `active`, `limited`, `logged_out`

5. **tg_groups**
   - Groups accessible by accounts for manual posting
   - Fields: `_id`, `account_id`, `chat_id`, `title`, `username`, `access_hash`, `entity_type`

6. **promo_suppressions**
   - Opt-out list (unsubscribe, "stop", admin removal)
   - Unique `tg_user_id` index
   - Checked before every send

7. **promo_events**
   - Activity log (reply, manual_message)

8. **promo_coupons** (shared with main system)
   - Discount codes with quota/product restrictions

9. **traffic_sources**
   - UTM-style source tracking for prospect attribution

### Key Features

#### 1. Prospect Management
- **Import from Telegram:**
  - `import_private_chats()` - Scan account dialogs, add non-bot users
  - `sync_groups()` - Refresh group membership
  - Filters: excludes bots, deleted accounts, existing bot_users, suppressed users

- **Manual Addition:**
  - Admin can add Telegram ID + metadata
  - Automatically marked `customer` if already in bot_users

- **Status Tracking:**
  - `contact_count` increments on each send
  - `last_contacted_at` timestamp
  - `last_reply_at` when prospect responds

#### 2. Campaign System
- **Template Variables:**
  - `{nama}` - prospect name/username fallback
  - `{username}` - Telegram username
  - `{bot_link}` - Bot deep link
  - `{produk}` - product name
  - `{harga_usd}` - formatted USD price
  - `{harga_idr}` - formatted IDR price (rate-converted or direct)

- **Job Creation:**
  - `enqueue_campaign()` - create jobs for matching prospects
  - Filters: status, contact_allowed, no suppression
  - Round-robin account assignment
  - Approval gate (queued → approved transition)

- **Send Controls:**
  - Daily limit per account (default 20, range 1-100)
  - Send window hours (default 09:00-21:00)
  - Minimum interval 300s (5 min) between sends
  - FloodWait / PeerFlood detection → stops campaign

#### 3. Runtime Workers

**Reply Listener** (`promo_runtime.py`):
- Telethon event handler on each active account
- Detects "stop", "berhenti", "unsubscribe" → opt_out()
- Updates prospect status to "replied"
- Logs event to promo_events
- Notifies admin via bot (if ADMIN_TELEGRAM_ID set)

**Job Queue** (`_queue_loop()`):
- Polls every 5 seconds
- Fetches up to 20 approved jobs (status=approved, scheduled_at <= now or null)
- Calls `send_job()` for each
- Random sleep after send: min_interval * [1.0, 1.5]
- Defers on daily limit, send window, scheduled_at future
- Cancels on opt_out
- Stops campaign on FloodWait/PeerFlood
- Retries failed jobs after 5-minute backoff

#### 4. Manual Actions
- **Send to Prospect:** Admin can send one-off message via UI
- **Post to Group:** Admin can broadcast to synced groups
- **Opt-Out:** Mark user suppressed, cancel all pending jobs

#### 5. Compliance & Safety
- **Suppression List:**
  - Unique tg_user_id enforcement
  - Checked before job creation (enqueue)
  - Checked before job execution (send_job)
  - Reply "stop" triggers opt_out
  - Admin can manually suppress

- **Telegram Rate Limits:**
  - FloodWaitError → account status "limited", campaign stopped
  - PeerFloodError → account status "limited", campaign stopped
  - UserPrivacyRestrictedError → job failed, continues

- **Access Control:**
  - Requires `owner_account_id` or `access_hash` to send
  - Username lookup fallback
  - Prevents sending without proper peer info

### API Endpoints

**Prospects:**
- `GET /api/admin/promo/prospects` - List with status filter
- `POST /api/admin/promo/prospects` - Create prospect
- `POST /api/admin/promo/prospects/manual` - Add by Telegram ID only
- `PATCH /api/admin/promo/prospects/{id}` - Update prospect
- `POST /api/admin/promo/prospects/{id}/send` - Manual message

**Campaigns:**
- `GET /api/admin/promo/campaigns` - List campaigns
- `POST /api/admin/promo/campaigns` - Create campaign
- `POST /api/admin/promo/campaigns/{id}/enqueue` - Generate jobs
- `PATCH /api/admin/promo/campaigns/{id}/stop` - Stop + cancel jobs
- `GET /api/admin/promo/jobs` - List jobs (status filter)
- `POST /api/admin/promo/jobs/{id}/approve` - Approve job
- `POST /api/admin/promo/opt-out` - Suppress user

**Accounts:**
- `GET /api/admin/promo/accounts` - List Telegram accounts
- `POST /api/admin/promo/accounts/login/start` - Begin auth flow
- `POST /api/admin/promo/accounts/login/{id}/verify` - Complete auth
- `POST /api/admin/promo/accounts/{id}/check` - Verify account status
- `DELETE /api/admin/promo/accounts/{id}` - Revoke session
- `POST /api/admin/promo/accounts/{id}/import-private` - Import chats
- `POST /api/admin/promo/accounts/{id}/sync-groups` - Sync groups

**Groups:**
- `GET /api/admin/promo/groups` - List groups (account filter)
- `POST /api/admin/promo/groups/{id}/post` - Manual group post

**Analytics:**
- `GET /api/admin/promo/results` - Job/prospect counts by status
- `GET /api/admin/promo/results/sources` - Conversion by source_code
- `GET /api/admin/promo/summary` - Dashboard counts
- `GET /api/admin/promo/events` - Activity log

**Coupons & Sources:**
- `GET /api/admin/promo/coupons` - List coupons
- `POST /api/admin/promo/coupons` - Create coupon
- `GET /api/admin/promo/sources` - List traffic sources
- `POST /api/admin/promo/sources` - Create source

### Frontend
**File:** `frontend/src/pages/Promotions.jsx`

**Route:** `/promotions` ("Promosi / Cari Pelanggan")

**UI Tabs:**
1. **accounts** - Telegram account login/logout/import
2. **prospects** - Prospect list, manual add, contact permission toggle, manual send
3. **campaigns** - Campaign list, create, enqueue, stop
4. **coupons** - Coupon CRUD
5. **sources** - Traffic source tracking
6. **groups** - Group list, sync, manual post
7. **jobs** - Job queue status
8. **events** - Activity log
9. **results** - Dashboard metrics and source attribution

---

## Current Menu Structure (Frontend Routes)

From `frontend/src/App.js` and `frontend/src/components/Layout.jsx`:

1. **Admin** (`/admin`) - Dashboard
2. **Produk** (`/products`) - Product management
3. **Katalog** (`/catalogs`) - Catalog management
4. **Orders** (`/orders`) - Order list
5. **Rekap & Laporan** (`/reports`) - Reports
6. **Inventory** (`/inventory`) - Inventory items
7. **Deposit** (`/deposits`) - Deposit management
8. **Pengguna** (`/users`) - User management
9. **Discount** (`/discounts`) - Discount rules
10. **Broadcast** (`/broadcasts`) - User broadcasts + Marketing Campaigns component
11. **Broadcast Terpusat** (`/central-broadcasts`) - System update broadcasts
12. **Bot Reseller** (`/resellers`) - Reseller bot management
13. **Promosi / Cari Pelanggan** (`/promotions`) - Outreach/CRM module
14. **Tindak Lanjut Bot** (`/bot-moderation`) - Post-purchase actions
15. **Bot Messages** (`/messages`) - Message templates
16. **Pengaturan** (`/settings`) - Global settings

---

## Database Schema Summary

### Broadcast Collections
```
broadcasts (multi-purpose)
├─ kind != "marketing_campaign"  → User broadcasts (System 1)
└─ kind = "marketing_campaign"   → Persistent campaigns (System 2)

inventory_items
└─ status: "marketing_allocated" → Reserved for campaigns
   └─ marketing.event_id, campaign_id, allocated_at
   └─ marketing_audit[] → allocation/restore receipts

stock_events → Audit projection
```

### Outreach Collections
```
prospects (385 records)
├─ tg_user_id [unique per owner_account_id]
├─ status: new|contacted|replied|interested|customer|opt_out
└─ contact_allowed: boolean

outreach_campaigns (1 record)
└─ template with {variables}

outreach_jobs (88 records)
├─ campaign_id → outreach_campaigns
├─ prospect_id → prospects
├─ account_id → tg_accounts
└─ status: queued|approved|sending|sent|failed|cancelled

tg_accounts
└─ session_encrypted (MTProto session)

tg_groups
└─ Synced from account dialogs

promo_suppressions (6 records)
└─ tg_user_id [unique]

promo_events
└─ reply, manual_message logs

promo_coupons (shared)
promo_coupon_redemptions
traffic_sources
```

### Indexes (from db.py lines 161-183)
```python
# Outreach indexes
prospects: [(owner_account_id, tg_user_id)] unique
prospects: [(status, created_at)]
tg_accounts: [tg_user_id] unique sparse
tg_accounts: [status]
tg_groups: [(account_id, chat_id)] unique
outreach_jobs: [(status, scheduled_at)]
outreach_jobs: [(campaign_id, prospect_id, status)]
outreach_campaigns: [(status, created_at)]
promo_suppressions: [tg_user_id] unique
promo_events: [(type, created_at)]
promo_coupons: [code] unique
promo_coupon_redemptions: [(coupon_id, order_id)] unique
promo_coupon_redemptions: [(coupon_id, user_tid)]
traffic_sources: [code] unique
```

---

## Architectural Observations

### Duplication & Overlap

1. **Two Broadcast Menus:**
   - "Broadcast" contains Marketing Campaigns component
   - "Broadcast Terpusat" is separate but uses different broadcast features
   - Both write to same `broadcasts` collection (differentiated by `kind`)

2. **Channel Broadcast Modes:**
   - System 1 (admin_routes): `POST /broadcasts/channel` - one-off sends
   - System 2 (marketing_campaigns): persistent multi-event campaigns
   - Both target channels, both can auto-generate images

3. **User Broadcast Overlap:**
   - System 1: User broadcasts via bot_users collection
   - System 3: Could theoretically broadcast to prospects (not bot users)
   - Outreach is 1:1 DM, not broadcast, but similar audience concept

### Separation Rationale

**Why System 1 & 2 are separate:**
- System 1: Immediate, one-off user/channel broadcasts (fire and forget)
- System 2: Scheduled, inventory-coupled, persistent campaigns with recovery

**Why System 3 is separate:**
- Different audience (prospects, not bot users)
- Uses user accounts, not bot account
- Compliance-heavy (opt-out, rate limits, send windows)
- 1:1 direct messages, not broadcasts

### Integration Points

1. **Prospect → Customer:**
   - `promo_campaign.py` checks `bot_users` to mark prospect as "customer"
   - `checkout.py` and `direct_checkout.py` update prospects on purchase
   - `traffic_source_code` links prospect acquisition to order attribution

2. **Coupon System:**
   - `promo_coupons` collection used by both storefront checkout and outreach campaigns
   - Redemptions tracked in `promo_coupon_redemptions`

3. **Product References:**
   - Outreach templates can include product_id for variable substitution
   - Marketing campaigns select from active inventory products
   - User broadcasts can attach product_id for auto-image generation

---

## Key Differences: System 1 vs System 2

| Aspect | System 1 (Broadcast) | System 2 (Marketing Campaigns) |
|--------|---------------------|--------------------------------|
| **Purpose** | One-off promotional messages | Persistent scheduled campaigns |
| **Target** | Bot users (customers) | Channels (public announcements) |
| **Collection** | broadcasts (kind != marketing_campaign) | broadcasts (kind = marketing_campaign) |
| **Inventory** | No inventory coupling | Allocates inventory items |
| **Scheduling** | Immediate send | Random intervals, next_scheduled_at |
| **State Management** | Simple (running → completed) | Complex (active/paused/stopped/failed) |
| **Concurrency** | None (fire and forget) | Lease-based worker locking |
| **Recovery** | No recovery needed | Restore allocations, confirm_sent |
| **Image Generation** | Optional | Not currently used |
| **Worker** | Ad-hoc asyncio task | Persistent polling loop (15s) |

---

## Consolidation Considerations

### Owner Request
"Merge Broadcast + Broadcast Terpusat into one module"

### Technical Paths

#### Option A: Merge into Unified Broadcast Module
- Combine admin_routes.py broadcast logic with marketing_campaigns.py
- Single menu item: "Broadcast"
- Tabs: User Broadcasts | Channel Broadcasts | Marketing Campaigns
- Shared collection: `broadcasts` (already merged via `kind` field)

**Pros:**
- Single source of truth for all broadcast operations
- Unified image generation pipeline
- Consistent API patterns

**Cons:**
- Marketing campaigns have fundamentally different lifecycle (persistent vs one-off)
- Inventory coupling is campaign-specific
- Large combined file/module

#### Option B: Separate Concerns, Unified Menu
- Keep backend modules separate (different purposes)
- Merge frontend routes under single "Broadcast" menu
- Sub-navigation or tabs for User/Channel/Campaign modes

**Pros:**
- Clean separation of concerns in backend
- Frontend consolidation satisfies "one module" requirement
- Easier to maintain/test separately

**Cons:**
- Backend still has two distinct systems
- API surface remains split

#### Option C: Three-Tier Architecture
1. **Broadcast Engine** (shared): Message composition, image generation, sending
2. **User Broadcasts**: One-off sends to bot_users
3. **Marketing Campaigns**: Scheduled, inventory-coupled, channel campaigns

**Pros:**
- Eliminates code duplication (image generation, template rendering)
- Each tier has clear responsibility
- Scales to future broadcast types

**Cons:**
- Requires refactoring both existing systems
- More complex initial implementation

### Recommendation

**Hybrid Approach (Option B + C elements):**

1. **Frontend:** Merge menu items into single "Broadcast" page with tabs
   - Tab 1: Quick Broadcast (current System 1 functionality)
   - Tab 2: Marketing Campaigns (current System 2 functionality)
   - Remove "Broadcast Terpusat" menu item (fold into Tab 1 or separate "System Updates" section)

2. **Backend:** Extract shared utilities into `broadcast_engine.py`
   - Image generation (already in broadcast_image.py)
   - Template rendering
   - Recipient targeting logic
   - Send infrastructure (already via tgapi)

3. **Keep Separate Modules:**
   - `admin_routes.py` - User broadcast endpoints
   - `marketing_campaigns.py` - Campaign endpoints (already separate router)
   - `broadcast_composer.py` - Shared composition logic (already exists)

4. **Outreach Module:** Keep completely separate (different audience, compliance, architecture)

### Risks & Considerations

1. **Breaking Changes:**
   - Existing 43 broadcasts in database must remain readable
   - Frontend route changes need migration guide
   - API clients (if any) need update

2. **Inventory Integration:**
   - Marketing campaigns tightly coupled to inventory_items
   - Stock allocation logic is complex, avoid breaking
   - Audit trail (marketing_audit) must remain intact

3. **Worker Safety:**
   - Marketing worker loop runs continuously
   - Lease locking prevents race conditions
   - Don't break during refactor

4. **Testing:**
   - 51 backend tests exist (test_upgradeversi.py references campaigns)
   - Browser tests in scripts/ cover UI workflows
   - All must pass after consolidation

---

## Current Database State (from backup reference)

- **43 broadcasts** - Mix of user broadcasts and marketing campaigns
- **1 outreach_campaign** - One active outreach campaign
- **88 outreach_jobs** - Active job queue
- **385 prospects** - Lead database
- **6 promo_suppressions** - Opt-out list
- **inventory_items with marketing status** - Reserved for campaigns
- **stock_events** - Audit trail

---

## Related Files

### Backend Core
- `admin_routes.py` - User broadcast endpoints (lines 1862-2241)
- `marketing_campaigns.py` - Persistent campaign system (349 lines)
- `broadcast_composer.py` - Message composition utilities
- `broadcast_image.py` - Auto-generated visuals
- `daily_recap.py` - Scheduled summary broadcasts

### Outreach/CRM (Promo Module)
- `promo_campaign.py` - Campaign/job/prospect core (235 lines)
- `promo_campaign_routes.py` - Campaign HTTP API (223 lines)
- `promo_routes.py` - Prospects, coupons, sources (178 lines)
- `promo_routes_accounts.py` - Telegram account management (81 lines)
- `promo_reply_routes.py` - Event logs (8 lines)
- `promo_runtime.py` - Workers (105 lines)
- `promo_telegram.py` - MTProto wrapper
- `promo_service.py` - Shared utilities

### Frontend
- `frontend/src/pages/Broadcasts.jsx` - User broadcast UI (233 lines)
- `frontend/src/pages/CentralBroadcasts.jsx` - System update UI (117 lines)
- `frontend/src/pages/Promotions.jsx` - Outreach CRM UI (395 lines)
- `frontend/src/components/MarketingCampaigns.jsx` - Campaign manager component
- `frontend/src/components/BroadcastOptions.jsx` - Shared broadcast controls

### Database
- `db.py` - Schema, indexes (lines 161-183 for promo/outreach)

### Tests
- `tests/test_upgradeversi.py` - Campaign persistence tests
- `tests/test_broadcast_composer_stock.py` - Broadcast logic
- `tests/test_broadcast_reports.py` - Reporting
- `tests/test_central_broadcast_discount.py` - Discount broadcasts
- `tests/test_purchase_source.py` - Source attribution

### Configuration
- `.env.example` - PROMOTION_ENABLED flag (line 53)
- `server.py` - Conditional router mounting (lines 113-117)

---

## Consolidation Action Plan (Draft)

### Phase 1: Frontend Unification
1. Create unified `Broadcasts.jsx` with tabs:
   - Quick Broadcast (existing System 1)
   - Marketing Campaigns (existing System 2)
   - System Updates (existing Central Broadcasts)
2. Update `App.js` routes (remove `/central-broadcasts`)
3. Update `Layout.jsx` menu (single "Broadcast" item)
4. Test UI navigation and state management

### Phase 2: Backend Cleanup
1. Extract shared logic to `broadcast_engine.py`:
   - Image generation interface
   - Template variable substitution
   - Target validation
2. Refactor admin_routes.py to use broadcast_engine
3. Refactor marketing_campaigns.py to use broadcast_engine
4. Remove duplicate code

### Phase 3: API Consolidation (Optional)
1. Namespace under `/api/admin/broadcasts`:
   - `/users` - User broadcast endpoints
   - `/campaigns` - Marketing campaign endpoints (already exists)
   - `/system` - System update endpoints
2. Maintain backward compatibility or version API

### Phase 4: Testing & Validation
1. Run all existing tests
2. Manual smoke tests for each broadcast type
3. Verify inventory allocation still works
4. Verify worker loops continue running
5. Test with real Telegram sends (controlled)

### Phase 5: Documentation
1. Update README with unified broadcast section
2. API documentation updates
3. Migration guide for existing API consumers
4. Admin user guide for new UI

---

## Appendix: Code Metrics

**Backend Python Files:** 72  
**Frontend JSX Files:** 77

**Broadcast-Related Backend:**
- admin_routes.py: ~380 lines broadcast code
- marketing_campaigns.py: 349 lines
- broadcast_composer.py: (referenced, not read)
- broadcast_image.py: (referenced, not read)
- daily_recap.py: (referenced, not read)

**Outreach-Related Backend:**
- promo_campaign.py: 235 lines
- promo_campaign_routes.py: 223 lines
- promo_routes.py: 178 lines
- promo_routes_accounts.py: 81 lines
- promo_reply_routes.py: 8 lines
- promo_runtime.py: 105 lines
- **Total Outreach:** ~830 lines

**Frontend:**
- Broadcasts.jsx: 233 lines
- CentralBroadcasts.jsx: 117 lines
- Promotions.jsx: 395 lines (34,585 bytes)
- MarketingCampaigns.jsx: (size not measured)

---

**End of Audit**
