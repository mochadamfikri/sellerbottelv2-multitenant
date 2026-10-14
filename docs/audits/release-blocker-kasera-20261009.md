# Release blocker sprint — Kasera V1

**RELEASE BLOCKER SPRINT RESULT: PASS**

**V1 PRODUCTION CANDIDATE: READY FOR PRODUCTION CANDIDATE — V1 PROFILE**

Date: 2026-10-09. Development workspace `/home/sellerbottelv2`, VPS `16.78.106.9`. Production is a different machine and was not accessed or changed. No live charge, settlement transfer, payout, refund, Telegram message or email was sent. All provider operations used the Kasera test environment.

Baseline: `1012d6323cac96e1dd04729a6eb791e295978114`. Branch: `feature/v1-kasera-release-blockers`. Implementation commit: `4ee7798` (`feat(payments): verify Kasera webhooks and add buyer fees with IDSE tiers`). Final report commit and clean git state are recorded in `test_reports/release-blocker-kasera-20261009/git-final.json` after committing this audit.

Source architecture and prior evidence: [V3 master](../architecture/sellerbottel-v3-master.md), [C1](phase-c1-commerce-foundation-20261008.md), [C2](phase-c2-physical-commerce-20261008.md), [Phase 3](phase-3-payment-shipping-post-purchase-20261008.md), [Phase 4](phase-4-final-hardening-20261008.md), [candidate checklist](../ops/PRODUCTION_CANDIDATE_CHECKLIST.md).

## Final owner-approved fee policy

The owner clarified that SellerBottel fees apply only when tenants use the IDSE payment gateway. The owner selected **B**: buyers pay Kasera costs; the SellerBottel fee is deducted from the IDSE tenant's proceeds. Self-gateway tenants pay no SellerBottel fee.

- Default SellerBottel fee: Rp250.
- Platform Control → **Fee gateway IDSE** lets the platform owner change the default and add up to 20 amount ranges. Tenant owners cannot change the platform policy.
- Ranges use product value after discounts plus manual shipping, before Kasera fees. Both endpoints are inclusive. An empty upper endpoint means unbounded. Overlapping/reversed ranges, fractional/negative fees and invalid types are rejected.
- Amounts outside configured ranges use the default. For example, Rp10,000–20,000 → Rp250; Rp20,001–50,000 → Rp500. These are configurable examples, not globally activated defaults. The isolated test fixture was restored to flat Rp250 with no tiers after verification.
- The selected fee and range are frozen on each payment at checkout. Changes affect new checkouts, including when an older pending payment succeeds after a policy update.
- Buyer checkout displays separate Kasera percentage/fixed components and the total before payment. The server requires the displayed total and rejects stale totals before reserving stock or creating a provider payment.

Kasera's [fee documentation](https://pay.kasera.id/en/docs/fees) specifies QRIS percentage rounding upward to whole rupiah and a fixed component. For cart value `B`, the implementation computes `G = ceil((B + 250) × 10000 / 9930)`, then verifies `G - ceil(G × 70 / 10000) - 250 = B`. The documented [transaction API](https://pay.kasera.id/en/docs/api/transactions/create) receives this explicit gross amount; no undocumented fee-bearer parameter is sent. Returned provider fee and net must match the checkout quote. Unconfirmed or mismatched rules fail closed with `NEEDS PROVIDER FEE RULE CONFIRMATION`.

For a Rp100,000 cart, buyer total is Rp100,957, Kasera fee Rp957, and provider net Rp100,000. At the default IDSE fee, tenant settlement is Rp99,750. Self-gateway provider net remains Rp100,000, with no platform ledger credit or SellerBottel charge.

## Acceptance matrix

| Gate | Result |
|---|---|
| DNS pay.idsepos.my.id → 16.78.106.9 | PASS |
| HTTPS certificate | PASS; TLS verified, certificate expires 2027-01-07 |
| Reverse proxy | PASS; existing active sites preserved |
| Kasera webhook endpoint | PASS |
| Kasera webhook contract | VERIFIED |
| Signature verification | PASS |
| Genuine Kasera callback | VERIFIED; both payment modes, including after backend restart |
| Kasera status mapping | PASS |
| Amount/reference verification | PASS |
| Tenant payment route resolution | PASS; direct indexed route lookup |
| Webhook idempotency | PASS; first, repeated and concurrent delivery |
| Kasera percentage 0.7% | PASS; upward rounding confirmed |
| Kasera fixed Rp250 | PASS; authoritative fee/net confirmed |
| SellerBottel default Rp250 / configurable tiers | PASS |
| Settlement fee separation | PASS; five immutable components |
| Tenant isolation | PASS |
| Manual shipping | PASS |
| Midtrans | DEFERRED — NOT REQUIRED FOR V1 |
| Stripe | DEFERRED — NOT REQUIRED FOR V1 |
| Biteship / integrated shipping | DEFERRED — NOT REQUIRED FOR V1 |
| Backend regression | PASS; 908 passed, zero skipped/failures |
| Frontend tests/build | PASS; 21 tests in 11 suites; CI build passed |
| Secret scan | PASS; no actual secret or provider-token matches |
| Production untouched | PASS |
| V1 Production Candidate | READY — candidate review only; no production deployment |

## DNS, HTTPS and running configuration

`getent hosts` and `dig +short` verified the expected IPv4 before proxy edits. Final [DNS/TLS/proxy evidence](../../test_reports/release-blocker-kasera-20261009/https-proxy.json) records the hostname, certificate verification, health HTTP 200 and preserved routes.

The actual systemd Caddy configuration path is `/etc/caddy/Caddyfile`. Its pre-existing disk contents failed validation because obsolete `on_demand_tls interval/burst` directives were unsupported. The running admin configuration was snapshotted privately. Removing those unused disk directives produced JSON **exactly equal to the running configuration** before adding the new site. Existing hosts, upstreams and on-demand TLS permission endpoint were preserved. The invalid original disk file was retained as `/etc/caddy/Caddyfile.before-kasera-20261009` for forensics; it is not a reloadable rollback configuration.

The added site exposes only:

- `GET https://pay.idsepos.my.id/health`
- `POST https://pay.idsepos.my.id/api/payments/webhooks/kasera`

Other paths return 404; the proxy limits webhook bodies to 64 KB. Both configuration validation before reload and [final validation of the actual path](../../test_reports/release-blocker-kasera-20261009/caddy-final-validation.log) passed. Caddy was reloaded without stopping it. No unrelated DNS or site routing was changed.

The isolated development backend is `sellerbottel-kasera-sandbox.service`, listening on loopback `127.0.0.1:8007`. It shares the canonical application webhook implementation, has no admin/docs endpoints, and runs trusted receipt repair only. Existing backend port 8002 and unrelated application services were left intact. The development unit uses the audit virtualenv under `/tmp`; it is not a production deployment unit or boot-enable operation. Route/receipt records and encryption keys survive its tested process restart.

## Callback contract and security

The [official webhook contract](https://pay.kasera.id/en/docs/api/webhook) uses `Kasera-Signature-V1` with timestamp `t` and one or more `v1` signatures. Verification uses constant-time HMAC-SHA256 comparison of `timestamp + '.' + raw body`, within ±300 seconds. Rotation may supply multiple signatures. Test events require `livemode=false`.

Accepted type/status pairs are `payment.paid/succeeded`, `payment.expired/expired`, and `payment.failed/failed`; internal paid status is `paid`. Unknown or inconsistent pairs are rejected. Delivery is at least once; duplicates reuse the provider event ID. Late paid events after locally released terminal orders enter operator review rather than silently consuming released stock.

The public handler checks body size and requires the signature header. Untrusted references are bounded strings, never query operators. Routing reads the platform payment route and validates registry tenant/database binding, payment/order, provider reference, provider payment ID, integer amount and IDR currency before mutation. It does not scan tenant databases. Historical credential versions remain bound to existing payments; revocation blocks new credential use without losing legitimate historical callbacks.

[Security and replay results](../../test_reports/release-blocker-kasera-20261009/security-restart.json) cover missing/invalid signatures, stale/future timestamps, wrong amount/currency, unknown/foreign references, query operators, foreign provider payment IDs, wrong tenant database binding, revoked credentials, hidden public admin/docs paths, and 12 concurrent duplicate requests. Those adversarial requests are locally signed synthetic tests and are explicitly **not** counted as genuine provider delivery.

## Genuine callback and durable effects

`tools/validate_release_kasera.py` creates a real Kasera test transaction and invokes the provider's [documented test simulation](https://pay.kasera.id/en/docs/api/test-mode). The script never calls `apply_event`, `repair_paid` or a local fabricated callback. It waits for the public HTTPS service to apply a signed provider receipt. Genuine callbacks were observed before and after isolated backend restart.

Final policy evidence:

| Case | Cart value | Buyer pays | Kasera fee | SellerBottel | Tenant net |
|---|---:|---:|---:|---:|---:|
| IDSE default | 15,001 | 15,359 | 358 | 250 | 14,751 |
| Self gateway | 15,001 | 15,359 | 358 | 0 | 15,001 |
| IDSE tier example | 25,001 | 25,430 | 429 | 500 | 24,501 |
| Self gateway with same cart | 25,001 | 25,430 | 429 | 0 | 25,001 |

[Default/buyer-fee evidence](../../test_reports/release-blocker-kasera-20261009/genuine-callback-buyer-fees.json), [tier evidence](../../test_reports/release-blocker-kasera-20261009/genuine-callback-tier-fees.json), and [Mongo effects](../../test_reports/release-blocker-kasera-20261009/mongo-effects.json) include route/provider/event identities, receipt timestamps and exact financial components. Each final test payment has one applied receipt, one stock SALE and one physical fulfillment. IDSE payments have exactly five ledger components; self-gateway payments have zero platform credit. Restart/replay preserved the route unique index and all financial, stock and fulfillment state.

The five components are `PAYMENT_GROSS`, `KASERA_PERCENT_FEE`, `KASERA_FIXED_FEE`, `SELLERBOTTEL_PLATFORM_FEE`, and `NET_SETTLEMENT`. The final component carries the pending-balance delta; the other four are separate immutable accounting facts. Old journal formats and archive behavior remain readable.

Earlier `genuine-callback.json`, `genuine-callback-after-restart.json`, and `genuine-callback-final.json` preserve intermediate sprint verification before the later buyer-fee/tier instructions. They are not the final pricing acceptance evidence. No historical fixture snapshots were rewritten to make earlier results appear to use the new policy.

## Regression, configuration and remaining work

[Backend log](../../test_reports/release-blocker-kasera-20261009/backend-regression.log) and [JUnit](../../test_reports/release-blocker-kasera-20261009/backend-regression.xml): **908 passed, zero skipped**, including prior C1/C2/Phase3/Phase4 tests. No old test was removed or skipped; an old Kasera fixture gained the now-required documented event type. The focused suite passed 70 tests; the full final run also covers policy updates between checkout and payment.

[Frontend tests](../../test_reports/release-blocker-kasera-20261009/frontend-tests.log): **21 passed / 11 suites**. [CI build](../../test_reports/release-blocker-kasera-20261009/frontend-build.log), `python -m compileall -q backend`, and `git diff --check`: PASS. Tests cover fee-tier editing, stale buyer quotes, provider visibility, owner authorization, tier boundaries, credential protection and immutable fee selection. Existing dependency deprecation warnings remain visible in the logs.

Set `COMMERCE_LAUNCH_PROFILE=v1_kasera` on the tenant application when adopting this candidate. Under this profile, checkout offers Kasera QRIS, enforces manual shipping, blocks tenant legacy merchant checkout and rejects deferred providers. Owner-private GoPay remains separate. QRIS is the method covered by the approved percentage model; Kasera VA has a different tariff and is not presented as covered by this fee model. The isolated webhook runtime already uses this profile; this sprint did not deploy/restart the full tenant UI application or production services.

The supplied signing secret and stable development API/encryption configuration are private, mode 0600 and git-ignored. [Secret scan](../../test_reports/release-blocker-kasera-20261009/secret-scan.json) checks actual private values and provider-token patterns across source and evidence without exposing values. Neither private file is in source, frontend or reports.

**P0 remaining: 0. P1 remaining: 0 within the approved V1 candidate gates.**

**P2 remaining: 1 inherited limitation:** tenant ledger browsing shows the bounded hot tail; archived history remains retained and auditable. A fuller historical browsing UI is not part of this sprint.

**External V1 test blockers: none.** The previous unavailable Midtrans credential and rejected Biteship credential remain documented in Phase 4 and are deferred, not silently converted into successful provider tests. Operational production activation still requires the separate checklist: protected production secrets, approved live provider/commercial setup and tenant disbursement procedure, correct runtime flags and production infrastructure review. No live adapter, settlement transfer or payout was enabled by this work.

Stop after this sprint. No automatic production deployment.
