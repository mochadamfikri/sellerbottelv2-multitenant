# Phase 3 — Payment + Shipping + Post-Purchase audit

**Result: PASS — development/mock scope**, 2026-10-08.

Starting SHA: `93118b13ec8d0cbbb41a72ee5fbd6026c804a820`  
Branch: `feature/v3-phase-3-payment-shipping-post-purchase`  
Final SHA and checkpoint commits are recorded after the documentation commit in the local evidence `git-final.json`, avoiding a self-referential commit hash.

Architecture: [Phase 3](../architecture/PHASE_3_PAYMENT_SHIPPING_POST_PURCHASE.md). Baseline: [C1](phase-c1-commerce-foundation-20261008.md), [C2](phase-c2-physical-commerce-20261008.md), and [V3 master](../architecture/sellerbottel-v3-master.md).

## Delivered checkpoints

**3A Payment Core:** one order-level payment for mixed digital/service/physical carts, separate provider/method, canonical transitions, registered tenant route lookup and unique indexes. Scoped, signed webhooks use durable receipts and processing leases. Duplicate callbacks cannot repeat financial credit or fulfillment. Unknown external outcomes retain reservations and require confirmation instead of blind retries. A read-only expiry worker releases confirmed expired orders, including disabled tenants.

**3B Settlement and tenant gateway:** encrypted, versioned credentials with tenant/database/provider/environment binding, masked settings, explicit Test Connection and capabilities. Settlement IDSE resolves platform Kasera; Gateway Saya Sendiri resolves tenant Kasera or Midtrans without fallback or platform settlement credit. Immutable settlement journal covers pending, clearing, available, fees, refund reversal and post-payout liability. Atomic payout reservations and simulated states never send a real payout. Bank data is encrypted and masked.

**3C Shipping:** manual shipping remains compatible; integrated shipping uses a provider interface, scoped encrypted credentials, server-calculated rates and immutable expiring address/cart/customer snapshots. Shipment intents and signed tracking are idempotent and repairable. Pickup has zero delivery fee and permits direct customer collection without courier/resi. Owners can configure an origin and create shipments; customers manually enter alamat, kota/kabupaten, provinsi and kode pos.

**3D Returns/refunds/reconciliation:** delivered physical lines support cumulative partial quantity claims, review, receipt, inspection, restock/damage and resolution. Compensating stock entries preserve original SALE history; damaged returns do not increase sellable stock. Separate financial refunds reserve amounts atomically, cap cumulative refunds at paid amount, support partial/full outcomes and reverse settlement once. Confirmed provider receipts recover interrupted local effects; ambiguous outcomes are displayed for review. Reconciliation API and restricted development CLI repair durable receipts/projections without resending uncertain financial operations.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Backend full regression | 815 passed; no skipped tests | [log](../../test_reports/phase-3-payment-shipping-post-purchase-20261008/backend-regression.log), [JUnit](../../test_reports/phase-3-payment-shipping-post-purchase-20261008/backend-regression.xml) |
| Focused Phase 3 | 39 passed | [log](../../test_reports/phase-3-payment-shipping-post-purchase-20261008/focused.log), [JUnit](../../test_reports/phase-3-payment-shipping-post-purchase-20261008/focused.xml) |
| Frontend unit | 8 suites / 16 tests passed | [log](../../test_reports/phase-3-payment-shipping-post-purchase-20261008/frontend-tests.log) |
| Frontend CI build | PASS | [log](../../test_reports/phase-3-payment-shipping-post-purchase-20261008/frontend-build.log) |
| Real Mongo / Chromium | 102 passed, 0 failed | [results](../../test_reports/phase-3-payment-shipping-post-purchase-20261008/live-results.json), [harness](../../tools/validate_phase3_live.py) |
| Compile and whitespace | PASS | compileall and git diff --check |

The full suite retains all 776 C2 backend tests. Existing dependency deprecation warnings remain. Tests use the audit venv and the compiled frontend. Financial/provider operations are explicitly MOCKED; Mongo and Chromium are real. Sandbox adapter implementations are not merchant-certified or validated with actual sandbox credentials.

## Acceptance matrix

| Gate | Result |
|---|---|
| Backend full regression | PASS |
| Frontend unit | PASS |
| Frontend CI build | PASS |
| 3A Payment Core | PASS |
| Provider registry | PASS |
| Payment route index | PASS |
| Webhook verification | PASS |
| Payment idempotency | PASS |
| Credential encryption | PASS |
| Test Connection/capabilities | PASS |
| 3B Settlement IDSE | PASS |
| Settlement ledger | PASS |
| Pending/clearing/available | PASS |
| Payout reservation/state | PASS |
| Tenant Kasera | PASS |
| Tenant Midtrans | PASS |
| Self-gateway no-settlement invariant | PASS |
| 3C Shipping | PASS |
| Manual shipping regression | PASS |
| Integrated shipping adapter | PASS |
| Rate snapshot | PASS |
| Shipment/tracking idempotency | PASS |
| 3D Returns | PASS |
| Stock compensation | PASS |
| Full refund | PASS |
| Partial refund | PASS |
| Settlement refund reversal | PASS |
| Self-gateway refund | PASS |
| Reconciliation | PASS |
| Cross-tenant isolation | PASS |
| Real Mongo | PASS |
| Browser acceptance | PASS |
| Secret-safe logs | PASS |
| Production untouched | PASS |

Provider-related PASS entries mean the supported development/mock contracts and invariants passed. They do not imply real merchant onboarding, real shipping-provider integration certification, live settlement or live payout approval.

## Evidence and failure coverage

The retained live run uses isolated platform `sellerbottel_phase3_dev_22c047c1`, tenants `sellerbottel_tenant_phase3_a_22c047c1` and `sellerbottel_tenant_phase3_b_22c047c1`, dedicated development Mongo at localhost:27019, real HTTP and compiled React/Chromium. The harness generates ephemeral keys and synthetic customer/owner records; it does not load production credentials. Existing retained databases are not dropped.

Real-Mongo acceptance includes duplicate signed payment webhooks, concurrent payout reservations, tenant-owned gateways without settlement, refund liability after simulated payout, shipping rate snapshots and duplicate tracking, damaged return compensation, partial refund, cross-tenant cookie/credential rejection, and repair after injected local receipt-processing failure. Browser checks cover owner settings, payment/settlement panels, shipping workflow, customer manual address/rate selection/payment, tracking, return submission, owner inspection/restock and partial refund. Five screenshots are retained in the evidence directory.

Unit fault injection additionally covers ambiguous create/refund/shipment outcomes, projection loss after authoritative stock journal commit, webhook timestamp/signature tampering, exact integer money validation, partial/full refund races, stale credential binding and revoked versions, settlement timing/fees, mixed fulfillment, return quantity limits and confirmed expiry. Unknown financial writes are not automatically retried. Unsupported Kasera sandbox refunds are manual-required, never marked successful.

## Adapter scope

Kasera platform, Kasera tenant, Midtrans tenant and shipping acceptance use explicit mock adapters with MOCKED labels. Kasera sandbox code follows official transaction, discovery and timestamped webhook contracts; refund/cancel/payout remain unsupported unless documented. Midtrans sandbox Core QRIS code uses server-key signing, status/cancel/refund interfaces; merchant activation must be validated separately. No actual external sandbox calls were required or performed for acceptance. Production `.env`, DNS/Caddy and production databases remain untouched. No real charge, payout, SMTP or Telegram message was sent.

## Remaining and deferred

**P0: 0. P1: 0 within the approved development/mock scope.**

P2 follow-ups: existing C2 stock journal archival before the 3,000-entry bound; settlement journal archival before its 10,000-entry bound; persistent Docker Mongo nofile configuration remains an operations follow-up. Bounds fail closed rather than silently discarding financial/stock history. Real provider sandbox credential testing and merchant/commercial approval are required before enabling corresponding production adapters. These limitations are visible in capabilities and the architecture.

Deferred: DOKU, GoPay Merchant tenant adapter, OttoPay, Stripe, advanced warehouse, advanced fraud tooling, production settlement/live payout unless separately approved. Existing wallet/legacy QRIS semantics remain compatible; canonical gateway financial refunds do not invent legacy payment records or credit a different wallet. Work stops after Phase 3.
