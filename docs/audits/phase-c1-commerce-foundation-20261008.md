# Phase C1 — Commerce Foundation audit (2026-10-08)

**PHASE C1 RESULT: PASS.** Final regression: **729 backend tests**, **47 focused C1 domain tests**, **5 frontend suites / 9 tests**, CI frontend build, and **53 real-Mongo acceptance checks** passed. No unresolved P0/P1. One non-blocking development-container configuration follow-up is documented below.

## Git and scope

- Starting SHA: `026fa480624d36e4a0ef73444cf76b3e9e099fcd`.
- Validated implementation ending SHA: `5ae4986f0f67a01ff5a99516022b827158542975`.
- Branch: `feature/v3-c1-commerce-foundation`.
- Final documentation/evidence commit SHA is recorded after commit in `test_reports/phase-c1-commerce-foundation-20261008/git-final.json`. Recording a document's own commit hash inside that commit is circular; the report's committed ending SHA above identifies the complete implementation, and the external final record identifies the final branch tip.
- Only development code and dedicated localhost Mongo were used. No production deployment, provider integration, DNS/Caddy change, original `.env` write, real Telegram message or SMTP delivery occurred in this phase.
- Before C1 the working tree held the previously requested master architecture and phase plan. They were retained and included in the documentation commit. No unrelated user changes were overwritten.

## Acceptance matrix

| Gate | Result |
|---|---|
| Backend full regression | PASS — 729 tests; baseline 681 retained |
| Frontend unit | PASS — 5 suites / 9 tests |
| Frontend CI build | PASS |
| Fulfillment type resolver | PASS |
| Legacy digital mapping | PASS |
| Legacy service mapping | PASS |
| Order item normalization | PASS |
| Historical snapshot stability | PASS — new snapshots frozen; legacy reconstruction explicitly marked |
| Fulfillment model | PASS |
| Fulfillment router | PASS |
| Mixed-order grouping | PASS — one record per line, complete and unique |
| Fulfillment idempotency | PASS — atomic real Mongo upserts/claims; central/owner share identity |
| Digital auto regression | PASS |
| Service regression | PASS — admin and legacy queue completion preserved |
| Tenant isolation | PASS — scoped DB/IDs, foreign read and mutation denied |
| Real Mongo validation | PASS — 53 checks; delivery/provider transports mocked |
| Restart/index idempotency | PASS — backend restart and repeated index initialization |
| Secret-safe logs | PASS |
| Shipping | DEFERRED |
| Physical SKU/stock | DEFERRED |
| Payment provider adapters | DEFERRED |
| Settlement | DEFERRED |
| White-label expansion | DEFERRED |

## Legacy mapping and usage audit

The [usage inventory](../architecture/phase-c1-legacy-usage-inventory.md) covers every matching baseline use of `product_kind`, `delivery_type`, `inventory_mode` and `service_wait_minutes`: 17 files and 45 containing function/model groups, classified as must remain, should call resolver, or future C2 concern. V2 formatting, inventory representation, service timers, UI defaults and HTTP legacy fields remain in place; checkout routing is wrapped by canonical normalization/adapters.

Valid explicit canonical classification wins. Legacy digital inventory/session/account/file/link cases map to `digital_auto`. Legacy service kind or service delivery maps to `service`, never digital-manual. Completely absent legacy classification retains the existing digital catalog/link default. Invalid explicit or ambiguous legacy values fail safely; migration counts them and leaves their documents unchanged.

## Data model

Products gain `fulfillment_type` on new/updated writes; old fields remain. Existing products continue through the resolver without mandatory migration. Future types can be stored inactive but cannot be activated or purchased through operational C1 checkout.

New order items snapshot product ID, name, quantity, price/subtotal and fulfillment type, with stable line/group IDs, nullable SKU/variant, metadata and delivery/schema/service configuration. Both `quantity` and compatibility `qty` remain. Snapshot values take priority over later product edits. Legacy paid normalization preserves captured line-level delivery facts and records `legacy_reconstructed`; historical facts never captured by V2 cannot be recreated reliably. The backfill tool deliberately does not rewrite historical orders.

Tenant-local fulfillment records contain safe routing/state metadata, item references, attempts, timestamps and safe error codes. Unique `(tenant_id, order_id, line_id)` and recovery indexes initialize idempotently. Central bot context resolves the same registry owner ID as owner APIs, preventing separate claims in the same merchant database. V2 tenant-slug order IDs are accepted only as a validated same-tenant alias.

## Router and timing

Digital-auto and service handlers reuse V2 channel functions. Digital-manual, physical and subscription handlers safely return pending without digital delivery. Future checkout/UI is unavailable. No extra payment/order is created for mixed items; one fulfillment per line avoids accidental grouping loss.

Confirmed payment creates records before execution. Balance insertion failure occurs before inventory commitment, allowing existing refund/reservation compensation. QRIS order/payment CAS, unique fulfillment upsert and atomic execution claim guard repeated success signals. Two lines for the same product receive distinct inventory slices, including customer delivery display/email attachments. Service completion updates records and legacy order status.

Failed/running/ambiguous work is never blindly replayed. Mongo persistence and external messages are not a distributed transaction: a crash after a transport send but before recording acknowledgement requires manual reconciliation. C1 prevents automatic duplicate delivery but does not claim universal exactly-once external transport. Automatic recovery workers and reconciliation UI remain deferred.

The additive owner endpoint `/api/public/tenant/full/orders/{oid}/fulfillments` verifies the existing order in the current tenant database and hides claim tokens. Cross-tenant IDs return 404. Mongo outage responds 503; safe exception classes replace raw new commerce failure text.

## Tests and evidence

Commands used from the indicated directories:

```bash
# backend
/tmp/sellerbottel-audit-venv/bin/python -m compileall -q .
/tmp/sellerbottel-audit-venv/bin/python run_offline_tests.py tests/test_commerce_foundation.py -q
/tmp/sellerbottel-audit-venv/bin/python -u run_offline_tests.py tests/ -q --junitxml=/home/sellerbottelv2/test_reports/phase-c1-commerce-foundation-20261008/backend.xml
# frontend
CI=true npm test -- --watchAll=false --runInBand
CI=true npm run build
# repository root
/tmp/sellerbottel-audit-venv/bin/python tools/validate_c1_live.py
git diff --check
```

Full backend: **729 passed**, existing deprecation warnings only. Focused domain: **47 passed**. Frontend: **5 suites, 9 tests passed**. CI build and compilation passed. No existing green test was deleted or skipped. Existing test doubles were extended for the additive collection and product lookup; the tenant balance fixture now supplies a real active registry binding. Bot 2's existing balance test was strengthened to require delivered status and a completed fulfillment.

Evidence: [`test_reports/phase-c1-commerce-foundation-20261008`](../../test_reports/phase-c1-commerce-foundation-20261008). The harness uses actual Mongo persistence on `127.0.0.1:27019`, fresh isolated C1 platform/tenant databases and HTTP backend port 8003. Telegram, notification, SMTP and payment transports stay mocked. Python runtime was 3.14 in the development audit venv; this is local regression evidence, not a claim that remote CI ran.

## Live development findings

**53 checks passed**. Registration/owner login/product writes used the real HTTP backend and Mongo. Balance digital/service checkout, snapshots after product edits, mixed records, repeated/concurrent routing, failure compensation, duplicate mock QRIS success, identical order IDs across databases, foreign record reads/mutations, suspended routing, central/owner shared claims, migration dry-run, repeated indexes and restart were verified. New temporary backend processes were stopped by the harness. Retained earlier audit tenants were not reset; their registry counts remained unchanged.

The real-Mongo validation intentionally retains disposable C1 databases rather than deleting them. Repeated runs exposed the dedicated Mongo container's inherited file limit: WiredTiger encountered error 24 (Too many open files), then exit 14. The existing container was restarted with its original volume; no database reset or volume replacement occurred. Its soft limit was raised from 1,024 to 65,535 within the existing hard limit 524,288, and the final live run passed. The harness now checks this prerequisite before writes. `mongo-recovery.json` records safe details. The temporary failed provisioning returned retryable HTTP 503 rather than false authentication/ownership errors.

## Defects found and fixed

| Severity | Reproduction / root cause | Fix / regression evidence |
|---|---|---|
| P0 | Two order lines share a product; old allocation map selects the last reservation for both and can repeat the same credential | Deterministic distinct sold-inventory slices; unit and real Mongo same-product-line checks |
| P0 | Central bot scope and owner API use different tenant IDs for one database; tenant-keyed upserts could create two execution claims | Resolve central scope to registry owner ID before repository access; offline and real Mongo central/owner delivery-once tests |
| P1 | Product classification/name changes after purchase, changing later routing | Frozen normalized order snapshot plus legacy captured-delivery precedence; offline and live edited-product checks |
| P1 | Fulfillment insertion fails after balance debit | Ensure before inventory commit; existing refund/release compensation; injected offline/live insert failure tests |
| P1 | Repeated/concurrent payment/execution events | Unique upserts and atomic claims; repeated real QRIS success and concurrency tests |
| P1 | Completing service only changes old global order status | Update service records with existing completion paths; domain/live service checks |
| P1 | New provisioning index collection and order product lookup absent from old test doubles | Extend faithful mocks without removing assertions; full regression passes |
| P1 development infrastructure | Repeated disposable tenants exceed Mongo soft nofile limit, producing WiredTiger panic | Restart retained-volume container, raise current soft limit, fail-fast harness preflight; final 53 live checks pass |

P0 remaining: **0**. P1 remaining: **0**. P2 remaining: **1** environment follow-up: configure a persistent adequate Docker nofile limit, or reapply the process tuning after restarting the dedicated audit Mongo. Current process is tuned; the harness prevents a low-limit run from creating more databases. This does not change production or application deployment configuration.

## Migration

`tools/migrate_c1_products.py --tenant <slug>` is dry-run by default; `--apply` enables an additive tenant-scoped backfill. It validates dedicated development environment and registry binding, never loads `.env`, leaves explicit classifications authoritative, uses CAS against product edits and does not touch historical orders. Unit tests verify dry-run preservation, repeat application idempotency and untouched ambiguity; real Mongo verifies dry-run data preservation. Startup never auto-runs the backfill.

## Exact changed files

- `.gitignore`
- `backend/admin_routes.py`
- `backend/bot.py`
- `backend/bot2.py`
- `backend/bulk_product_import.py`
- `backend/catalog_repository.py`
- `backend/checkout.py`
- `backend/commerce/__init__.py`
- `backend/commerce/fulfillment/__init__.py`
- `backend/commerce/fulfillment/adapters.py`
- `backend/commerce/fulfillment/base.py`
- `backend/commerce/fulfillment/registry.py`
- `backend/commerce/fulfillment/repository.py`
- `backend/commerce/fulfillment/router.py`
- `backend/commerce/fulfillment_types.py`
- `backend/commerce/migration.py`
- `backend/commerce/order_items.py`
- `backend/db.py`
- `backend/direct_checkout.py`
- `backend/error_handlers.py`
- `backend/inventory.py`
- `backend/order_fulfillment.py`
- `backend/storefront_routes.py`
- `backend/tenant_full_routes.py`
- `backend/tenant_orders_repository.py`
- `backend/tenant_provisioning.py`
- `backend/tests/test_bot2_flow.py`
- `backend/tests/test_bot_dispatcher_regression.py`
- `backend/tests/test_commerce_foundation.py`
- `backend/tests/test_tenant_orders_repository.py`
- `backend/tests/test_tenant_provisioning_index_contracts.py`
- `backend/v2_commerce_routes.py`
- `docs/architecture/PHASE_C1_COMMERCE_FOUNDATION.md`
- `docs/architecture/phase-c1-legacy-usage-inventory.md`
- `docs/architecture/sellerbottel-v3-master.md`
- `docs/audits/phase-c1-commerce-foundation-20261008.md`
- `docs/plans/phase-c1-commerce-foundation.md`
- `test_reports/phase-c1-commerce-foundation-20261008/backend.log`
- `test_reports/phase-c1-commerce-foundation-20261008/backend.xml`
- `test_reports/phase-c1-commerce-foundation-20261008/domain.log`
- `test_reports/phase-c1-commerce-foundation-20261008/frontend-build.log`
- `test_reports/phase-c1-commerce-foundation-20261008/frontend-tests.log`
- `test_reports/phase-c1-commerce-foundation-20261008/live-results.json`
- `test_reports/phase-c1-commerce-foundation-20261008/mongo-recovery.json`
- `test_reports/phase-c1-commerce-foundation-20261008/runtime.log`
- `tools/migrate_c1_products.py`
- `tools/validate_c1_live.py`

## Commits

```text
28edd10 feat: add canonical commerce snapshots and fulfillment router
734497d feat: route V2 checkout through durable fulfillment adapters
b88595b test: verify C1 idempotency, rollback and tenant isolation
5ae4986 test: add isolated real Mongo acceptance and C1 migration CLI
```

The final documentation/evidence commit follows these implementation commits and is recorded in the final Git evidence file.

## Deferred phases

- C2 Physical Commerce MVP — variants/SKU, physical stock ledger and physical checkout UI.
- P1 Payment Core — new provider abstractions/integrations.
- P2 Settlement IDSE.
- P3 Tenant Own Gateway.
- S1 Shipping — addresses, rates, couriers and packing/shipping states.
- R1 Returns & Refunds.
- B1 Branding & White Label.

Subscription recurring billing, a digital-manual UI, external-transport crash reconciliation and production deployment were not implemented.
