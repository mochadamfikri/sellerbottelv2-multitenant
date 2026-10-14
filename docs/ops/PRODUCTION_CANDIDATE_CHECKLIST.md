# SellerBottel V3 — Production candidate checklist

**Decision: NOT READY FOR PRODUCTION CANDIDATE.** This is a source/configuration review and disposable-development validation, not a production inspection or rollout authorization. Production was not accessed or changed.

## Required external decisions before candidate approval

- [ ] Configure a dedicated Kasera sandbox HTTPS callback and its signing secret; verify genuine delivery, replay and local failure recovery. API/status tests already passed; they do not replace this gate.
- [ ] Replace/fix the rejected Biteship test credential, then verify rates, service selection, shipment, tracking and supported cancel in the application's shipping path. Biteship adapter currently remains a readiness probe and is not registered for checkout.
- [ ] Supply/verify Midtrans sandbox credentials if Midtrans is in the launch scope. Otherwise explicitly exclude it.
- [ ] Approve an exact launch profile. Until then, blocked providers are not treated as optional simply to obtain READY.
- [ ] Rotate any credentials shared in conversation before operational use, including the unused live keys. No such values are in source/evidence.
- [ ] Obtain merchant/commercial approval for platform settlement. Kasera API does not provide payouts to arbitrary third-party bank accounts. No real payout adapter is enabled.

## Environment and secrets review

- [x] Registry/database-per-tenant bindings and authenticated host/path/owner/customer scopes reviewed and tested.
- [x] Credential encryption uses `INVENTORY_ENCRYPTION_KEY`; keys must survive backup/restore and rotation. Changing the key without migration makes stored inventory/provider/bank values unreadable.
- [ ] Provision protected `JWT_SECRET`, inventory key, admin credentials and separate test/live provider/webhook secrets through the deployment secret mechanism; never build them into frontend or images.
- [ ] Disable `PHASE3_MOCK_ENABLED`, `PHASE3_SANDBOX_ENABLED`, `PHASE4_SANDBOX_ENABLED` and `PHASE4_BITESHIP_RATE_FEES_APPROVED` for production. No supplied live credentials were tested.
- [ ] Explicitly configure `GOPAY_ENABLED`, `STORE_QRIS_ENABLED`, `BOT2_ENABLED` and promotions for the approved launch profile. Legacy compatibility is not a license to enable production transports implicitly.
- [ ] Require `COOKIE_SECURE=true`, appropriate SameSite policy, exact `CORS_ORIGINS` and a trusted-proxy configuration matching the actual reverse proxy.

## Database/storage/runtime review

- [x] Dedicated development Mongo uses persistent nofile soft/hard 65536, localhost-only 27019 and retained named data volume. `docker compose -f compose.mongo-dev.yaml up -d` reproduces configuration.
- [x] Verification: `sudo docker inspect sellerbottelv2-dev-mongo --format '{{json .HostConfig.Ulimits}}'` and `sudo docker exec sellerbottelv2-dev-mongo sh -c 'cat /proc/1/limits'`; restart validated. Do not start the retained pre-Phase4 container alongside its replacement.
- [x] Stock/settlement archives have immutable chunk history, reproducible totals, bounded hot journals, indexed operation lookup and explicit verification/rebuild.
- [x] Existing route, SKU, fulfillment, invoice and customer uniqueness indexes preserved. New archive indexes are tenant-database scoped; index initialization is idempotent.
- [x] Quiescent disposable platform/tenant + storage backup/restore and backend restart tested, preserving original database names and credential/idempotency namespaces.
- [ ] Configure production Mongo access control, network isolation, capacity, monitoring and coordinated snapshots/PITR. Dev nofile verification is not evidence of production settings.
- [ ] Secure production storage mount/permissions, encrypted backup retention, off-host copies and key escrow; schedule restore drills with matching database/storage boundaries.
- [ ] Ensure a single intended worker topology. Existing claim/CAS protections remain, but deployment must deliberately operate dispatcher, provider-free expiry and canonical payment maintenance workers.

## Proxy, communications and branding review

- [x] Arbitrary custom domains disabled; tenant input cannot bypass ownership or TLS verification.
- [ ] Set canonical `PUBLIC_BASE_URL`, registry host bindings, HTTPS certificates and public webhook URLs. Production DNS/Caddy changes require separate authorization.
- [ ] Validate SMTP TLS/auth, verified envelope sender and delivery. Tenant sender display names require capability; tenant-supplied SMTP domains/credentials are not accepted by branding.
- [ ] Validate intended production Telegram bot ownership, token isolation, dispatcher/webhook secret and lifecycle behavior. No Telegram/SMTP message was sent during this phase.
- [x] Branding input validation, mode entitlement enforcement, receipt CSP and tenant identity isolation reviewed/tested. Browser modes and owner preview verified.

## Upgrade and rollback runbook

1. Confirm a reviewed archive-aware revision, green evidence and explicit owner launch authorization.
2. Pause writes and workers; take a consistent database + storage backup and verify encrypted key recovery.
3. Apply additive indexes/branding defaults. Review index conflicts explicitly; do not drop unique indexes automatically.
4. Deploy the archive-aware binary before any compaction. Existing small journals remain readable with zero backfill; oversized old journals can be drained by a controlled audited compaction job.
5. Verify archive hashes/totals/projections, tenant registry bindings, public host resolution, pending orders and reconciliation queues. Resume workers only after those checks.
6. Roll back only to an archive-aware binary after compaction. For older binaries restore a coherent pre-upgrade backup during a write freeze; assess transactions received after the snapshot separately. Never silently discard or truncate history.

## Observability and limits

- [x] Acceptance scans runtime logs/evidence for generated and supplied secrets, while retaining scoped operation IDs, status/HTTP outcomes and error classes.
- [x] Bounded catalog/order/settlement/shipment/return/route lookup smoke performed; no production load certification is claimed.
- [ ] Configure operational alerts for reconciliation backlog, unknown provider outcomes, pending leases, archive integrity errors, backup age, worker health and disk usage.
- [ ] Decide retention/pagination UX for historical ledger browsing; full history is preserved and auditable even when the normal owner response shows only the hot tail.

Deferred optional features: DOKU, tenant GoPay Merchant adapter, OttoPay, Stripe, advanced warehouse and advanced fraud tooling. Stop after Phase 4; no automatic deployment or live financial enablement.
