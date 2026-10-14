# SellerBottel V2 tenant audit — 8 October 2026

Scope: `/home/sellerbottelv2`, offline validation only. No production deployment,
MongoDB connection, real Telegram message, SMTP delivery, payment, Caddy change,
or secret configuration change was performed.

Initial HEAD: `530a6a05b3b6f89eba138adbc126e45f70d0c7df` on `main`, clean working tree.
Implementation branch: `fix/tenant-management-audit-20261008`.
The final commit SHA is provided in the accompanying final report; `git rev-parse HEAD`
identifies the commit containing this report.

## Baseline evidence

Tests were attempted before application edits. The checkout had no backend virtualenv
or frontend node_modules. After isolated dependency installation:

- CI backend requirements failed collection: missing Pillow; a second pass exposed
  missing Telethon and email-validator. `backend_test.py` is a live HTTP script and
  also required requests; it was deliberately excluded from the offline rerun.
- Original HEAD was exported into `/tmp/sellerbottel-baseline` to obtain an unchanged
  full baseline after dependency installation: **566 passed, 11 failed, 35 errors**.
- Frontend unit baseline: **2 suites / 5 tests passed**.
- Frontend build with `CI=true`: **failed** on Hook dependencies in DnsVerify and
  TenantPanel. Hook lint rules were not disabled or weakened.
- Sandboxed Python thread/event-loop execution hung on the first HTTP integration
  test. The same offline analytics test passed outside the sandbox in 0.67 seconds.
  Subsequent backend runs used the offline runner outside the sandbox, still with
  mocked MongoDB and outbound sockets blocked.

Original full baseline failure groups: bot2 QR send returning None; bot2 catalog
heading compatibility; welcome sends bypassing the tested message helper; horizontal
main menu; empty platform DB names; shared mock indexes and registry data leaking
between modules; old channel-notification test omitting enabled feature settings.

## Findings and implementation

| Area | Finding | Resulting behavior |
| --- | --- | --- |
| CI | Two backend files only, missing import dependencies, frontend build only | Full `test_*.py` suite through offline runner; Pillow/Telethon/email-validator included; frontend unit tests plus strict CI build; lockfile-based npm ci |
| Auth | Global Axios tenant Authorization; logout retained header | Separate in-memory Axios instance per session, context supplied to tenant children; logout clears header, session, password and panel data; platform/public Axios receives no tenant bearer |
| Lifecycle | Public owner APIs did not require active tenant | Login and every simple/full management request require active status and matching owner tenant ID; stale tokens stop working immediately after suspension |
| API | Tenant inventory used owner URLs; missing wrappers and order response mismatch | Inventory, transform, session replacement, schema/template and order operations reuse existing logic inside validated tenant DB/token scope |
| Catalog | Product/catalog links left tenant admin; invalid bodies raised internal validation errors | Links stay in `/admin?tab=...`; typed catalog request models produce HTTP 422; prices/catalog assignment remain product-based |
| Images | Owner artwork URL/auth dependency | Public label-only artwork preview; private tenant images fetched with the isolated Axios token and rendered using revocable blob URLs |
| Panel | Duplicate auth/UI implementation, unused simple-product forms, undefined Send/X | TenantAdmin is canonical; legacy `/panel-tenant` re-exports it; unused forms removed and Send imported |
| Host routing | Tenant determined by hardcoded hostname suffix | `/public/host-config` resolves registered storefront hosts, including custom domains; lookup failure does not render owner panel |
| Registration | Missing store_name, inconsistent verified email, ignored domain/provision failures | Canonical email validators, owner store_name, explicit delivery failures, domain preflight plus atomic claim; compensation removes this attempt's owner/domain/tenant/new DB on failure; verification is consumed only after success |
| Domain registry | Upsert could overwrite another tenant mapping | Unique domain index; insertion claims ownership; same owner is idempotent with JSON-safe responses; other owner conflicts; canonical trailing dot normalization; indexes ensured at startup |
| Database | Normalized slug aliases could select same DB; registry/startup index definitions differed | Unique database_name claim plus collision detection; consistent index initializer; provisioning is idempotent and does not inherit platform admin Telegram ID |
| Bot dispatcher | Partial token fingerprint, arbitrary first-active central tenant fallback, catch-all dedup errors | Full SHA256 fingerprint; central resolves only its configured owner (legacy default idse); cancellation awaited; only DuplicateKeyError treated as duplicate; dedup includes bot identity; tenant payment/stock/followup/recap/marketing jobs inherit scope and are cancelled with the worker |
| Bot flow state | Edit targets, checkout locks, service tasks, bot2 last message and join-gate cache were process-global | Maps partitioned by tenant DB, worker slug and bot identity |
| Bot UX | Horizontal menu contradicted acceptance test; unconfigured tenant branding fell back to platform | One button per row; tenant scope branding before legacy defaults; reseller opt-in defaults false for tenant scopes, central configured separately |
| Dashboard/broadcast | Wrong users/catalog collection; broadcast queue had no consumer | Counts use bot_users/product_catalogs; full tenant broadcast reuses the actual broadcast worker with tenant token/DB and stops sending when tenant is suspended |
| Logs | OTP values and HTTP exceptions could include credentials | OTP no longer logged; audited registration/dispatcher/join-gate errors log exception class and safe tenant identifiers; root log formatter also redacts Telegram URLs, Mongo URLs, Authorization and configured secrets, including exception traces |

One email maps to one public tenant owner. This follows the current login lookup's
single-owner `find_one(email)` contract; unique owner email prevents ambiguous login.
Multi-store ownership for one email would need an explicit account/tenant selector
and a separately agreed business rule, rather than removing this index silently.

## Tenant API boundary

- `/api/public/tenant/login` and `/me`: account/session endpoints.
- `/api/public/tenant/full/...`: canonical management API consumed by TenantAdmin.
- Existing simple management endpoints remain for compatibility and still enforce
  active lifecycle; the simple broadcast endpoint delegates to the canonical worker.
  New management UI should not use the legacy simple product/stock contracts.
- `/api/public/host-config`: public hostname-to-tenant-slug discovery only; accepts
  a host query for frontend deployments whose API base URL uses another host. It
  grants no access and returns no owner, credentials or tenant DB details.
- `/api/public/artwork-preview`: public generated artwork from bounded labels only.
- Full APIs select DB from the authenticated owner and registry, never from an
  arbitrary `X-Tenant-ID`, query parameter or body field.

| Resource | Canonical operations |
| --- | --- |
| Products | GET/POST products, PUT/DELETE product, PATCH toggle, import/template, authenticated image |
| Catalogs | GET/POST/DELETE catalogs, PUT rename/assign |
| Inventory | GET list/summary/template; POST validate/import/manual/transform/inspect/session-file replacement; PUT schema/record; DELETE item |
| Orders | GET list/detail, POST service complete/refund/email retry |
| Dashboard/users | GET stats/users |
| Broadcast | GET history, POST message with scoped live worker |

Static contract tests cover required method/path pairs and prohibit owner URLs,
global Authorization assignments and owner product/catalog navigation in the five
management pages. HTTP tests exercise real wrappers with mock tenant databases,
including cross-tenant denial and context restoration after errors.

## Behavior decisions and test corrections

- V2 `/start` retains its IDR display fallback without forcing first-run currency
  selection. This differs from the old SellerBottel flow and has explicit regression
  coverage. No requirement requested restoring the old currency selection.
- Dynamic welcome uses the tenant/BotFather name; the stale return-to-main assertion
  was updated from generic Bot Store to its fixture's Test Store Market. Profile,
  username, balance, first_start_at, purchased PCS and coupon assertions remain.
- Vertical main menu follows the existing acceptance test.
- Bot2 retains catalog navigation and also includes its established LIST PRODUCT
  heading, satisfying both catalog and legacy callability contracts.
- The old reseller image test now explicitly enables channel notifications and
  automatic images and mocks the current send_composed photo dependency. The test
  still requires both admin and channel images; disabled notification behavior is
  independently tested and preserved.
- Mock isolation drops mock collections/data/indexes between test modules, guarded
  by an AsyncMongoMockClient type assertion. Production indexes are not weakened to
  accommodate test fixtures. No test was deleted or skipped to hide a failure.

## Custom domain and deployment limits

Custom domains can be claimed without takeover and recognized for `/admin`, but
**custom-domain TLS is intentionally not enabled**. Custom claims are unverified;
public registration cannot claim the known platform hosts or managed namespace.
The TLS ask endpoint continues to require a registered managed storefront domain
and now allows only active tenants, including denial of failed/provisioning tenants.
Managed subdomain behavior is covered by regression tests.

Before custom TLS activation, implement backend-owned DNS ownership proof (e.g.
challenge TXT), verify A/AAAA routing against the configured ingress, mark the exact
claim verified, and ensure the runtime serves both SPA and API for that host.
Then extend tls-ask to require verified ownership and an active tenant. An A record
pointing at the shared server alone is insufficient proof. Caddy/TLS and external
infrastructure were not modified by this audit.

Live Mongo unique-index behavior, SMTP/Telegram/payment delivery, DNS and TLS issuance
remain untested. Local tests used Python 3.14.4; CI is configured for Python 3.12.
Dependency deprecation warnings are reported without suppressing lint or tests.
Existing live databases with conflicting email/database/domain keys or equivalent
indexes under older names need a read-only reconciliation before index creation;
no destructive migration was added.

Registration rollback is compensating work, not a Mongo multi-document transaction.
It refuses pre-existing tenant DBs and cleans only a newly claimed DB. A real DB outage
that also prevents compensation still requires operational recovery. Broadcast jobs
use the existing process-local worker; restart recovery of unfinished broadcasts and
exactly-once Telegram delivery are not claimed. Dispatcher update dedup preserves
at-most-once claim semantics; a process crash after claiming an update needs separate
durable recovery design. These limits require live acceptance before a release.

## Reproduce validation

From backend with an isolated virtualenv installed from requirements-ci.txt:

```sh
python -m compileall -q .
python run_offline_tests.py tests/ -q
```

The runner disables dotenv loading, installs AsyncMongoMockClient before application
imports, uses a mock-only Mongo URL/DB, and rejects outbound socket connections.
The unchanged pytest xdist configuration remains intact; the runner intentionally
uses its existing serial override for these legacy mock suites.

From frontend:

```sh
npm ci --ignore-scripts --no-audit --no-fund
CI=true npm test -- --watchAll=false --runInBand
CI=true npm run build
```

Live `backend/tests/backend_test.py` is excluded by the test_*.py discovery boundary.
It must be invoked deliberately in an isolated live integration environment with
appropriate test credentials; it was not run here. Offline HTTP tests use ASGITransport
or TestClient against an in-process app and never require a running production server.

Final validation counts and per-module results follow below.


## Final validation results

| Group | Result | Evidence |
| --- | --- | --- |
| Full offline backend | PASS — 678 tests, 0 failures/errors/skips | [JUnit XML](../../test_reports/tenant-audit-20261008/backend.xml) |
| Frontend unit | PASS — 5 suites / 9 tests | tenant Axios isolation, canonical panel login/logout/tab navigation, custom host routing, existing catalog/platform helpers |
| Frontend production build | PASS with CI=true | Compiled successfully; no React Hook warning/error |
| Python compileall | PASS | All backend modules |
| Static tenant API contract | PASS — 40 cases | Required route methods/paths, five management pages without owner URLs, legacy canonical panel |
| GoBiz syntax | PASS | node --check on gobiz.js, create_qris.mjs, history.mjs |
| Whitespace/diff check | PASS | git diff --check |
| Real Mongo/Telegram/SMTP/QRIS/DNS/TLS E2E | NOT RUN | No production DB or external integration used; no deployment authorized |

Backend results by module (all PASS; classes grouped into their source module):

| Test module | Passed |
| --- | ---: |
| test_analytics_routes | 1 |
| test_audit_events | 18 |
| test_audit_events_persistence | 5 |
| test_audit_lifecycle_events | 2 |
| test_bot2_flow | 6 |
| test_bot_dispatcher_regression | 6 |
| test_bot_start_welcome | 5 |
| test_bot_tenant_scope | 4 |
| test_broadcast_composer_stock | 4 |
| test_broadcast_reports | 3 |
| test_catalog_delivery_flow | 6 |
| test_catalog_repository | 7 |
| test_central_broadcast_discount | 4 |
| test_commerce_security | 42 |
| test_config_safety | 29 |
| test_control_plane_setup | 5 |
| test_customer_identity_repository | 12 |
| test_dependencies | 3 |
| test_direct_checkout | 8 |
| test_discount_validation | 3 |
| test_domain_registry | 2 |
| test_dry_run_reconciliation | 8 |
| test_feature_upgrade | 5 |
| test_global_identity_policy | 45 |
| test_idse_stage3_migration | 8 |
| test_idse_tenant | 5 |
| test_inventory_upload | 20 |
| test_invoice_counter_repository | 7 |
| test_invoice_sequencing | 20 |
| test_master_revision | 12 |
| test_migration_planning | 6 |
| test_migration_runner | 9 |
| test_platform_indexes | 9 |
| test_platform_rbac | 4 |
| test_platform_rbac_memberships | 8 |
| test_product_catalog | 6 |
| test_public_tenant_management | 16 |
| test_purchase_source | 17 |
| test_rbac_slug_resolution | 8 |
| test_reseller_flow | 12 |
| test_sandbox_payment | 10 |
| test_secret_safe_logging | 2 |
| test_server_startup | 3 |
| test_stage2_report | 6 |
| test_stage3_execute | 12 |
| test_storefront_auth | 3 |
| test_subscription_pricing | 8 |
| test_tenant_context | 5 |
| test_tenant_context_mongo | 4 |
| test_tenant_db | 24 |
| test_tenant_db_proxy | 1 |
| test_tenant_frontend_contract | 40 |
| test_tenant_inventory | 9 |
| test_tenant_isolation_security | 27 |
| test_tenant_orders_repository | 13 |
| test_tenant_provisioning | 11 |
| test_tenant_provisioning_index_contracts | 9 |
| test_tenant_registry | 8 |
| test_tenant_registry_mongo | 6 |
| test_upgradeversi | 18 |
| test_v2_commerce_authorization | 5 |
| test_v2_commerce_routes | 10 |
| test_v2_customer_config | 11 |
| test_v2_platform_bot_provisioning | 5 |
| test_v2_platform_lifecycle | 9 |
| test_v2_platform_routes | 5 |
| test_v2_platform_routes_dependency | 2 |
| test_v2_tenant_routes | 3 |
| test_wallet_ledger | 9 |

Commands executed used `/tmp/sellerbottel-audit-venv/bin/python` for backend. Full
regression was run after each substantive correction group; the final full command
was `python -u run_offline_tests.py tests/ -q --junitxml=/tmp/sellerbottel-final-backend.xml`.
Frontend final commands were `CI=true npm test -- --watchAll=false --runInBand` and
`CI=true npm run build`. Local dependency installation used npm install with scripts
ignored; the existing package-lock.json was unchanged and CI uses npm ci.

No known failing offline acceptance test remains. Live runtime readiness and
custom-domain HTTPS are deliberately not marked PASS.

## Files changed

- `.github/workflows/ci.yml`
- `README.md`
- `backend/admin_routes.py`
- `backend/bot.py`
- `backend/bot2.py`
- `backend/bot_dispatcher.py`
- `backend/bot_tenant_scope.py`
- `backend/domain_registry.py`
- `backend/gopay_provider.py`
- `backend/join_gate.py`
- `backend/platform_indexes.py`
- `backend/public_registration.py`
- `backend/pytest.ini`
- `backend/requirements-ci.txt`
- `backend/run_offline_tests.py`
- `backend/secret_safe_logging.py`
- `backend/server.py`
- `backend/tenant_db.py`
- `backend/tenant_full_routes.py`
- `backend/tenant_provisioning.py`
- `backend/tenant_registry.py`
- `backend/tests/conftest.py`
- `backend/tests/test_bot_dispatcher_regression.py`
- `backend/tests/test_bot_start_welcome.py`
- `backend/tests/test_domain_registry.py`
- `backend/tests/test_public_tenant_management.py`
- `backend/tests/test_reseller_flow.py`
- `backend/tests/test_secret_safe_logging.py`
- `backend/tests/test_tenant_frontend_contract.py`
- `docs/audits/tenant-management-20261008.md`
- `frontend/craco.config.js`
- `frontend/src/App.js`
- `frontend/src/components/TenantImage.jsx`
- `frontend/src/lib/tenantApi.js`
- `frontend/src/lib/tenantApi.test.js`
- `frontend/src/pages/DnsVerify.jsx`
- `frontend/src/pages/TenantAdmin.jsx`
- `frontend/src/pages/TenantAdmin.test.jsx`
- `frontend/src/pages/TenantCatalogs.jsx`
- `frontend/src/pages/TenantHostRouting.test.jsx`
- `frontend/src/pages/TenantInventory.jsx`
- `frontend/src/pages/TenantOrders.jsx`
- `frontend/src/pages/TenantPanel.jsx`
- `frontend/src/pages/TenantProducts.jsx`
- `frontend/src/setupTests.js`
- `test_reports/tenant-audit-20261008/backend.xml`
