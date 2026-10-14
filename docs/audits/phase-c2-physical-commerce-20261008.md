# Phase C2 — Physical Commerce MVP audit

**Result: PASS** — 2026-10-08, development machine `/home/sellerbottelv2`.

Starting SHA: `88b3ab281b9bd79322ea66e05ce18233f48dda5c`  
Branch: `feature/v3-c2-physical-commerce`  
Validated application/test revision: `a40ecef`; initial tests/evidence commit: `1e48253`. The final documentation commit SHA is recorded after commit in [git-final.json](../../test_reports/phase-c2-physical-commerce-20261008/git-final.json), avoiding a self-referential report commit.

Source of truth: [V3 master](../architecture/sellerbottel-v3-master.md), [C1 architecture](../architecture/PHASE_C1_COMMERCE_FOUNDATION.md), and [C1 PASS audit](phase-c1-commerce-foundation-20261008.md). Implementation is described in [C2 architecture](../architecture/PHASE_C2_PHYSICAL_COMMERCE_MVP.md).

## Outcome

Tenant owners can author physical products, add generic variant options and stable SKU, receive/adjust/damage stock, inspect ledger/counters, configure flat shipping, and operate packing through delivered with a manual carrier/resi. Customers select a variant, retain it in a mixed cart, manually enter or save an address, see shipping before payment, pay once, and inspect tracking. Kota/kabupaten is a manual text field; no address/courier API is required.

Physical quantity stock is distinct from encrypted digital inventory. A single-document atomic stock journal with an immutable, repairable ledger projection prevents oversell on standalone Mongo. Paid order initialization, shipment projection and interrupted expiry/cancellation compensation have explicit idempotent recovery paths. Digital lines in mixed orders remain accessible when their delivery has completed.

Production, original `.env`, retained audit tenants and real SMTP/Telegram/payment providers were not modified or invoked. Physical Telegram checkout is blocked before charging. Existing digital/service bot flows and all 729 baseline backend tests remain green.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Backend compileall | PASS | `python -m compileall -q .`, exit 0 |
| Backend full regression | PASS — 776 tests; 0 skipped/failures/errors | [JUnit](../../test_reports/phase-c2-physical-commerce-20261008/backend.xml), [log](../../test_reports/phase-c2-physical-commerce-20261008/backend.log) |
| Focused C2 | PASS — 47 tests (43 domain, 4 HTTP) | [log](../../test_reports/phase-c2-physical-commerce-20261008/focused-c2.log) |
| Existing focused C1 | PASS — all 47 included unchanged in full regression | Full JUnit and C1 tests |
| Frontend unit | PASS — 7 suites / 14 tests | [log](../../test_reports/phase-c2-physical-commerce-20261008/frontend-tests.log) |
| Frontend CI build | PASS | [log](../../test_reports/phase-c2-physical-commerce-20261008/frontend-build.log) |
| Real Mongo and browser acceptance | PASS — 58 checks | [results](../../test_reports/phase-c2-physical-commerce-20261008/live-results.json), [harness](../../tools/validate_c2_live.py) |
| Repository whitespace | PASS | `git diff --check`, exit 0 |

Validation uses the installed audit venv, with backend tests run from `backend/`. Frontend commands are `CI=true npm test -- --watchAll=false --runInBand` and `CI=true npm run build`. Deprecation warnings from existing FastAPI/Starlette/openpyxl dependencies remain; no old test was skipped or deleted.

## Acceptance matrix

| Gate | Result |
|---|---|
| Backend full regression | PASS |
| Frontend unit | PASS |
| Frontend CI build | PASS |
| Physical product authoring | PASS |
| Variant model | PASS |
| SKU uniqueness | PASS |
| Physical stock ledger | PASS |
| Stock invariants | PASS |
| Stock reservation | PASS |
| Concurrency/oversell protection | PASS |
| Address snapshot | PASS |
| Manual shipping | PASS |
| Physical checkout | PASS |
| Mixed digital+physical order | PASS |
| Physical fulfillment states | PASS |
| Tracking number | PASS |
| Tenant Admin physical UI | PASS |
| Storefront physical UI | PASS |
| Tenant isolation | PASS |
| Real Mongo validation | PASS |
| Restart/index idempotency | PASS |
| Secret-safe logs | PASS |
| Shipping provider integration | DEFERRED |
| Payment Core P1 | DEFERRED |
| Settlement IDSE P2 | DEFERRED |
| Tenant gateways P3 | DEFERRED |
| Returns/refunds R1 | DEFERRED |
| Branding/white-label B1 | DEFERRED |

## Stock, idempotency and failure evidence

| Scenario | Verified outcome |
|---|---|
| SKU case collision | Same tenant rejects uppercase-equivalent SKU; separate tenant accepts it |
| Invalid/inactive/missing variant or missing address | Fails before charging; digital-only compatibility remains green |
| Stock counter and journal mutation | One Mongo CAS persists event/counters, enforcing nonnegative available/reserved/on-hand |
| Last-unit concurrent reservation | Real Mongo: 20 buyers, exactly one reservation winner |
| Last-unit concurrent wallet checkout | Real Mongo: two customers, one paid order, one unchanged wallet, no outstanding reservation |
| Repeated checkout/payment/state | One debit, one SALE, unchanged record identity; conflicting resi rejected |
| Ledger projection write fails | Journal remains committed; retry repairs one ledger event without applying stock twice |
| Reservation succeeds, purchase insertion fails | Injected insertion failure is asserted; physical reservation releases |
| Order already exists, reservation rejects | Persisted order ends failed; wallet unchanged and no physical reservation left |
| Balance fulfillment insertion fails | Existing rollback refunds wallet and releases physical stock |
| Payment succeeds, fulfillment insertion fails | Real Mongo preserves paid `delivery_failed` and reserved stock; explicit owner recovery consumes once and initializes records |
| Storefront tenant has no bot/payment monitor | Provider-free 30-second expiry worker scans its database; inactive tenants also release existing reservations, with no notification transport |
| Mongo outage during expiry release | Expired order retains `stock_release_pending`; subsequent pass releases once, including legacy quantity-stock compensation |
| Shipment projection fails after state mutation | Authoritative shipment snapshot survives; repeating state repairs projection; older shipped projection cannot regress delivered |
| Pre-shipment paid cancellation | Append-only RETURN compensates SALE exactly once |
| Product/variant edits | Purchased SKU/options/price/address snapshots remain stable |
| Mixed digital/service/physical | One wallet payment, three fulfillment records; global order waits for all, digital delivery remains independently available |
| Identical IDs across tenants | Same SKU/variant/customer/order/fulfillment IDs remain database scoped; foreign cookie rejected; stock/shipment mutation affects only caller's tenant |
| Unpaid/refunded physical shipment | State action rejected; no shipment transition occurs |
| Product discount plus coupon | Merchandise-only discount; shipping remains charged; quote/order formula reconciles |
| Physical photo upload | Owner HTTP route uses existing validated WEBP image infrastructure and tenant image read |

Append-only `stock_movements` is a projection of the authoritative embedded journal, not a separately committed transaction. Reads/retries repair projection failures. Outstanding digital failed/running/ambiguous C1 claims require operator reconciliation and cannot be replayed through the physical recovery action. Financial physical refunds remain deferred; shipment cancellation compensates stock only.

## Real development acceptance and browser

The final run uses platform `sellerbottel_c2_dev_fff99534` and tenant databases `sellerbottel_tenant_c2_a_fff99534` / `sellerbottel_tenant_c2_b_fff99534`, on dedicated Mongo `127.0.0.1:27019`. Fresh synthetic tenants were provisioned through the real owner API. Existing `sellerbottel_live_e2e_dev` tenant count was checked unchanged. Mongo/index/claim/order/stock operations are real. QRIS generation and notification transports are mocked where exercised.

The harness starts an isolated backend on 8004 and compiled frontend proxy on 3004; the proxy supplies the registered synthetic tenant hostname. Chromium performs owner login, physical product and generic option authoring, stock receipt, customer login/catalog/variant/cart, manual address and balance payment, packing/ready/shipped/delivered, and customer tracking inspection. Both temporary runtimes are stopped afterwards. A backend restart rechecks saved stock/shipment and repeated index initialization.

Browser evidence:

- [Tenant products, variant and stock](../../test_reports/phase-c2-physical-commerce-20261008/tenant-physical-products.png)
- [Customer manual address and checkout](../../test_reports/phase-c2-physical-commerce-20261008/storefront-physical-checkout.png)
- [Tenant shipment/resi actions](../../test_reports/phase-c2-physical-commerce-20261008/tenant-physical-tracking.png)
- [Customer carrier/resi](../../test_reports/phase-c2-physical-commerce-20261008/customer-physical-tracking.png)

Harness iterations corrected fixture expectations for secure cookies, catalog navigation, payment selection, and unique customer email indexes. The final [results JSON](../../test_reports/phase-c2-physical-commerce-20261008/live-results.json) contains 58 PASS and zero FAIL. The retained runtime log includes development iterations; the final harness log includes an expected synthetic fulfillment-insertion exception used to verify recovery. Generated passwords, JWT/encryption/webhook secrets and inventory payloads are absent from runtime logs.

## Remaining severity and boundaries

P0 remaining: **0**. P1 remaining: **0**.

P2 remaining: **2** follow-ups:

1. Add physical journal archival/scalable projection for high-volume variants. The MVP stops new admin operations/reservations at 3,000 journal events, leaving headroom for existing SALE/RELEASE/RETURN. History must not be erased to bypass the guard.
2. Persist an adequate Docker Mongo `nofile` limit. The dedicated audit process currently has sufficient limits; the harness fails before writes if a container restart restores the low inherited limit. This carries forward the C1 development infrastructure follow-up.

Deferred feature phases are separate from unresolved C2 severity: P1 Payment Core, P2 Settlement IDSE, P3 Tenant Own Gateway, S1 Shipping Provider Integration, R1 Returns & Refunds, and B1 Branding & White Label. No automatic work continues into those phases.

## Commits

- `2db4800` feat: add physical variants sku and atomic stock ledger
- `030d477` feat: add physical checkout addresses and shipment workflow
- `c194a24` feat: add tenant admin and storefront physical commerce ui
- `1e48253` test: add c2 physical regression and real mongo browser acceptance
- `a40ecef` fix: expire physical reservations for storefront-only tenants
- Final documentation commit: `docs: document phase c2 physical commerce acceptance`; SHA in the post-commit artifact above.
