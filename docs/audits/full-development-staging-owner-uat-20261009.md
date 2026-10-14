# Full development staging + owner UAT — 2026-10-09

**FULL DEVELOPMENT STAGING: PARTIAL. OWNER UAT: READY for the documented V1 flows.** Public full application and isolated services are running. Genuine Kasera test payments, SMTP tenant registration and commerce operations pass. Remaining limitations are listed explicitly; this is not certification that every requested feature or owner manual test has passed.

Start: [UAT_HANDOFF.md](../uat/UAT_HANDOFF.md). Owner checkboxes: [OWNER_UAT_CHECKLIST.md](../uat/OWNER_UAT_CHECKLIST.md).

## Domain patch and isolation

The owner's domain patch supersedes the earlier staging-domain proposal. No staging.idsepos.my.id host is created or relied upon.

| Purpose | Public URL |
|---|---|
| Platform landing / registration | https://idseconnect.my.id |
| Platform control | https://idseconnect.my.id/platform-control |
| Tenant login root | https://idsestock.my.id |
| Fashion panel / store | https://fashion-demo.idsestock.my.id / https://fashion-demo.idseconnect.my.id |
| Digital panel / store | https://digital-demo.idsestock.my.id / https://digital-demo.idseconnect.my.id |
| Existing payment callback | https://pay.idsepos.my.id/api/payments/webhooks/kasera |

Both authoritative nameservers, Google and Cloudflare resolved the new stock wildcard to 16.78.106.9. The VPS upstream resolver retained one negative fashion-demo lookup; direct connection to the authoritative IP with normal certificate validation succeeded. All eight tested roots/demo/fresh hosts returned HTTPS200. Browser smoke used a host mapping for that stale-cache hostname only; no TLS verification was disabled. See [domains.json](../../test_reports/full-development-uat-20261009/domains.json).

Before deployment, Caddy roots returned502 because they targeted unavailable localhost22130; the unrelated tailnet forwarder listens on another interface. Development roots/wildcards now route API→localhost8010 and SPA→localhost3010. `idsehub.my.id` is preserved; the entire existing `pay.idsepos.my.id` block is byte-identical. Config was validated before and after reload. The global on-demand ask now checks the isolated UAT registry and active lifecycle. Unknown domains and wrong-purpose registrations cannot obtain certificates; internal ask/docs are not publicly routed.

Services: `sellerbottel-uat-backend`, `sellerbottel-uat-frontend`, `sellerbottel-uat-dispatcher`, all enabled/active, dedicated journal logs. Dedicated Mongo container `sellerbottel-uat-mongo`, localhost27020 and separate volume; platform DB `sellerbottel_uat_platform`. Existing audit Mongo27019 remains separate. Storage/build/Python runtime `.uat-runtime`; config and five generated role credentials `.uat-private`, files0600. No secrets committed.

Callback ingress preserves the existing payment host/port8007. The development-only opt-in bridge forwards raw body/signature for references beginning `uat-` to fixed localhost8010. The destination validates Kasera signature before effects using the UAT registry/encryption key. All old references retain the original release namespace. No local apply-event call was used as evidence of genuine callbacks.

## Acceptance matrix

| Gate | Result and evidence |
|---|---|
| Public staging domains | PASS — owner-selected domains, eight DNS/HTTPS probes |
| HTTPS | PASS — certificate verification enabled; stale local DNS cache caveat above |
| Platform Owner login | PASS — HTTPS API and Android browser; fee control visible |
| Fresh tenant registration | PASS — genuine SMTP accepted, OTP verified; inbox receipt not manually confirmed |
| Tenant provisioning | PASS — fresh active tenant and both domain-purpose registrations |
| Tenant owner login | PASS — A/B API, B Android UI, fresh owner API |
| Tenant lifecycle | PASS — suspended/disabled A denied, B unaffected, A restored with data |
| Tenant A storefront | PASS — HTTPS, Android viewport, no JS errors |
| Tenant B storefront | PASS — HTTPS, Android viewport, no JS errors |
| Tenant Admin products | PASS — catalog, physical create/edit/image upload |
| Physical variants/SKU | PASS — four Hoodie variants, new CRUD variant |
| Stock panel/ledger | PASS — receive/adjustment/damage APIs, payment/return stock effects |
| Customer signup/login | PARTIAL — seeded A/B login PASS; new customer inbox signup remains owner checklist |
| Mixed cart | PASS — both tenants, one payment and three independent fulfillment records |
| Digital fulfillment | PASS — synthetic inventory delivered after genuine paid callback |
| Service fulfillment | PASS — owner completion independent of pending physical item |
| Physical fulfillment | PASS — packing/ready_to_ship/shipped/delivered for both |
| Manual shipping | PASS — typed address and manual fee; integrated shipping deferred |
| Tracking/resi | PASS — manual carrier and demo resi through shipment transitions |
| Kasera TEST checkout | PASS — real sandbox API, no live key/charge |
| Genuine Kasera webhook | PASS — both tenants' receipts applied through public pay host |
| Fee visibility | PASS — buyer quote and settlement components; Android platform fee control |
| Platform fee tiers | PASS — 20,000/20,001 boundaries, null upper bound, overlap rejection, frozen pending checkout snapshot; default250 restored |
| Settlement view | PASS — five immutable fee/net components, clearing/available transitions |
| Return/refund | PARTIAL — restock/damaged lifecycle and manual_refund_required intent PASS; no provider refund execution available |
| Branding modes | PASS API — platform/tenant_only/co_branded; full manual channel visual review pending owner |
| One tenant bot | PASS runtime — approved token validated, Digital worker active/restored after restart; manual Telegram journey pending owner |
| Two-bot isolation | NOT RUN — owner disabled second token |
| Join-gate | NOT RUN — safe test channel not supplied |
| Broadcast | NOT RUN — safe test recipients not supplied |
| Cross-tenant isolation | PASS — host/path mismatch rejected, foreign order404, lifecycle isolation |
| Coupons | PASS customer quote UAT10; tenant coupon editor absent from existing panel |
| Payout simulation | NOT RUN — Kasera sandbox funds cannot be used for mock payout; UI disabled with explanation |
| Backend full regression | PASS — 919 tests, 0 failed/0 skipped |
| Frontend tests/build | PASS — 11 suites /21 tests; CI production build |
| Secret-safe logs | PASS — no configured secret values in52 scanned journal lines; private files0600 |
| Safe demo reset | PASS guards/dry-run only; destructive execution NOT RUN |
| Production untouched | PASS — no production machine access/deployment/migration |
| Owner manual UAT | READY FOR OWNER — manual checklist deliberately unchecked |

## Evidence and retained demo data

- [public-flow.json](../../test_reports/full-development-uat-20261009/public-flow.json): HTTPS login, lifecycle, isolation, mixed checkout, provider simulation, genuine receipts, fulfillment and settlement details.
- [extras.json](../../test_reports/full-development-uat-20261009/extras.json): SMTP registration, provisioning/domain binding, branding, returns/restock/damage, manual refund intents and settlement.
- [operations.json](../../test_reports/full-development-uat-20261009/operations.json): fee tiers/frozen checkout, CRUD, upload and stock operations.
- [coupon.json](../../test_reports/full-development-uat-20261009/coupon.json): UAT10 quote applies independently to each shop.
- [android-browser.json](../../test_reports/full-development-uat-20261009/android-browser.json): 390×844 mobile smoke, owner/tenant login, no page errors or horizontal overflow on public pages. This is Chromium mobile emulation, not a physical Android-device certification.
- [runtime.json](../../test_reports/full-development-uat-20261009/runtime.json): active services, Caddy preservation, log scan, file modes.
- [bot.json](../../test_reports/full-development-uat-20261009/bot.json): Digital Demo @GrizzlySMS_notifbot. Old development audit poller stopped to prevent duplicate polling. No unsolicited bot message or broadcast sent.

Five accounts are listed in the handoff; passwords only `/home/sellerbottelv2/.uat-private/credentials.txt`. Fresh registration has its own private credential file. A separate pending service checkout captures the Rp500 tier and may expire normally; fee policy afterward is default250 with no tiers. Paid/returned demo orders are retained for owner inspection, not reset away. Manual refund intents are not successful financial refunds.

## Regression and limitations

Full backend regression and reset guard results are recorded in [regression.json](../../test_reports/full-development-uat-20261009/regression.json). Compileall and `git diff --check` pass. Frontend21/21 tests and CI build pass. Targeted domain registration rollback and UAT bridge tests cover stock-panel TLS ownership, unknown/wrong-purpose domains, safe rollback on stock-domain collision, raw signature forwarding, production/flag-disabled non-forwarding, and fixed bridge destination.

An initial sandbox-targeted test run stalled on fixture network/thread behavior and was terminated; the unrestricted targeted run passed25 tests. Browser automation initially used an explicit submit-button selector while the real button uses HTML's default submit type; correcting the harness selector produced a successful tenant login. A fee harness initially expected the post-payment computed field on a pending payment; it now checks the persisted fee-policy snapshot. Neither was reported as a product pass until rerun succeeded.

Existing tenant panel does not expose the complete coupon editor, analytics page or bot settings UI. Seeded coupon/customer flow and configured bot are available for UAT. These UI gaps, manual customer-signup verification, complete Telegram interaction/branding channel review and provider refund/payout limitations prevent an unqualified FULL PASS. Midtrans, Stripe, Biteship/integrated shipping, future providers and production payout/live settlement remain deferred. No live functionality was enabled to hide these gaps.

## Operations and rollback

Systemd units and exact deployed Caddy config are in `deploy/uat/`. Original Caddy backup is `.uat-private/Caddyfile.before`; restoring it would restore the prior development502 roots as well, so review before doing so. Payment bridge can be disabled by removing private `uat_bridge` and restarting only `sellerbottel-kasera-sandbox`; don't disable it while UAT checkouts await callbacks. Mongo/storage must be retained for pending payment reconciliation.

Reset tooling is `tools/reset_owner_uat.py`: default dry-run, exact two-demo allowlist and manifest identity checks, expected Mongo/platform namespace, explicit confirmation and stopped backend/dispatcher required. Fresh owner tenant and production resources are outside the reset scope. Destructive reset was not performed.

Baseline commits: `4ee7798`, `73bd7f5`. Work branch: `feature/full-development-owner-uat`. Final change commit is reported in the handoff response/Git history.

**Production: UNTOUCHED. Stop after handoff; owner findings start a separate UAT-fix sprint.**
