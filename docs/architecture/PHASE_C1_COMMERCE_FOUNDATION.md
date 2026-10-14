# Phase C1 — Commerce Foundation

Implementation branch: `feature/v3-c1-commerce-foundation`. Scope follows [V3 master](sellerbottel-v3-master.md). This phase adds a shared fulfillment seam to existing V2 checkout; wallet, coupon, QRIS reservation, Telegram menus and customer delivery APIs retain their contracts.

## Classification and compatibility

`backend/commerce/fulfillment_types.py` owns the five canonical values:

| Type | C1 operational behavior | Initial state |
|---|---|---|
| `digital_auto` | Existing V2 inventory/file/link delivery adapter | `reserved` |
| `service` | Existing queue and completion adapter | `queued` |
| `digital_manual` | State foundation, no delivery callback | `pending` |
| `physical` | Pending placeholder, no shipping | `pending` |
| `subscription` | Pending placeholder, no billing | `pending` |

Valid explicit `fulfillment_type` wins. Without it, legacy `product_kind=service` or `delivery_type=service` maps to service. Legacy digital/inventory/session/link/file/license/account/redeem-code products map to digital-auto. Missing kind and delivery fields retain the legacy digital catalog/link default. Recognizable future kinds map to their canonical values. Unknown explicit values and ambiguous legacy values raise safe domain errors; a backfill leaves these records untouched and counts them for review.

Legacy inventory selection remains the V2 rule, gated by canonical digital-auto: digital kind, inventory delivery, or inventory-enabled. Legacy delivery format and mode fields remain necessary for account/session/file formatting. Product creation, update, activation, bulk import, inventory import, and the injected catalog repository write the canonical field. Legacy UI changes between digital and service derive a new canonical value when no explicit value is supplied; changing a product never changes a normalized existing order.

Future types can exist as inactive backend records. Activating them or sending them through operational checkout is rejected before payment. No physical/manual/subscription UI was added.

## Order snapshots

New balance, main-bot QRIS, storefront QRIS, Bot 2 QRIS, and injected repository order creation normalize items before insertion. `commerce_schema_version=1` identifies this representation. Each item retains old fields and adds:

- Stable UUID5 `line_id`, based on order ID and line position.
- `product_id`, `name`, positive integer `quantity` and compatibility `qty`.
- Numeric `unit_price`, `subtotal`; nullable `variant_id` and `sku`.
- Canonical `fulfillment_type` and `fulfillment_group_key=line_id`.
- Metadata and a `fulfillment_snapshot` containing classification, delivery/inventory format, schema and service queue parameters.

Names, quantities, prices and classification are frozen. Delivery payloads remain in the existing protected inventory/product storage; they are not copied into fulfillment records or logs. Channel adapters combine the stored snapshot with a live payload lookup. Later product edits cannot substitute a different fulfillment handler, name or delivery format.

Paid legacy orders may be normalized lazily. Existing line-level delivery facts are preferred to an edited product. Where historical fields were never captured, C1 cannot recover missing purchase-time facts; `commerce_snapshot_origin=legacy_reconstructed` makes that limitation explicit. The migration helper does not rewrite historical orders. Terminal historical orders are marked as already executed when records are materialized and never replayed.

## Records, grouping and indexes

Fulfillments live in each merchant's own database. Each line has exactly one record; even two lines with the same product ID remain distinct. Mixed types share one payment/order, with a separate record per line. Duplicate line IDs are rejected.

Record fields: deterministic `_id`, `tenant_id`, `order_id`, `line_id`, `type`, `status`, `item_refs`, `attempts`, `error_code`, `error_detail_safe`, `created_at`, `updated_at`, `completed_at`. Internal execution fields are `execution_status`, claim token and lease expiry. No inventory credentials are stored here.

The tenant ID is the validated registry owner ID. The central bot scope is resolved to that same owner ID before accessing records, so central and owner APIs cannot create separate idempotency namespaces in one database; legacy unscoped operation uses `legacy:<database-name>`. Orders from the injected V2 repository may carry the validated tenant slug instead of registry UUID. That alias is accepted only by the repository constructed from the same scope, whose active registry/database binding is checked before routing.

Required indexes:

1. Unique `(tenant_id, order_id, line_id)` for creation idempotency.
2. `(tenant_id, execution_status, lease_expires_at)` for reconciliation.

Provisioning and legacy startup initialize these indexes idempotently. Lazy materialization also ensures them for retained tenant databases. No shared platform business-data collection is introduced.

## Payment, routing and idempotency

Existing stock reservation still occurs before payment when required. Payment confirmation precedes record creation. Balance checkout creates records before committing reserved inventory, so record-insert failure can refund the wallet and release the reservation using the existing compensation path. QRIS creates records after its payment CAS and before consumption/delivery. Insert failure leaves a controlled failed-delivery state, never a success claim.

`ensure_order_fulfillments` loads the actual paid order in the current database. A unique upsert creates each record once. A compare-and-set freezes any lazy legacy normalization; losing writers reload the winning snapshot. `route_item` matches the persisted line, rejects a changed caller snapshot, resolves the registered handler and atomically claims ready work. Attempts increment only for the winning claim.

A completed execution returns its stored state without invoking delivery again. Concurrent/repeated paid callbacks cannot create duplicate work or claim one line twice. Existing payment/order CAS also prevents repeated QRIS consumption. Same-product lines select separate deterministic slices of sold inventory, including customer display and email attachments.

Digital and service handlers call existing V2 adapters. Physical, subscription and manual placeholders return pending without invoking an external delivery callback. Service records become completed with existing admin completion and legacy Telegram queue completion.

External messaging and Mongo are not one transaction. If a process dies after a send but before acknowledgement persistence, C1 **does not blindly resend**. Running claims expire into an ambiguous reconciliation state when `mark_ambiguous_claims` is invoked. Failed/ambiguous records cannot be automatically claimed again. Operator reconciliation is deferred; C1 does not promise exactly-once external transport under every crash. This favors preventing duplicate credentials over automatic recovery. No automatic startup replay worker is added.

## State transitions

| Type | Allowed transitions |
|---|---|
| digital-auto | reserved → delivering/cancelled; delivering → delivered/delivery_failed |
| service | queued → processing/completed/failed/cancelled; processing → completed/failed/cancelled |
| digital-manual | pending → processing/cancelled; processing → delivered/failed/cancelled |
| physical | pending only |
| subscription | pending only |

Terminal states cannot be reopened. Repeating the same transition is idempotent. Completion refuses a running execution, preventing an admin completion from being overwritten by a concurrent queue callback. State changes use CAS.

## Tenant enforcement and API errors

Router context must match its database and tenant ID. Active registry status and database binding are checked before record creation and execution, including a second check after claim. A suspended or mismatched context cannot execute a handler. A lifecycle change after claim leaves unexecuted work blocked for reconciliation rather than sending under an invalid scope.

Owner-only `GET /api/public/tenant/full/orders/{oid}/fulfillments` is additive, verifies order ownership using the existing scoped owner API and omits internal claim tokens. Foreign order IDs return 404; database outages return retryable 503. Customer-facing menus and terminology stay unchanged. Existing customer credential APIs still require completed orders and customer ownership.

Domain errors contain fixed safe messages. Logs contain tenant/order/fulfillment IDs, type/state and exception class only. Handler exception messages and credentials are excluded from new persisted errors. Database errors return 503 with safe text.

## Migration

`commerce.migration.backfill_products` accepts an already validated tenant database and ID. It is dry-run by default, additive, idempotent and uses CAS against classification edits. It never deletes fields or rewrites orders. Explicit classifications remain authoritative; ambiguity is counted and left untouched.

`tools/migrate_c1_products.py --tenant <slug>` provides a development-only CLI. `--apply` enables writes. It requires explicitly configured development environment, `PYTHON_DOTENV_DISABLED=1`, and the dedicated localhost Mongo port 27019; it never reads the project's `.env`. The CLI resolves the registry rather than accepting arbitrary database names. No migration runs at startup.

## Deferred work

C2 physical SKU/stock, P1 payment core, P2 settlement IDSE, P3 tenant gateways, S1 shipping, R1 returns/refunds and B1 branding/white label remain deferred. Subscription billing, a manual fulfillment UI and automatic crash reconciliation are not operational in C1. Current payment provider code is reused only through existing mocked regression flows; no provider integrations were added.

Repeated live runs retain fresh disposable databases instead of resetting audit data. The dedicated Mongo container needs a sufficient open-file limit; the harness checks for at least 65,535 before writes. During validation its inherited soft limit of 1,024 caused a WiredTiger file-limit crash. Restart preserved its volume; raising the process soft limit to 65,535 restored operation. This process-level tuning must be re-applied if that container is restarted without a persistent Docker nofile configuration. The harness fails early rather than silently creating more tenants under a low limit.

See [C1 audit](../audits/phase-c1-commerce-foundation-20261008.md) and its evidence for final gates.
