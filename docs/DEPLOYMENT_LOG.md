# Deployment Log

## 2026-10-17 — Audit checkpoint

- Status: **NOT DEPLOYED**
- Production service remained running; no restart or reload performed.
- Active local listener observed at `127.0.0.1:8002` (`uvicorn`, PID 18067).
- No production configuration, database, Telegram, payment, inventory, domain, port, or proxy changes made.
- Development branch: `feat/rich-table-audit-20261017`.
- Deployment will remain blocked until isolated staging tests, backup/restore verification, rollback procedure, smoke test, and explicit owner approval for any risky operation are available.

## 2026-10-17 authorized main-bot pilot deployment
Owner approved single backend restart at 19:47 WIB. Deployed only bot.py, rich_tables.py, rich_table_transport.py, product_rich_views.py, history_rich_views.py; TELEGRAM_RICH_TABLES_ENABLED=true. Source commit 4dc688ce4bee2d3ad1887a5ac76a01866856e490. Bot2 baseline unchanged, no reseller/frontend/DB changes. Private file/config backup: /home/reaagent/sellerbottel-deploy-backups/20261017T194907; backup byte equality verified. No DB backup/restore claim.
Initial wrapper child exited at exec cleanup after successful startup; restarted as tracked background exec rapid-forest (timeout disabled). Latest /api/ and /openapi.json HTTP 200; all five source hashes match; startup log has no tracebacks. This is API smoke verification, NOT Telegram render/checkout acceptance. Deployment included a brief interruption; zero downtime is NOT claimed. No real Telegram message or payment test sent.
Rollback: stop only tracked backend, restore bot.py and .env from private backup; remove five-file pilot additions only if verified newly introduced; launch original command with private saved launch environment. Do not roll back database: this pilot made no schema or data migration.
