# Risk Register — V2 Discovery

Status: Active. Risks remain open until their listed controls and Owner decisions are completed.

| ID | Risk | Severity | Evidence / consequence | Required control | Status |
|---|---|---|---|---|---|
| R-01 | Wrong environment or live production database use | Critical | Production archive/config exists; Development restore is separate at `sellerbottel_dev`. A wrong URI can modify live data. | Environment allow-list, separate credentials, loopback/private binding, explicit production runbook and approvals. | Mitigated for Discovery; open for future migration. |
| R-02 | Production secrets exposed in archive | Critical | Archive contains production environment/infrastructure/payment-cache material. | Restrict archive/staging access; never copy/activate values; rotate exposed credentials; use secret manager. | Open — rotation/verification is Owner/operations work. |
| R-03 | Missing legacy tenant isolation | Critical | One database/direct collection access; no tenant context or tenant key found. | Select isolation model; tenant-scoped data access/authorization; automated cross-tenant tests. | Open — Owner architecture decision required. |
| R-04 | Cross-tenant data leakage in V2 | Critical | Shared data model without complete enforcement would expose PII/financial data. | Central tenant-context validation, repositories, tenant-aware indexes, negative authorization tests, audit logs. | Open. |
| R-05 | Financial migration/reconciliation error | Critical | Purchases, deposits, payment records, balances, commissions and payouts exist. | Preserve IDs/amounts/timestamps; dry run; count/sum/link reconciliation; idempotency; backup/rollback; approval gate. | Open — no V2 transform run yet. |
| R-06 | Production-only uncommitted source changes lost or blindly applied | High | Snapshot has edits in `backend/bot.py` and `backend/tests/test_direct_checkout.py`; active baseline is clean. | Preserve patch as evidence; code review/test selectively before any adoption. | Open. |
| R-07 | PII and marketing-consent noncompliance | High | bot users, prospects, storefront customers, messages and outreach data exist. | Owner retention/consent policy; least privilege; suppression/opt-out enforcement; PII-safe logs/reports. | Open — policy decision required. |
| R-08 | External side effects | High | Telegram, payment, broadcast/outreach integrations can notify users or process money. | Default disabled; sandbox credentials; explicit activation gates; rate limits/circuit breakers. | Mitigated for Discovery; open for implementation. |
| R-09 | Integration credentials shared across tenants | High | Legacy single deployment uses global configuration. | Per-tenant encrypted secrets, rotation, access audit; prohibit source/env token storage. | Open. |
| R-10 | Data uniqueness/counter collisions | High | Global invoice/customer/Telegram/fingerprint indexes and counters need tenant-aware redesign. | Explicit uniqueness matrix, counter strategy, migration validation and rollback. | Open. |
| R-11 | Incomplete index/schema verification | Medium | Restore count reconciliation is complete; verification artifact lists selected critical indexes, not a full schema contract. | Generate full schema/index manifest and validate it for migration rehearsal. | Open. |
| R-12 | Deployment infrastructure leakage | High | Archive contains Nginx, systemd, Docker and TLS-related material. | Treat only as sensitive reference; recreate reviewed environment-specific configuration. | Open. |
| R-13 | Commercial licensing/transfer ambiguity | High | Plan, subscription, quota, billing and source transfer requirements are not approved. | Owner defines commercial terms and ownership/transfer workflow before Phase 5. | Open. |
| R-14 | Cross-tenant analytics/privacy ambiguity | Medium | Platform analytics needs aggregation rules but customer/marketing data is sensitive. | Owner selects aggregation, consent, retention and access model. | Open. |
| R-15 | Release without recovery proof | Critical | V2 needs data migration and external integrations; failure needs tested recovery. | Backup/restore rehearsal, rollback test, incident runbooks, release gate. | Open. |

## Discovery Controls Confirmed

- Archive SHA256 and internal checksum manifest verified.
- Development source baseline is clean and matches remote baseline commit.
- Database restored only to isolated Development target `sellerbottel_dev`.
- Collection reconciliation passed: 46 collections and 3,804 documents, no discrepancies.
- Selected critical indexes verified by `dev_db_verification.json`.
- No production database/credential/integration was used during Discovery.

## Owner Risk Decisions Required

1. Accept and choose the tenant-isolation approach.
2. Set financial reconciliation/audit and payment-provider policy.
3. Set PII retention, consent, deletion, and analytics rules.
4. Define license, subscription, quota, billing, and source-transfer commitments.
5. Require a production-secret rotation review due to archive exposure.
