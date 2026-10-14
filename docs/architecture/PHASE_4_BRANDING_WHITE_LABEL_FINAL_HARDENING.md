# Phase 4 — Branding, White Label and Final Hardening

Starting revision: `6351094d7bd91bd221d5fdd0ab2fa3b45297653e`. Branch: `feature/v3-phase-4-final-hardening`. Builds on the [V3 master](sellerbottel-v3-master.md), [C1](PHASE_C1_COMMERCE_FOUNDATION.md), [C2](PHASE_C2_PHYSICAL_COMMERCE_MVP.md) and [Phase 3](PHASE_3_PAYMENT_SHIPPING_POST_PURCHASE.md). No production deployment or database migration is performed.

## 4A — One tenant identity

`branding.py` defines validated tenant identity stored in the tenant database's `branding/main`. It supports brand name, HTTPS logo/favicon/invoice logo, two strict hex colors, an allowlisted local font, description, Telegram/WhatsApp contacts, sender display name, receipt footer and social links. Domain is explicitly empty/disabled until ownership and TLS verification are implemented. There is no customer-controlled host-routing registration or wildcard TLS shortcut.

`platform` makes SellerBottel primary; `co_branded` makes the tenant primary with attribution; `tenant_only` removes attribution when authorized. Registry metadata capabilities are platform-controlled: `can_white_label`, `branding_mode_allowed`, `custom_email_branding_enabled`. `custom_domain_enabled` is always false. Tenant APIs cannot mutate registry capabilities. Entitlements are re-read for every settings/public identity read; revocation immediately falls back to an allowed mode. No plan names or new billing logic are introduced.

Identity drives storefront, checkout, shared tracking surface, navigation, favicon, generated product artwork, receipt, OTP/completion email and configured bot greetings. Tenant-only email sender customization separately requires email-branding capability; the envelope sender remains the existing platform SMTP address. No unverified tenant email domain is used. The receipt is an authenticated, customer-owned, escaped HTML document with restrictive CSP and no-store. Preview uses an empty-sandbox iframe. URLs are not fetched by the backend. HTML/control characters, CSS fragments, arbitrary fonts, unsafe schemes, credentials in URLs and nonempty custom domains are rejected.

Frontend identity is scoped to the current API prefix, ignores obsolete asynchronous responses and clears the previous identity during tenant changes. There is one frontend and one capability layer. Existing legacy bot identity remains compatible when a tenant has not configured the new branding record.

## 4B — Security regression

The Phase 4 suite exercises branding mode enforcement/revocation, tenant record isolation, lifecycle/stale tokens/reactivation, invalid/expired/customer owner credentials, upload type/corruption/size limits, storage path traversal and injection inputs. C1–C3 tests continue exercising the deeper stock, inventory, order, payment route, credential, refund, shipment and race boundaries. The [audit](../audits/phase-4-final-hardening-20261008.md) identifies evidence and limitations rather than treating mock tests as external certification.

Owner reads install the authenticated tenant database only after checking the current registry binding and lifecycle. Customer cookies and host/path routing remain tenant-bound. Raw provider/bank credentials remain encrypted, masked and absent from customer/owner responses. Historical credential versions remain usable for authenticating original payment callbacks; revocation prevents new payment creation. This intentional historical behavior is not a bypass.

## 4C — Bounded journals and recovery

`commerce/journal.py` implements a fixed-prefix immutable archive. A hot journal compacts at 512 events by archiving its first 256 events. Each owner has scalar `archive_generation`, `archive_hash` and `archive_totals`, rather than an ever-growing list of chunk IDs. Chunks contain owner, monotonically increasing generation, events, previous hash and SHA256 of canonical extended JSON.

The chunk is inserted with `$setOnInsert` **before** the owner CAS removes that exact prefix and advances the generation and counters snapshot. Appends can only extend the prefix. An interrupted pre-CAS write is uncommitted/invisible and the identical next attempt reuses it. Conflicting content fails closed. Readers use only generations at or below the owner's committed generation. A stale owner CAS retries. Missing committed chunks fail historical lookups. The existing single-document mutation of counters and new events remains authoritative and works with standalone Mongo.

Stock operations query archived event IDs, reservation/sale references and return sale references. Settlement operations query operation references, payment IDs or payout IDs. Historical effects remain idempotent after compaction. Per-payment pending/clearing, pooled available balances, payout state and refund liability still use original facts. A snapshot of nonmock credits preserves the prohibition on simulated payout consuming sandbox funds. Financial buckets derive from archived totals plus hot deltas; archival itself has no financial effect.

Immutable ledger/movement collections remain projections. Projection inserts use bounded batches and recover duplicate-only races, while propagating write-concern/nonduplicate failures. Routine reads/mutations do not rehydrate all archived history. Explicit `Journal.verify` streams chunks, validates generation/hash links/snapshots and can rebuild projections. `tools/audit_phase4_journals.py DATABASE [--repair] [--compact]` is restricted to fresh Phase 4 databases on localhost:27019. It never loads `.env`. Complete historical audit is proportional to history; ordinary hot operations are bounded, with indexed context lookups. Extremely many actions on one payment/return remain proportional to that operation's own history.

New indexes cover archive owner + event reference/payment/payout + generation, keeping tenant isolation at the database boundary. Existing uniqueness contracts are preserved. Tenant provisioning's test fixture was extended for the new collections without removing its original assertions.

`compose.mongo-dev.yaml` owns only the audit Mongo on localhost:27019, the retained named data volume and explicit nofile soft/hard 65536. The old container is kept stopped as a rollback reference. Restart checks confirm persisted limits and unchanged pre-existing database names. Never run both old/new containers against the same data volume.

Backup acceptance pauses the temporary backend/workers, exports complete disposable platform/tenant records and indexes plus a synthetic storage object, encrypts the backup outside git, replaces only that exact run's disposable databases, and restores under their **original names**. Name preservation is required for encrypted credential and deterministic idempotency bindings. Every restored document and index is compared before restart and callback replay. Production backup still requires coordinated writes or PITR, secure encryption-key escrow and an operational retention policy; the disposable test is not a production disaster-recovery certification.

## 4D — External sandbox boundaries

Kasera test credentials were explicitly supplied and exercised against the real provider API: discovery, create/retrieve, duplicate create, simulated paid/expiry. Additional fresh real-Mongo platform/self-gateway flows verify encrypted storage, checkout replay, original route/order mapping, one stock effect, platform settlement, zero self-gateway settlement and repair of a local failure after provider confirmation. These confirmations use authenticated provider status; **no genuine provider webhook was claimed**. A test webhook signing secret/public HTTPS endpoint is unavailable. Kasera API cancellation/refund/third-party payout remain unsupported.

Biteship test authentication, one approved rate request and one test-order request returned HTTP 400 / code 40000001. Both documented raw-token and Bearer formats were checked without recording credentials. The sandbox-readiness adapter is not registered for customer checkout; no Biteship shipping certification is claimed. Rate APIs can charge usage fees even with a test key and require a separate explicit opt-in. Midtrans has no supplied sandbox credentials and remains mock-verified only.

Sources: [Kasera test mode](https://pay.kasera.id/en/docs/api/test-mode), [Kasera webhook](https://pay.kasera.id/en/docs/api/webhook), [Biteship authentication](https://biteship.com/en/docs/api/authentication), [test-mode fee policy](https://help.biteship.com/hc/en-us/articles/58286997471513-Testing-Mode-Fee-Policy), [order create](https://biteship.com/en/docs/api/orders/create), [order cancel](https://biteship.com/en/docs/api/orders/delete). No supplied live key was used or persisted. Test secrets reside only in a private temporary input, never committed evidence.

## 4E — Migration and release boundary

See the [production candidate checklist](../ops/PRODUCTION_CANDIDATE_CHECKLIST.md). Branding is additive and defaults safely. Archive fields/collections are additive, but **after compaction C1–C3 binaries are not safe rollback targets** because they cannot read archived events/totals. Roll back only to an archive-aware build or restore a coherent pre-upgrade database/storage backup while writes remain paused. Reconstructing embedded journals can exceed Mongo document limits and is not a safe general rollback. No destructive migration auto-runs against production.

The complete launch candidate remains NOT READY while required genuine webhook/shipping dependencies are blocked and an approved reduced launch profile has not been selected. Optional provider futures remain deferred. Production rollout, DNS/TLS changes, live credentials, settlement and payouts require a separate owner decision.
