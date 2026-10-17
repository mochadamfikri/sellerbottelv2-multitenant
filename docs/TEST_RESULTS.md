# Test Results

## 2026-10-17 — Phase A baseline

**Environment:** repository development checkout; offline test harness; no production writes.

Command:

```bash
cd /home/reaagent/sellerbottelv2-multitenant/backend
python3 -m pytest -q --disable-warnings --maxfail=1
```

Result: **FAILED** — 38 passed before the first failure.

Failure:

- `tests/test_tenant_db.py::test_resolve_platform_database_name_rejects_unsafe_environment_value[]`
- `resolve_platform_database_name({"PLATFORM_DB_NAME": ""})` currently falls through to the default `sellerbottel`; the test expects an explicitly supplied empty value to be rejected.

No claim of full baseline pass is made. Detailed test results will be appended per phase.

## Isolated reproduction
Command: `ENVIRONMENT=test python3 -m pytest tests/test_tenant_db.py -q --disable-warnings` in isolated backend.
Result: FAILED, 22 passed / 2 failed (empty and whitespace PLATFORM_DB_NAME). Offline conftest installs Mongo mocks and disables outbound socket connections before application collection. No production .env exists in isolated worktree.
This is a pre-existing test/code contract disagreement. Do not silently change runtime fallback behavior on production.

## Renderer checkpoint
New pure renderer and opt-in transport: 12 tests PASS in 0.96s (escaping, pagination, empty state, limits, money validation, default-off, success, explicit rejection fallback, timeout ambiguity, rate limit and server error no-resend). No live Telegram calls.
Full unmodified baseline: 601 PASS, 13 FAILED, 17 ERROR, 20 warnings in 98.79s. Legacy backend_test.py requires live network and is correctly blocked by offline harness; other failures include tenant DB naming, bot2, welcome/menu, reseller notifications and platform routes. Full log local /tmp/sellerbottel-rich-baseline.log. This is baseline evidence, not a regression introduced by renderer (not integrated).

## Baseline repair verification
624 PASS, 20 warnings in 9.37s: `ENVIRONMENT=test python3 -m pytest -q --disable-warnings --ignore=tests/backend_test.py`. Legacy live-server suite explicitly excluded, NOT claimed passing; its offline network failures remain documented above.
Fixes: scoped QR transport mocks (real-shaped responses), correct welcome transport alias, grouped-menu/current brand assertions, notification feature flags + actual composer boundary mock, isolated platform registry fixture, reject explicitly blank configured database name while preserving fallback when absent. Original production configuration unchanged.
Earlier shared renderer/commerce subset: 53 PASS, 4 warnings in 1.87s.

## Catalog pilot regression
626 PASS, 20 warnings in 9.47s using offline suite excluding tests/backend_test.py. New flag-on integration tests prove five headers, tenant-isolated database selection, hidden product exclusion, no secret projection, stable product callback, and old-message retention when send fails. No Telegram device/API send performed.

## Product detail checkpoint
Detail checkpoint: 629 PASS, 20 warnings in 9.62s. Command ENVIRONMENT=test python3 -m pytest -q --disable-warnings --ignore=tests/backend_test.py. Long unicode description, conditional warranty, escaping validated; live Android and production deployment unverified.

## Public stock checkpoint
633 PASS, 20 warnings in 9.57s; offline suite excluding legacy live-server backend_test.py. Flag-on catalog/detail/stock tests verify tenant isolation, hidden products, secret exclusion and no delete after failed send. Android/live API remain unverified.

## History checkpoint
636 PASS, 20 warnings in 9.36s: offline suite excluding live-server backend_test.py. Pure tests verify historical amounts, WIB conversion, deposit fees, unknown historical warranty and explicit snapshots. Flag-on handler authorization tests still required.

## Warranty snapshot checkpoint
638 PASS, 20 warnings in 9.20s using offline suite excluding backend_test.py. Metadata validation and independent allowlisted snapshots tested. No claim of full acceptance or Android verification.

V2 commerce/authorization/metadata subset: 17 PASS, 4 warnings in 1.30s after optional warranty API field addition.

History authorization regression: 640 PASS, 20 warnings in 9.35s, same offline command. Explicit flag-on tests deny another user and another tenant order/deposit IDs before rendering; secrets excluded.

Secondary bot legacy + shared transport regression subset: 18 PASS, 1 warning in 1.18s. New secondary detail path still requires flag-on integration acceptance.

Latest branch bf9f389 regression: 640 PASS, 20 warnings in 9.32s; command unchanged, live-server suite excluded.

## Admin metadata compatibility checkpoint
Optional legacy admin metadata compatibility: 640 PASS, 20 warnings in 9.25s. Explicit HTTP tests for new optional field still needed; existing suite proves regression coverage only.

Products.jsx syntax PASS via existing Babel parser (read-only dependency reuse). This is NOT a frontend build/E2E PASS.
