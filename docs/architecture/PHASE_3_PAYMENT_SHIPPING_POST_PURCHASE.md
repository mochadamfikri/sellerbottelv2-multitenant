# Phase 3 — Payment, Shipping, Post-Purchase

Branch: `feature/v3-phase-3-payment-shipping-post-purchase`, based on C2 `93118b13ec8d0cbbb41a72ee5fbd6026c804a820`. This implements the four mandatory checkpoints in the [V3 master](sellerbottel-v3-master.md), preserving [C1](PHASE_C1_COMMERCE_FOUNDATION.md) and [C2](PHASE_C2_PHYSICAL_COMMERCE_MVP.md).

## 3A — Payment core

`backend/payments` owns canonical order payments. One mixed cart creates one order/payment, with independent C1 fulfillment records. Legacy wallet and personal GoPay QRIS transports remain compatible; the new settlement gateway never inherits their credentials.

Tenant payment configuration selects `platform_settlement` (Settlement IDSE) or `self_gateway` (Gateway Saya Sendiri). Provider and method are separate: `kasera` / `midtrans` versus `qris`, `va_bca`, `va_bni`. Checkout uses `gateway:<method>` to distinguish this transport from legacy QRIS. Canonical financial amounts, fee calculations, ledger deltas, refund aggregates and payout amounts use integer rupiah. Existing pricing snapshots are validated at the boundary: fractional, nonfinite and boolean monetary values are rejected, rather than silently rounded. Gateway total is merchandise subtotal minus discount plus immutable shipping plus tax/payment fee (currently zero).

Payment fields include tenant/order, mode/provider/method/environment, credential version, amount/currency, status, external ID/reference, expiry, paid/cancel timestamps, refunded amount, reserved refund amount, refund intents, timestamps and reconciliation state. States are `created`, `pending`, `paid`, `expired`, `failed`, `cancelled`, `partially_refunded`, `refunded`, with explicit transitions in `payments/models.py`.

Preparation writes a stable order identity derived from tenant database, customer and idempotency key before reserving stock. Physical reservations, digital inventory and legacy product stock have compensating release paths. The platform `payment_routes` document is committed before the first provider call. Its unique provider/reference and provider/external-ID indexes resolve webhooks without scanning tenant databases. Business records remain in the routed tenant database. Provider response metadata is retained in the route to repair a failed local create update.

Webhook processing validates registry/database binding, credential version, signature, external ID/reference, exact amount and currency. An immutable semantic receipt is stored in platform `payment_events` before effects. Durable event identity, a five-minute processing lease and payment CAS prevent concurrent delivery of the same event from duplicating work. Receipt retries and operator repair reuse stock, fulfillment and settlement operation identities. A failed or running C1 delivery claim is never blindly replayed. Different or older events cannot regress a paid/refunded payment.

A signed early paid callback can bind the external ID when the create response was lost. Settlement requires a verified fee before credit. A paid event after local cancellation/expiry/failure records `external_paid` and `late_paid_requires_refund_or_stock_review`; it does not resell released stock. Unknown create/cancel/refund/shipment outcomes remain visible for reconciliation and are never automatically resubmitted.

## Credentials and provider capabilities

Gateway secrets are Fernet encrypted using the existing server encryption facility. The encrypted envelope binds database, tenant, provider, environment and immutable credential version. Copying ciphertext to another tenant fails. Replacement creates a new version; revocation prevents new payment resolution. Historical events/refunds reference the purchase-time version, which remains encrypted for reconciliation. Normal reads expose only masked field names and capability snapshots, never plaintext secrets.

Provider-specific fields:

| Provider | Fields |
|---|---|
| Kasera | `api_key`, `webhook_secret` |
| Midtrans | `server_key`, `client_key`, optional `merchant_id`, mock-only `webhook_secret` |

Test Connection authenticates sandbox adapters where enabled. Kasera discovers methods and amount limits from its authenticated method catalog. Midtrans authenticates a status probe and reports deterministic configured Core QRIS capabilities; merchant activation remains necessary. No account-discovery API is claimed where unavailable. Capability snapshots include environment, coverage, methods, refund/cancel/payout support, discovery explanation and verification time.

Sandbox execution is opt-in through `PHASE3_SANDBOX_ENABLED=true`. Kasera requires a `kp_test_` key; Midtrans requires `SB-Mid-server-`. Registry rejects live environments. Official HTTP adapters implement only documented sandbox methods. Kasera has no invented refund/cancel/third-party-payout endpoint, so these capabilities are false and refunds become `manual_refund_required`. Midtrans Core QRIS refund/cancel adapters exist; merchant refund activation and provider windows still apply. Sandbox credentials and real sandbox transports were **not available or exercised** in acceptance.

`PHASE3_MOCK_ENABLED=true` enables explicit deterministic contract simulators for Kasera and Midtrans. Mock keys/signing secrets start with `mock_`; Test Connection returns **MOCKED**, never a real merchant authentication claim. Mock confirmations use HMAC-SHA256 on raw body. Kasera sandbox uses its timestamped HMAC header and rejects timestamps outside five minutes or live payloads. Midtrans verifies SHA512 of order ID, status code, gross amount and server key.

Official sources consulted: [Kasera API](https://pay.kasera.id/en/docs/api), [method discovery](https://pay.kasera.id/en/docs/api/payment-methods/list), [create](https://pay.kasera.id/en/docs/api/transactions/create), [retrieve](https://pay.kasera.id/en/docs/api/transactions/retrieve), [webhooks](https://pay.kasera.id/en/docs/api/webhook), [Midtrans QRIS](https://docs.midtrans.com/reference/qris), [status](https://docs.midtrans.com/reference/get-transaction-status), [refund](https://docs.midtrans.com/reference/refund-transaction), [notification verification](https://docs.midtrans.com/docs/https-notification-webhooks). These are technical references, not a claim of production merchant approval. Kasera's documented payout restrictions also require separate assessment before live platform settlement.

## 3B — Settlement IDSE and tenant gateway

Platform credentials live only in the platform database under tenant binding `platform-idse`, with verified Kasera configuration in `platform_payment_settings`. Tenants cannot write these credentials through owner settings. Self-gateway uses the tenant's exact encrypted credential version with no platform fallback and creates no settlement credit/reversal.

The tenant settlement account contains an append-only authoritative journal and CAS version. Every event bundle and version change is one Mongo document operation, compatible with standalone Mongo. `settlement_entries` is an immutable `$setOnInsert` projection, repaired from the journal. Payout authorization always derives balances from authoritative entries, never from a stale cached balance.

| Entry | Accounting semantics |
|---|---|
| PAYMENT_GROSS | Gross payment fact; no bucket delta |
| GATEWAY_FEE / PLATFORM_FEE | Fee facts; no independent bucket delta |
| NET_PENDING | Pending += gross − both fees |
| NET_CLEARING | Transfer this payment's remaining pending to clearing |
| NET_AVAILABLE | Transfer this payment's remaining clearing to available |
| PAYOUT_RESERVE | Available −= amount; reserved += amount |
| PAYOUT_STATE | Immutable lifecycle fact; rejection/failure/cancel releases reservation |
| PAYOUT | Reserved −= amount; paid_out += amount |
| REFUND_REVERSAL | Remove this payment's remaining pending/clearing, then pooled available; remainder increases liability |

Pending/clearing/available timings are configurable and checked before advancement. No production T+N is assumed. Fee facts and net transfers are not double-counted. All operation references are deterministic and conflicting reuse is rejected. Liability reduces funds available for new payout requests. Refund after funds are reserved/paid out produces explicit liability.

Payout bank details are encrypted, tenant/version bound, with masked account number on normal reads. A request snapshots the encrypted bank version and atomically reserves funds in the journal. States are requested → reviewing → processing → paid, with rejected/cancelled/failed alternatives and idempotent reserve/release. This phase exposes **mock verification and simulated payouts only**; simulated payout cannot consume sandbox/nonmock credits. No external bank payout API is called.

## 3C — Shipping

`backend/shipping` defines independent `get_rates`, `create_shipment`, `cancel_shipment`, `track_shipment` interfaces. Modes are `manual_shipping`, `integrated_shipping`, `pickup_only`. Existing C2 flat manual fees/workflow remain unchanged. Gateway, wallet and legacy store QRIS checkouts validate selected integrated quotes; pickup has zero shipping fee and no provider requirement. Paid pickup can move ready-to-ship → delivered without courier/resi, recording a pickup receipt.

The implemented integrated provider is **Mock Courier / MOCKED**, explicitly enabled by the dev mock flag. Rates use origin, validated address, physical parcel quantity, integer grams and variant dimensions. Persisted quotes bind tenant, customer, credential version and cart/address fingerprint, expire after ten minutes, and snapshot service, fee, origin/address and parcels. Old order totals never recalculate from a later rate/configuration. Private encrypted shipping credential snapshots live outside customer-visible orders.

A paid, initialized, ready-to-ship physical fulfillment creates one durable shipment intent. Unknown create outcomes block another provider call. A platform shipping route retains the provider result before local projection, permitting safe repair if the local update fails. Signed tracking events resolve the registered tenant directly, are journaled by event ID and cannot regress delivered to shipped. C2 fulfillment/shipment projections remain repairable. Copying another tenant's shipping secret fails envelope binding; foreign shipments/rates cannot be accessed through another tenant context.

## 3D — Returns, refunds and reconciliation

Physical returns live in `backend/commerce/aftercare`, separate from the existing `post_purchase.py` follow-up feature. Lifecycle: return_requested → reviewing → approved → return_shipped → received → inspected → resolved, with rejected/cancelled alternatives. An owner may acknowledge direct receipt after approval. Customer eligibility comes from delivered physical fulfillments and remaining purchased quantities; legacy C2 orders are eligible in their own tenant database.

An order-level quantity claim CAS prevents concurrent returns exceeding purchased quantity. Return records project idempotently from these claims. Rejected/cancelled claims release eligibility. Inspection sets a durable compensation flag before applying stock. Partial returns validate the original SALE and cumulative returned quantity. Resellable goods create RETURN. Damaged goods append RETURN plus DAMAGE in the **same variant CAS**, so damaged stock never briefly becomes sellable. Historical SALE is never rewritten. Repeated inspection or projection failure repairs the same movement identity.

Refund is a separate financial lifecycle and does not rewrite order/fulfillment/return status. Canonical gateway payments support full/partial refunds. Atomic refund reservations enforce `succeeded + reserved + requested <= paid amount`. Each request has a durable platform operation before any external call. A confirmed provider result is persisted independently before changing local totals or settlement. Local failures repair from that receipt; external-unknown actions retain their reservation and are not retried. Signed mock refund callbacks can resolve unknown results without issuing another refund. Unsupported API refunds remain `manual_refund_required`, with no fake success or settlement reversal. Self-gateway refunds use the original tenant provider version and create zero IDSE credit/reversal. Legacy wallet/QRIS transports retain their pre-existing financial semantics; canonical provider refund endpoints do not invent a gateway payment for them.

Owner APIs under `/api/public/tenant/full/commerce` provide settings/connection, transactions, settlement stages, masked payout bank, simulated payouts, shipping settings/shipments, returns, refunds and reconciliation. Customer APIs are aliased for registered hosts and `/api/store/t/{slug}` and include gateway methods/rates, owned payment status, return eligibility/request/history. Tenant cookie ownership is checked before access. Raw gateway/shipping/bank secrets are never returned.

Reconciliation reports unknown create/cancel/refund/shipment actions, accepted receipts, stale preparation and missing projections. Repair replays trusted local receipts, restores shipping/provider-response projections, projects return quantity claims/stock compensation and settlement entries, and releases failed preparation only when no external route exists. It never blindly retries an external create/refund/payout. `tools/reconcile_phase3.py` provides dev-only report/repair with explicit localhost:27019 and dedicated Phase 3 database guards; it never loads `.env`.

A separate payment maintenance worker repairs accepted/expired-lease receipts and polls **read-only** provider status when a canonical payment expires. Confirmed expiry releases reservations once, including disabled tenants without bots; inactive paid tenants wait for reactivation. It never retries financial writes and does not alter C2's provider-free expiry worker.

## Validation, limits and deferred scope

See the [audit report](../audits/phase-3-payment-shipping-post-purchase-20261008.md) and committed evidence. Tests distinguish offline Mongo mocks, real dedicated Mongo persistence, real Chromium UI, mocked providers and unexercised sandbox HTTP adapters.

Carry-forward P2: scalable physical journal archival beyond 3,000 events (also needed for growing settlement/payment journals; settlement currently guards at 10,000 events), and persistent Docker Mongo nofile configuration. These remain explicit capacity/operations limits. Do not bypass a guard by deleting immutable journal history.

Deferred: DOKU, GoPay Merchant tenant adapter, OttoPay, Stripe, advanced warehouse, replacement returns, advanced fraud tooling, and production settlement/live payout. Real sandbox account certification, merchant capability activation, live commercial/payment-provider approval and live bank verification remain prerequisites outside this mock development acceptance. Stop after Phase 3.
