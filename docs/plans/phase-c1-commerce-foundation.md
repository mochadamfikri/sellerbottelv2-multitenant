# Phase C1 — Commerce Foundation

Status: implementation specification; application changes have not started.
Source: [SellerBottel V3 master architecture](../architecture/sellerbottel-v3-master.md).
Baseline: `026fa480624d36e4a0ef73444cf76b3e9e099fcd`; 681 offline backend tests, 5 frontend suites / 9 tests, CI build passing. Prior live acceptance is PARTIAL, not production certification.

## 1. Outcome and scope

Introduce a tenant-scoped commerce contract for product fulfillment, immutable order-line snapshots, persisted fulfillment records and a single fulfillment registry. Preserve current digital/service checkout behavior through adapters. Cart, quote, checkout and payment remain shared capabilities; fulfillment dispatch starts only after the existing payment/reservation trigger succeeds.

C1 implements existing digital-auto and service behavior behind the new interface. It declares digital-manual, physical and subscription types for future phases but rejects their activation/purchase until handlers are supported. Declaring an enum does not make a product sellable.

Out of scope: physical SKU/variants/stock ledger/address/shipping, recurring billing, new gateways, settlement/payouts, provider credentials, courier integrations, returns, expanded branding and white-label packaging. No production migration/deployment, real payments, DNS/Caddy changes or external integration activation.

## 2. Current integration map

| Existing location | Current responsibility | C1 adaptation |
|---|---|---|
| `backend/admin_routes.py`, `bulk_product_import.py`, `catalog_repository.py`, `v2_commerce_routes.py` | Multiple product write contracts | Shared fulfillment-type validation/default resolver across every writer |
| `backend/checkout.py` | Balance order, coupon, wallet debit and inventory reservation/commit | Persist normalized lines, initialize fulfillment records at the existing allocation trigger; retain financial/reservation ownership |
| `backend/direct_checkout.py` | Bot/web QRIS creation, expiry and payment finalization | Snapshot lines at creation; dispatch after paid transition; expiry cancels/releases unconsumed work |
| `backend/bot.py`, `bot2.py` | Digital delivery and service scheduling after checkout | Channel adapters to shared fulfillment orchestration; eliminate duplicate business dispatch incrementally |
| `backend/storefront_routes.py` | Web balance finalization and completion email | Same orchestration, preserve authenticated customer/download/email contracts |
| `backend/order_fulfillment.py` | Private customer-owned delivery presentation/downloads | Preserve ownership/no-store behavior; read per-line readiness where new records exist |
| `backend/admin_routes.py` order completion/refund | Service completion, eligible refund | Idempotent record transition and legacy status projection, retaining existing financial checks |
| `backend/tenant_full_routes.py` | Owner JWT/lifecycle enforcement and scope | Reuse existing scope; no client-selected database |
| `backend/tenant_orders_repository.py` / V2 routes | Additional tenant order contract | Normalize through the same contracts; do not create another checkout engine |
| `backend/tenant_provisioning.py` | Tenant indexes/settings | Add fulfillment indexes idempotently; migration handles existing DBs |

`order_fulfillment.py` is an existing customer-delivery view, not a durable dispatch registry. C1 must integrate it rather than replace it accidentally. Existing balance checkout commits inventory before channel delivery; preserve that boundary initially. This phase does not redesign wallet/payment accounting.

## 3. Product contract and legacy resolution

Add `fulfillment_type` with values `digital_auto`, `digital_manual`, `service`, `physical`, `subscription`. Persist it for new/edited products; resolve legacy products through one pure helper when the field is absent. Preserve `product_kind`, `delivery_type`, `inventory_mode`, prices and stock fields throughout C1.

Resolution precedence:

1. A valid explicit type is authoritative. Reject conflicts with legacy fields and reject unsupported active types; do not silently route physical/subscription to digital inventory.
2. Legacy `product_kind=service` or `delivery_type=service` resolves to service, unless conflicting legacy data requires review.
3. Known digital inventory/account/file/session/license/link delivery resolves to digital_auto using the existing delivery subtype. Inspect actual persisted shapes before finalizing the mapping.
4. Missing/ambiguous/unknown legacy shapes appear in the migration review report. No guessed physical/manual classification and no automatic destructive rewrite.

No edit may change fulfillment semantics while inventory/reservations or affected pending orders exist unless an explicit safe transition is defined and tested. Existing order snapshots remain authoritative after later product edits/deletion. Declare money representation in the contract, preserving existing rounding; no float-to-Decimal financial rewrite in C1.

## 4. Normalized order lines

Add an order schema version and stable persisted `line_id` to each item. A line snapshot contains product ID, name, quantity, fulfillment type, delivery subtype, inventory mode, currency and quoted monetary fields. Keep legacy aliases such as product_id/pid and qty readable through a single normalizer; new writes use one canonical shape plus explicitly required compatibility fields.

Generate line IDs once before persistence and retries. Legacy migration can derive IDs deterministically from order ID and original item position, then persist them; item order must not be changed during conversion. Do not deduplicate two distinct lines simply because they reference the same product. Never include decrypted inventory, credentials or fulfillment payload secrets in snapshots/API order lists.

An order containing digital and service lines retains both. Physical/manual/subscription lines are contract-testable but remain unpurchasable in C1. Full physical mixed checkout belongs to C2.

## 5. Fulfillment records and registry

Proposed files under `backend/commerce/`: `models.py`, `normalization.py`, `legacy.py`, and `fulfillment/{base,registry,repository,orchestrator,digital_auto,service}.py`. Names may be adjusted to repository conventions; responsibilities must remain separate.

Store records in each tenant DB's `fulfillments` collection. Minimum fields: ID, tenant ID, order ID, line ID, fulfillment type, schema version, requested quantity, state, attempt count, claim/lease information, timestamps, safe failure code and references to existing allocations/delivery tasks. References are not plaintext delivery credentials.

Unique index `(order_id, line_id)` within the tenant DB; query index `(state, next_attempt_at)` and order lookup index. Every record read/update requires resolved tenant scope and order/line ownership. Tenant-ID fields are additional checks, never permission to cross databases.

Interface: handler advertises supported type and processes a claimed record with an explicit tenant/order/line context and channel delivery adapter. Unsupported handlers fail closed with a documented client error before financial debit/reservation. Registry registration must reject duplicate types. Handlers do not select gateways or independently debit/refund wallets.

Digital-auto states: reserved → delivering → delivered; delivering → delivery_failed. Service: queued → processing → completed; cancellation/failure use explicit permitted transitions. Conditional updates enforce legal transitions. Terminal work is not restarted by a repeated callback. Order aggregate status is derived separately from payment and per-line progress.

## 6. Compatibility and aggregate state

Retain existing outward statuses (`paid`, `delivered`, `service_waiting`, `failed`, `delivery_failed`, etc.) wherever current consumers require them. Add a separate fulfillment summary/status for C1 rather than rename all public statuses at once. A mixed digital/service order must not become globally delivered because its first digital line succeeded.

Publish a mapping table during implementation covering bot history, admin filters/refunds, storefront downloads, emails, analytics and V2 order routes. No delivered credential may become visible to another customer or to an unfinished line. Existing completed legacy orders remain readable without creating runnable fulfillment jobs.

## 7. Idempotency, failure and restart

Payment callbacks/retries create records with idempotent upserts. Claims use atomic compare-and-set and bounded leases; completion uses the claim token/version. Repeated payment events may not reserve/consume inventory, refund, schedule service tasks or finalize a fulfillment twice.

The current dedicated dev Mongo is standalone. Do not assume cross-collection transactions are available. Specify write ordering, idempotency keys and repair/reconciliation for crashes between order write, allocation, fulfillment creation, external send and completion write. Reconciliation may repair paid orders missing records; it may not turn unpaid orders into fulfillment jobs.

External delivery cannot be assumed exactly once: a process can crash after Telegram accepts a message but before the DB records success. Classify ambiguous delivery, retain a delivery-attempt key/reference, and require safe reconciliation/manual review when provider acknowledgement cannot be recovered. Do not blindly resend credentials or claim exactly-once external delivery from an internal unique index.

Suspension blocks new claims/delivery and preserves records. Reactivation resumes permitted work without duplicate allocations. Cancellation/expiry releases only the existing reservation owned by that attempt. Refunds preserve current eligibility and financial path; fulfillment failure must not independently initiate a second refund.

## 8. Migration and rollout

Provide a CLI restricted to explicitly configured development tenant databases, with dry-run default, counts/classifications only, resumable batches and an explicit apply option. Never auto-scan/mutate production or read existing project .env by default.

1. Inventory actual legacy shapes from disposable datasets and read-only dev snapshots, excluding secrets.
2. Add shared read normalizers and compatible new-write fields.
3. Add idempotent indexes and fulfillments repository; preserve existing records.
4. Dry-run product/order backfill; ambiguous records remain unchanged and reported.
5. Apply additive backfill to disposable real Mongo; a second run makes no semantic changes.
6. Introduce orchestration behind a default-off development rollout flag. Persist the chosen execution mode on each order so an in-flight order cannot switch engines halfway through a retry.
7. Validate balance and QRIS mock paths on bot and web channels, then enable only dedicated dev tenants after all gates pass.

Historical terminal orders get read-compatible projections or explicitly terminal records; never queue delivery. Pending legacy orders stay with their recorded legacy execution mode unless a separately tested handover procedure exists. Rollback stops new C1 claims and restores new-order legacy routing while retaining additive data and reconciling in-flight C1 orders. Never delete fulfillment/audit records or globally disable idempotency to roll back.

## 9. Implementation sequence and dependency map

| Slice | Depends on | Deliverable / acceptance |
|---|---|---|
| C1.1 Contracts | Current model inventory | Type/line normalizers, explicit legacy mapping, unsupported-type rejection |
| C1.2 Persistence | C1.1 | Fulfillment repository/indexes, tenant ownership, CAS state transitions |
| C1.3 Legacy handlers | C1.1–2 | Digital/service adapters, recorded execution mode, aggregate projection |
| C1.4 Channel integration | C1.3 | Existing balance/QRIS bot/web entrypoints dispatch via same orchestrator |
| C1.5 Migration/recovery | C1.1–4 | Dry-run/resume/backfill, repair, safe rollback and restart behavior |
| C1.6 Acceptance | All above | Offline + frontend as relevant + dedicated real Mongo failure/isolation evidence |

Each slice should be a small reviewable commit with its relevant regression coverage. No feature phase may skip C1 compatibility to start a provider integration. C2 and payment-core P1 depend on the stable contracts; their individual plans must be written separately. Subscription billing and shipping/payment provider selection remain deferred.

## 10. Acceptance criteria

| Gate | Required evidence |
|---|---|
| Legacy digital/service compatibility | Existing start/browse/cart/coupon/balance/QRIS mock/history/admin suites remain green; inventory account/file/session/link delivery cases preserved |
| Normalization | Legacy/new shapes, stable IDs on retry/reorder rejection, immutable snapshots after product edits, ambiguous records reported |
| Writers | Admin/import/catalog/V2 writers apply the same rules; unsupported active types rejected without mutation/debit |
| Mixed digital/service | One order/payment, distinct records, digital progress and service completion retained; aggregate not prematurely complete |
| Fulfillment states | Illegal transitions denied; duplicate callbacks and concurrent claims finalize once |
| Reservations/financial ownership | No second commit/release/debit/refund; insufficient balance and injected delivery failures preserve existing rollback behavior |
| Tenant isolation | A→B and B→A request/DB proof with identical order/line/product IDs; foreign documents unchanged |
| Customer privacy | Owner/customer authorization preserved; no plaintext payloads in summaries, artifacts or logs; downloads remain order/customer-bound |
| Lifecycle | Suspended/disabled/failed/provisioning reject new work; unaffected tenant continues; reactivation resumes safely |
| Recovery | Inject failures at each durable-write/send boundary; restart reconciles missing records; ambiguous sends do not blindly resend |
| Migration | Dry-run no writes; apply/reapply/resume preserve terminal orders and pending legacy routing; rollback retains history |
| Real Mongo | Index uniqueness, races/CAS/lease recovery and migration proven on dedicated dev Mongo, not just mock assertions |
| Frontend | Existing unit tests and CI build; update tests only where new fields/status presentation require changes |
| Completion | Full offline suite + compileall + applicable frontend checks + real dev report; no known P0/P1 remaining |

Reuse existing `test_purchase_source`, checkout/inventory/service/order authorization and commerce security coverage. Add focused meaningful regression tests for the new contracts, recovery and concurrent writes. Counts may grow; never weaken or skip existing tests to retain the baseline.

Live validation must use a fresh dedicated C1 dev Mongo/storage/config, not reset the retained audit runtime's database while its real Telegram worker is polling. External delivery tests require confirmed dev recipients; mock transport remains explicitly labeled. No production credentials/resources or real money.

Required implementation artifacts: migration dry-run/apply summaries without secrets; JUnit/check evidence; `docs/audits/phase-c1-commerce-foundation-<date>.md` with commit SHA, scope, compatibility matrix, real-Mongo isolation/failure evidence, limitations and recommendation.

## 11. Review points before coding

Validate legacy persisted shapes and the compatibility status table in C1.1. Choose the least complex claim/reconciliation mechanism that satisfies the crash tests; no new queue platform is required by this plan. Define money/rounding and digital delivery subtype snapshots explicitly before C1.4. Define expiry/lease timing as documented configuration and test with controlled clocks.

These are implementation design checkpoints, not requests to reconsider the established business decisions. Settlement IDSE remains Kasera-owned and separate from personal GoPay; tenant gateways remain adapter-based; tenant-first branding and physical commerce remain the direction of later phases.
