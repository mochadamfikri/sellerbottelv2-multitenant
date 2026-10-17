# Sellerbottel V2 — Implementation Progress

**Date:** 2026-10-17 (Asia/Jakarta)
**Scope:** Telegram native Rich Tables, staged and production-safe
**Current phase:** Phase A — Audit
**Overall status:** RUNNING (no production deployment)

## Safety gate

- Target repository verified: `/home/reaagent/sellerbottelv2-multitenant`.
- Development branch created: `feat/rich-table-audit-20261017`.
- Production process was not stopped or restarted.
- Active listener observed on `127.0.0.1:8002`, PID 18067 (`uvicorn server:app`, one worker).
- Existing working-tree changes were preserved; no files were overwritten.
- No production database, migration, Telegram broadcast, payment, or inventory operation was performed.

## Phase status

| Phase | Status | Evidence / next gate |
|---|---|---|
| A. Audit and backup | RUNNING | Repo/runtime/handler audit started; baseline test has one failure. Backup/rehearsal still required before deployment. |
| B. Shared Telegram Table Renderer | PENDING | Existing transport only wraps `sendMessage`/HTML; Rich Message adapter not found in initial scan. |
| C. Product catalog | PENDING | Existing `bot.py`, `product_catalog.py`, catalog tests identified. |
| D. Category/product list | PENDING | Existing stable catalog token/pagination logic identified. |
| E. Product detail/warranty | PENDING | Data fields and handler coverage require detailed audit. |
| F. Stock | PENDING | `checkout.py`, `inventory.py`, `inventory_admin.py` identified. |
| G. Purchase/deposit/history | PENDING | Purchase/deposit/stock event collections and handlers require mapping. |
| H. Admin validation | PENDING | Inventory upload validation exists; product metadata flow requires audit. |
| I. Integration/regression | PENDING | Blocked until earlier phases pass. |

## Initial findings

- Backend: Python/FastAPI + Motor/MongoDB; Telegram transport in `backend/tgapi.py`.
- Bot entry/flows: `backend/bot.py`, `backend/bot2.py`, `backend/bot_dispatcher.py`, `backend/reseller_bot.py`.
- Multi-tenant foundation exists, including tenant context/repositories, but legacy/global bot paths also exist and must be checked for scope leakage.
- Inventory secrets are encrypted by `backend/inventory.py`; listing must not expose them.
- Baseline command: `python3 -m pytest -q --disable-warnings --maxfail=1` from `backend/`.
- Baseline result: **FAILED** at `tests/test_tenant_db.py::test_resolve_platform_database_name_rejects_unsafe_environment_value[]`; 38 passed before stop. The empty configured `PLATFORM_DB_NAME` is currently treated as missing/default, while the test requires rejection.

## Current commit

- HEAD at audit start: `cdceb42a3c5c9b352f313892716186ea8f27c39a`.
- Documentation branch commit: to be recorded after this audit checkpoint.
- Existing local modifications are pre-existing and remain uncommitted.

## Next step

Complete the read-only handler/data mapping, decide the safe fix for the baseline failure, then implement only the shared renderer/transport on the development branch with isolated unit tests. Do not deploy until staging, backup/restore rehearsal, rollback plan, and smoke verification pass.

## Resume checkpoint — 2026-10-17

Status: BLOCKED at audit/release gate; no runtime code changed.
The active PID 18067 cwd is the original repository backend. A branch in that directory is NOT runtime isolation. All future implementation belongs in separate worktree `/home/reaagent/sellerbottelv2-rich-tables-dev`, branch `feat/rich-tables-isolated-20261017`, based on cdceb42. Existing dirty changes remain untouched in the original checkout; they are not incorporated in the clean development baseline and require compatibility review before release. No .env files were copied.

Official API verified live: https://core.telegram.org/bots/api#sendrichmessage supports rich_message with exactly one of html/markdown/blocks and reply_markup. Rich HTML tables support bordered/striped/compact, alignment and spans. Limits: 32768 text characters, 500 blocks, 20 columns, 16 nesting levels. Reuse existing httpx transport; no third-party renderer dependency necessary.

Handler map (partial, not full audit):
- Catalog/category: bot.show_products -> db.products(active) -> catalog_slice -> classic send_message; callbacks catalog/products/prod.
- Product detail: bot.show_product_detail -> product by active ID -> stock_for + price_for_product -> classic message; callbacks buy/cartadd/catalog.
- Stock: show_stock/show_stock_view; aggregation and permissions still need review.
- History: show_history -> deposits/purchases filtered user_tid, newest 50 each -> mixed event pagination, ten per page. Tenant isolation must be verified through ambient db proxy.
- Detail history: show_order_history_detail/show_deposit_history_detail.
- Secondary bot: bot2.show_products/show_product/show_stock/show_history; separate transport lifecycle requires tests.
- Admin inventory: inventory_admin.get_product/save_record/parse_text_records; API routes, not proof of equivalent bot admin menus.

Backup tooling: mongodump and mongorestore not found on PATH. No database backup or restore rehearsal performed; database topology/consistent snapshot strategy remains unverified. Do not deploy.
Next: resolve baseline contract decision, complete audit and backup strategy, then shared renderer with default-off flag and timeout-ambiguous no-resend behavior. Android/live Telegram acceptance remains BLOCKED without authorized test chat/device.

## Shared renderer implementation checkpoint
Implemented isolated files backend/rich_tables.py, backend/rich_table_transport.py, backend/tests/test_rich_tables.py. Shared renderer preserves rows, escapes HTML, enforces conservative budgets, returns labelled plain fallback. Transport reuses tenant-aware tgapi; feature flag defaults off; ambiguous timeout never retries/falls back; explicit 400/404 rejection may fall back. No existing handler imports these modules yet. Unit tests PASS; integration, staging deployment and Android verification PENDING/BLOCKED. No production deployment. Baseline full suite fails independently; do not promote.

## Baseline repair checkpoint
Offline suite PASS 624 tests excluding legacy live-server suite. Changed backend/tenant_db.py (fail closed on explicitly blank configured DB name); tests/test_bot2_flow.py, test_bot_start_welcome.py, test_reseller_flow.py, test_v2_platform_routes.py (stale expectations and isolation mocks). No live database/config changes. Deployment remains BLOCKED pending backup/rehearsal/staging/Android.

## Catalog pilot (development only)
backend/bot.py adds default-off native catalog/category list pilot. Existing legacy path remains unchanged with flag off. Uses real stock_for/pricing services and ambient tenant database; five rows per page, short list descriptions, ID callbacks; deletes previous message only after confirmed send. Warranty remains explicitly unknown pending metadata phase. Not yet complete: bot2/reseller integration, rich details, stock/history/admin forms/snapshots, live staging/Android, backup restore rehearsal. No phase deployment passed.

## Verified infrastructure gate
No mongodump/mongorestore/mongod/mongosh found on agent PATH. Docker CLI exists but daemon access returns permission denied; `sudo -n docker ps` requires a password. Only observed Mongo listener is localhost:27017 (treat as production; never use for tests). Backup/restore rehearsal and real DB staging are BLOCKED pending provisioned isolated MongoDB and backup tooling or authorized operator execution. No credentials requested through plain chat. Active app PID 18067 still listening at 8002.
Latest application pilot commit: e557a69; baseline repair be2bb1c; renderer d4825b7. No production rollout authorized or attempted.

## Product detail checkpoint
Detail produk native opt-in di bot utama ditambahkan; warranty enabled false dibedakan dari unknown; hanya ketentuan nyata dirender. Deskripsi panjang dipecah tanpa kehilangan data. Form metadata dan order snapshots belum diimplementasikan. User mengizinkan melewati gate infrastruktur untuk melanjutkan; tidak ada klaim backup PASS atau deployment. File: backend/product_rich_views.py, backend/bot.py, backend/tests/test_product_rich_views.py. Status implementation PARTIAL; deployment NOT DEPLOYED.

## Public stock checkpoint
Public Stock opt-in integrated into existing show_stock_view, preserving stockpage/stockadd/cart actions and stock service. Tables exclude unit secrets. Admin inventory and ledger not implemented. Flag remains off; no production deployment.

## History implementation
Opt-in main-bot order/deposit history and owned detail views wired; transaction projections exclude delivery secrets and use historical amounts. Existing user ownership queries preserved. New backend/history_rich_views.py and tests/test_history_rich_views.py. Snapshot presentation supported but snapshot creation/form metadata pending. Status RUNNING; NOT DEPLOYED.

## Warranty snapshot checkpoint
Purchase-time warranty snapshots added to balance checkout and direct QRIS order creation (additive fields only, old orders untouched). Pure WarrantyMetadata validator added but NOT wired to admin forms yet. Other commerce creation paths require audit. Status PARTIAL; no deployment.

Validated optional warranty metadata wired to authorized V2 product create/update request models; existing role/tenant dependencies unchanged. Legacy multipart/frontend forms remain pending.
