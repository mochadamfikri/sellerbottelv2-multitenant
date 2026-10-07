# ============================================================
# CODEX EXECUTION PROMPT
# ADDITIONAL REVISION — ADMIN BALANCE + TELEGRAM BROADCAST
# ============================================================

## EXECUTION MODE — IMPORTANT

Remaining Codex usage is limited.

DO NOT restart a full repository audit from zero.

You already have context from the previous work on this repository.

Do NOT:
- re-read unrelated repository files
- redesign unrelated UI
- refactor unrelated working systems
- replace frameworks
- create parallel architectures when an existing system can be extended
- repeat analysis that was already completed
- stop after planning

The repository/database backup from the previous task has already been prepared.

Before editing:

1. Run `git status`.
2. Inspect only files directly related to:
   - admin users
   - user source WEB/BOT
   - balances
   - balance transactions/ledger
   - Telegram bot
   - Telegram transaction broadcast
   - products/variants
   - inventory/stock
   - admin routes/API
   - scheduler/worker/cron/jobs if already available
3. Reuse the existing architecture.
4. Implement the requirements below.
5. Do not touch unrelated previous UI/UX work.

If a requirement can be implemented by extending an existing service/table/component, DO THAT instead of creating a duplicate system.

---

# ============================================================
# IMPLEMENTATION PRIORITY
# ============================================================

MUST FINISH FIRST:

1. Manual balance adjustment for WEB + BOT users.
2. Balance audit/ledger.
3. Telegram identity masking for REAL purchases.
4. Persistent promotional campaign.
5. Random interval scheduling.
6. Random product/variant selection.
7. Marketing stock allocation.
8. Marketing stock restore.
9. Pause / Resume / Stop campaign.
10. Relevant build/typecheck/tests.

ONLY AFTER THE ABOVE WORKS:

- dashboard counters
- cosmetic polish
- advanced campaign statistics
- optional UI enhancements

Do not spend limited execution time on cosmetic refactoring before core behavior works.

---

# ============================================================
# OBJECTIVE
# ============================================================

Implement the following without breaking the existing production system:

1. Admin can manually adjust balance for both WEB users and BOT users.
2. REAL purchase broadcasts to Telegram include privacy-masked Telegram identity.
3. Add automated promotional product broadcasts configurable from Admin Panel.
4. Promotional broadcasts must remain separate from real customer transactions.
5. Promotional stock allocation must NOT count as a real sale.
6. Everything must remain backward-compatible with existing production data.

Existing historical data must remain intact:

- users
- balances
- deposits
- transactions
- orders
- sales
- products
- variants
- inventory
- Telegram mappings

---

# ============================================================
# 1. ADMIN — BALANCE ADJUSTMENT
# ============================================================

Currently manual balance adjustment appears to work only for BOT users.

Fix this so the SAME balance system works for:

- WEB users
- BOT users
- other valid existing user types

DO NOT create separate balance systems.

Use the existing balance source of truth.

Admin flow should support:

Admin
→ Pengguna
→ User Detail / Action
→ Adjust Saldo

The existing user filters:

[ Semua ]
[ Web ]
[ Bot ]

must remain functional.

Admin must be able to adjust users returned from any of those filters.

---

## USER SEARCH

Reuse/extend the existing admin user search.

Support available fields such as:

- display name
- email
- Telegram username
- Telegram ID
- internal user ID

Do not perform full client-side filtering if server-side filtering already exists.

---

# ============================================================
# BALANCE ADJUSTMENT UI
# ============================================================

Use a modal or existing admin interaction pattern.

Example:

------------------------------------------------

Adjust Saldo

User:
Sheima Syabania
sheima@email.com

Source:
WEB

Saldo Sekarang:
Rp 56.480.650

Jenis:
[ Tambah Saldo ]
[ Kurangi Saldo ]

Jumlah:
Rp [____________]

Catatan:
[____________________________]

[ Batal ] [ Konfirmasi ]

------------------------------------------------

If the existing architecture supports multiple currencies, expose the existing currencies.

Example:

[ IDR ]
[ USD ]

Do not introduce currency behavior that does not already exist.

---

# ============================================================
# BALANCE BACKEND SECURITY
# ============================================================

Frontend must NEVER directly set the resulting balance.

Frontend only sends information such as:

- target user
- direction ADD/SUBTRACT
- amount
- currency if applicable
- reason

Backend must:

1. authenticate admin
2. authorize admin
3. validate target user
4. validate amount
5. validate currency
6. read/lock current balance according to current DB architecture
7. update balance atomically
8. create audit/ledger entry
9. return the resulting balance

Use a database transaction where supported.

DO NOT implement balance changes as an unaudited:

UPDATE users SET balance = ...

---

# ============================================================
# BALANCE AUDIT / LEDGER
# ============================================================

Reuse existing transaction/ledger tables if appropriate.

Do not create a duplicate ledger if one already exists.

Every manual adjustment should record as much as the existing schema allows:

- target user ID
- user source WEB/BOT if available
- currency
- amount
- direction ADD/SUBTRACT
- balance before
- balance after
- admin actor
- reason
- timestamp
- reference/request ID

Suggested type if a type is required:

ADMIN_BALANCE_ADJUSTMENT

Use the repository's existing naming conventions.

---

# ============================================================
# ADMIN USER HISTORY
# ============================================================

User detail/history should distinguish manual admin adjustments from:

- payment gateway deposits
- customer purchases
- other transaction types

Example:

+ Rp 100.000
Manual Balance Adjustment
By Admin
29 Sep 2026 00:30
Reason: Manual deposit correction

Do not represent it as a normal customer deposit if it was performed by admin.

---

# ============================================================
# 2. TELEGRAM — REAL PURCHASE BROADCAST
# ============================================================

Find the CURRENT Telegram broadcast implementation used for successful purchases.

Do NOT rebuild the broadcast system from scratch.

Keep the existing purchase message format.

Only extend it with privacy-safe Telegram identity information.

This section applies ONLY to REAL successful customer purchases.

---

# ============================================================
# MASK TELEGRAM USER ID
# ============================================================

Use the REAL Telegram user ID already linked to the actual purchasing user.

Never generate an ID.

Broadcast display rule:

- keep first 3 digits
- keep last 2 digits
- replace everything in the middle with `*`

Examples:

123456789

becomes:

123****89

1234567890

becomes:

123*****90

Formula:

prefix = first 3
suffix = last 2
masked_count = total_length - 5

result:

prefix + "*" * masked_count + suffix

Implement as a reusable helper according to project conventions.

Do NOT mutate the stored Telegram ID.

Mask only at the message/presentation layer.

If the value is malformed or too short, use a privacy-safe fallback instead of crashing the transaction/broadcast flow.

---

# ============================================================
# MASK TELEGRAM USERNAME
# ============================================================

If a REAL Telegram username exists:

@sheimasyabania

display only:

@sh***********

Rule:

- preserve `@`
- preserve first 2 username characters
- replace the remaining username characters with `*`

Do not store the masked username as the canonical username.

If no Telegram username exists:

use:

Username: -

or omit the field if that better matches the existing template.

NEVER generate a fake username.

---

# ============================================================
# REAL PURCHASE IDENTITY SOURCE
# ============================================================

Identity must originate from:

real order
→ real user
→ actual Telegram account mapping

Never:

- generate Telegram IDs
- generate Telegram usernames
- substitute another random user
- expose complete Telegram identity

Do not expose:

- full Telegram ID
- complete username
- email
- phone
- credentials
- payment secrets

---

# ============================================================
# REAL PURCHASE BROADCAST TEMPLATE
# ============================================================

Preserve the existing template.

Add fields similar to:

User ID: 123****89
Username: @sh********

Keep existing transaction information such as:

- purchase success status
- product
- variant if currently shown
- price
- timestamp
- invoice/order reference if currently shown

Do not unnecessarily redesign the existing channel message.

---

# ============================================================
# TELEGRAM ID STORAGE
# ============================================================

Audit the existing Telegram ID field only if necessary.

Telegram identifiers must not rely on signed 32-bit storage.

Do not perform a destructive schema conversion.

If the current schema already safely stores IDs, leave it alone.

Do not infer Telegram account creation year from numeric prefixes.

---

# ============================================================
# 3. AUTOMATED PROMOTIONAL BROADCAST
# ============================================================

Add an Admin feature:

Admin
→ Marketing / Broadcast

If a broadcast administration section already exists, extend it instead of creating another menu.

Purpose:

Schedule promotional product messages to the configured Telegram channel.

PROMOTIONAL broadcasts MUST remain technically and statistically separate from genuine customer purchases.

Do NOT create fake customer records.

Do NOT fabricate Telegram identities.

Do NOT record promo messages as REAL SALE.

---

# ============================================================
# PROMOTIONAL MESSAGE LABEL
# ============================================================

Promotional messages must be identifiable as promotional content.

Example:

PROMO IDSE
Produk Pilihan

or another equivalent label consistent with the existing design.

Do not claim a customer completed a purchase if no actual customer purchase occurred.

---

# ============================================================
# ADMIN CAMPAIGN SETTINGS
# ============================================================

Admin should be able to configure:

Campaign Name

Telegram Channel:
reuse existing configured destination

Minimum Interval:
[ 5 ] minutes

Maximum Interval:
[ 70 ] minutes

Number of Broadcasts:
[ 30 ]

Products:
[ All Eligible Products ]

or selected products/catalogs if straightforward with the existing architecture.

Campaign Status:

ACTIVE
PAUSED
COMPLETED
STOPPED
FAILED

or equivalent existing naming conventions.

---

# ============================================================
# RANDOM INTERVAL
# ============================================================

`minimum_interval` and `maximum_interval` represent the DELAY BETWEEN messages.

Example:

minimum = 5
maximum = 70

Valid sequence could be:

5 min
13 min
7 min
41 min
18 min
63 min

Do NOT produce fixed sequences such as:

5
10
15
20
25

Each next interval should be randomly selected inside the configured range.

No cryptographically secure RNG is required unless the current architecture naturally provides one.

Validate:

minimum > 0
maximum >= minimum
count > 0

Add reasonable upper limits if necessary to prevent accidental spam.

Respect existing Telegram/API rate limits.

---

# ============================================================
# CAMPAIGN PERSISTENCE
# ============================================================

DO NOT implement the campaign with browser `setTimeout`.

Campaign state must persist server-side.

Campaign must continue to be recoverable when:

- admin closes the browser
- admin refreshes the page
- server restarts
- application is redeployed

First inspect whether the project already has:

- cron
- scheduler
- worker
- queue
- background task
- recurring application job

Reuse it.

Do NOT add Redis/BullMQ/etc just because it is convenient if the project already has a viable scheduling mechanism.

If no scheduler exists, implement the smallest robust server-side mechanism consistent with the existing stack.

---

# ============================================================
# CAMPAIGN PROGRESS
# ============================================================

Admin should be able to see:

Campaign Name

Target:
30

Sent:
12

Remaining:
18

Next Scheduled:
...

Status:
ACTIVE

Actions:

[ Pause ]
[ Resume ]
[ Stop ]

Implement only what is needed to make the campaign controllable and persistent.

---

# ============================================================
# PAUSE / RESUME / STOP
# ============================================================

PAUSE:

- prevent future sends
- preserve remaining campaign events/state

RESUME:

- continue unsent work
- calculate/resume scheduling safely

STOP:

- cancel future unsent campaign events
- do not undo already-sent events automatically
- do not corrupt existing inventory records

Use clear persisted status.

---

# ============================================================
# 4. RANDOM PRODUCT SELECTION
# ============================================================

Promotional messages should select products/variants from the REAL product database.

Eligible product/variant requirements:

- active
- not archived
- valid variant
- stock available for marketing allocation
- purchasable according to the existing system

Selection should vary.

Avoid choosing the exact same product/variant consecutively when other eligible choices exist.

Example:

Claude Pro 1 Bulan
ChatGPT
Canva
Claude Pro 3 Bulan

instead of repeatedly using one product when alternatives exist.

Keep the algorithm simple.

Do not create an unnecessarily complex recommendation engine.

---

# ============================================================
# 5. MARKETING STOCK ALLOCATION
# ============================================================

Each promotional broadcast may allocate one actual product/variant stock if this matches the existing inventory model.

IMPORTANT:

This must NOT be recorded as a customer SALE.

Use a separate inventory reason/type.

Suggested semantic type:

OWNER_MARKETING_ALLOCATION

or:

MARKETING_ALLOCATION

Admin-facing label may be:

By Me

Use repository naming conventions.

---

# ============================================================
# STOCK EXAMPLE
# ============================================================

Before:

Claude Pro 1 Bulan

Available:
10

Marketing Allocated:
0

Sold:
existing value

After one promotional allocation:

Available:
9

Marketing Allocated:
1

Sold:
UNCHANGED

Sales statistics:
UNCHANGED

Revenue:
UNCHANGED

Customer orders:
UNCHANGED

---

# ============================================================
# INVENTORY LEDGER
# ============================================================

If the application already has an inventory/stock ledger, extend it.

Do not create a second competing stock system.

Suggested allocation event:

type:
OWNER_MARKETING_ALLOCATION

quantity:
-1

reference:
campaign_event_id

Restore:

type:
OWNER_MARKETING_RESTORE

quantity:
+1

reference:
original allocation or campaign event

Use the actual existing architecture if different.

---

# ============================================================
# STOCK ALLOCATION TRANSACTION
# ============================================================

When preparing/sending a campaign event:

1. select eligible product/variant
2. atomically verify stock
3. allocate one unit
4. create/update inventory ledger
5. link allocation to campaign event
6. send Telegram message
7. update event status

Do not allow negative stock.

Avoid:

read stock
→ wait
→ blindly write stock

Use an atomic update/transaction/locking pattern appropriate to the current database.

---

# ============================================================
# REAL CUSTOMER PURCHASE PRIORITY
# ============================================================

Campaign allocation must not corrupt genuine customer checkout.

If the selected variant becomes unavailable before allocation:

- do not create negative stock
- skip it
- select another eligible product if possible

If no eligible stock remains:

handle the campaign event safely according to the current system.

Do not fabricate inventory.

---

# ============================================================
# 6. RESTORE MARKETING STOCK
# ============================================================

Admin must have a way to restore stock previously allocated to marketing.

Could be placed under:

Inventory
→ Marketing Allocation

or integrated into the existing stock/admin UI.

Example:

Claude Pro 1 Bulan

Marketing allocated:
3

[ Restore 1 ]
[ Restore All ]

Restore must:

- return quantity to available stock
- reduce marketing allocation
- create ledger/audit record
- NOT create revenue
- NOT create customer sale
- NOT modify historical customer sales

Ensure a unit cannot accidentally be restored twice.

---

# ============================================================
# CAMPAIGN EVENT / IDEMPOTENCY
# ============================================================

Use an event/reference identifier so retries cannot decrement stock multiple times.

Conceptually an event may contain:

id
campaign_id
product_id
variant_id
inventory_allocation_reference
scheduled_at
sent_at
status
telegram_message_id
error

Use existing DB conventions.

Do not add unnecessary columns if existing models already cover them.

---

# ============================================================
# TELEGRAM SEND FAILURE
# ============================================================

If Telegram send fails:

- mark event FAILED / RETRYABLE according to existing conventions
- retain safe error information
- do not repeatedly decrement stock on retry
- ensure retry is idempotent

If the product was already allocated before the send failed, retry should reuse that allocation instead of allocating another unit.

Do not create duplicate broadcast events.

---

# ============================================================
# CAMPAIGN LOG
# ============================================================

Persist enough information to audit:

- campaign
- event
- selected product
- selected variant
- scheduled time
- actual send time
- status
- Telegram message ID if returned
- inventory allocation reference
- admin creator

Keep this concise and reuse existing audit infrastructure where possible.

---

# ============================================================
# ADMIN DASHBOARD / UI
# ============================================================

Minimum required Admin UI:

Marketing / Broadcast

Create campaign form

Campaign list

Campaign detail/progress

Actions:

Pause
Resume
Stop

Optional summary cards only AFTER core implementation works:

Active Campaigns
Messages Sent
Pending
Failed
Marketing Stock Allocated

Do not delay core functionality for dashboard cosmetics.

---

# ============================================================
# SALES / REPORTING SEPARATION
# ============================================================

MARKETING / OWNER allocations MUST NOT increase:

- sales count
- revenue
- successful purchases
- customer order count
- conversion metrics

Existing sales dashboards must continue to represent actual customer transactions only.

Do not rewrite historical sales queries unless necessary.

Verify that new marketing records are excluded.

---

# ============================================================
# CHANNEL CONFIGURATION
# ============================================================

Reuse the existing Telegram bot/channel configuration.

Do not hardcode:

- bot token
- channel ID
- API credentials

Use existing environment/configuration mechanisms.

Do not print secrets to logs.

---

# ============================================================
# DATABASE MIGRATION SAFETY
# ============================================================

If schema changes are required:

- inspect the existing schema first
- use additive/backward-compatible migrations
- extend existing tables where appropriate
- do not duplicate equivalent tables

DO NOT run:

DROP TABLE
TRUNCATE
database reset
prisma migrate reset
destructive reset commands

Do not remove historical columns/data.

If a migration command could alter production data destructively, stop and choose a safer migration.

The previous backup exists, but that is NOT permission to destroy production data.

---

# ============================================================
# DATABASE TRANSACTIONS
# ============================================================

Use database transactions where appropriate for:

- balance adjustment
- audit record creation
- inventory marketing allocation
- inventory restore

Balance update and its audit record should succeed/fail together.

Inventory update and its allocation ledger should succeed/fail together.

---

# ============================================================
# ACCEPTANCE TEST — BALANCE
# ============================================================

WEB user:

Admin
→ Users
→ WEB
→ Select user
→ Add Rp 100.000

Expected:

- balance updated
- audit/history entry exists
- user source remains WEB
- no Telegram account required
- existing transaction history remains intact

BOT user:

repeat the same process.

Expected:

- works
- no regression from existing BOT functionality

Also test SUBTRACT if implemented by the current UI requirement.

Prevent invalid/negative results according to existing business rules.

---

# ============================================================
# ACCEPTANCE TEST — REAL TELEGRAM PURCHASE
# ============================================================

Actual Telegram ID:

123456789

Broadcast:

123****89

Actual Telegram ID:

1234567890

Broadcast:

123*****90

Actual username:

@sheimasyabania

Broadcast:

@sh***********

Verify:

- database still stores the original value
- only broadcast output is masked
- full identity is never leaked
- real purchase still completes if Telegram broadcast fails according to existing behavior

---

# ============================================================
# ACCEPTANCE TEST — CAMPAIGN
# ============================================================

Create campaign:

minimum interval:
5

maximum interval:
70

count:
30

Expected:

- campaign persists
- intervals vary randomly
- no fixed 5/10/15 pattern
- product selection varies when alternatives exist
- browser refresh does not lose state
- Pause prevents future sends
- Resume continues remaining events
- Stop cancels future unsent work
- campaign events remain auditable

Do NOT wait hours in automated tests.

Test scheduling logic deterministically/unit-level where possible, while verifying persistence and worker behavior without literally waiting 5–70 minutes.

---

# ============================================================
# ACCEPTANCE TEST — INVENTORY
# ============================================================

Initial:

Claude Pro 1 Bulan

Available:
10

Marketing Allocated:
0

Campaign allocation:

Expected:

Available:
9

Marketing Allocated:
1

Sold:
UNCHANGED

Revenue:
UNCHANGED

Restore allocation:

Expected:

Available:
10

Marketing Allocated:
0

Sold:
UNCHANGED

Revenue:
UNCHANGED

Ensure restore cannot duplicate stock.

---

# ============================================================
# REGRESSION CHECK
# ============================================================

Do not extensively retest unrelated features unless required.

At minimum verify that these existing systems are not broken:

- admin login/auth
- user list/filter WEB/BOT
- existing BOT balance adjustment
- WEB balance
- checkout
- real stock decrement on real purchase
- real sales statistics
- Telegram real transaction broadcast
- product/variant inventory

---

# ============================================================
# TEST / BUILD STRATEGY
# ============================================================

To conserve execution usage:

First run tests/typecheck specifically related to changed components if the repository supports targeted execution.

Then run the normal final build/typecheck required for production confidence.

Do not repeatedly run a full expensive build after every small edit.

Typical sequence:

1. implement
2. targeted checks
3. fix errors
4. final build/typecheck
5. final git diff review

Use the actual scripts from the repository.

Do not invent commands that the project does not have.

---

# ============================================================
# STOP CONDITIONS
# ============================================================

Do NOT stop just to provide an implementation plan.

Continue implementing unless:

1. there is a genuinely destructive migration risk
2. an essential secret/configuration is missing and implementation cannot safely proceed
3. production architecture contradicts this specification in a way that risks data corruption

If a minor ambiguity exists, follow the current repository architecture and continue.

---

# ============================================================
# FINAL REVIEW
# ============================================================

Before finishing:

Run:

git status
git diff --stat

Review modified files.

Confirm no:

- secret
- bot token
- password
- credential
- database dump
- sensitive Telegram data

was accidentally added to the repository.

---

# ============================================================
# FINAL REPORT — KEEP IT CONCISE
# ============================================================

After completing implementation, report only:

IMPLEMENTATION SUMMARY

Balance:
- what changed

Real Telegram broadcast:
- what changed

Promotional campaigns:
- what changed

Inventory:
- what changed

Database migration:
- migration/schema changes

Files changed:
- concise list

Tests/build:
- PASS/FAIL + commands

Production data:
- how backward compatibility was preserved

Remaining issues:
- only real unresolved issues

Do not spend significant remaining execution budget writing a long report.

---

# ============================================================
# FINAL NON-NEGOTIABLE RULES
# ============================================================

REAL PURCHASE:

- must come from a real order
- must use the real linked Telegram account
- identity must only be masked at output
- never fabricate Telegram identity

PROMOTIONAL BROADCAST:

- must be classified as promotional/marketing
- must remain separate from customer sales
- must not fabricate customers
- must not affect sales/revenue statistics

MARKETING STOCK:

- may reduce AVAILABLE inventory
- must be classified separately
- must be restorable
- must not become SOLD
- must not increase revenue

ADMIN BALANCE:

- must work for WEB users
- must continue working for BOT users
- must use the existing balance source of truth
- must create an auditable record

PRODUCTION:

- preserve all existing users
- preserve all existing balances
- preserve all existing deposits
- preserve all existing transactions
- preserve all existing orders
- preserve all historical sales
- preserve all existing product/inventory data

IMPLEMENT THE REQUIREMENTS NOW.
Do not stop after analysis.
