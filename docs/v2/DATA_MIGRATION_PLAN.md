# Data Migration Plan — Verified Development Restore and V2 Migration

Status: **Development restore complete; V2 tenant migration requires Owner authorization.**

## Verified Development Restore

| Item | Result |
|---|---|
| Source archive | SHA256 `ca74ff070c82dec5d0f66e7b5ea38afcb24748cd935db01c84382d9444c1ab39` |
| Archive checksum manifest | PASS |
| Development target | `mongodb://127.0.0.1:27018/sellerbottel_dev` |
| Database source version | MongoDB 7.0.43 dump |
| Collection reconciliation | 46 expected / 46 actual |
| Document reconciliation | 3,804 expected / 3,804 actual |
| Collection discrepancies | 0 |
| Selected critical index checks | PASS |
| Production access | None |

The Development restore is the approved discovery data set. It is not a production deployment target and must not be connected to production Telegram, payment, email, or other outbound integrations.

## Safety Rules

1. Never use the production `sellerbottel` database, production connection URI, or production credentials for Development or test migrations.
2. Treat the restored `sellerbottel_dev` database as sensitive: it contains business data and likely PII. Limit access, do not expose it publicly, and do not use it for demonstrations.
3. Do not copy archive `.env`, TLS, Nginx, systemd, Docker, or payment-cache files into runtime configuration.
4. Keep the legacy application stopped or outbound integrations disabled while using restored data.
5. Back up the current target before each migration rehearsal; record archive checksum, source/target environment, operator, timestamp, and result.
6. Every migration must be dry-run capable, idempotent, reconciled, and rollback-tested before production authorization.

## Migration Scope

### In Scope
- Transform the single-tenant legacy data set into the approved V2 tenant model.
- Preserve business records, original identifiers, financial history, and required relationships.
- Assign legacy records only after Owner confirms the first-party tenant mapping (proposed: IDSE).
- Establish tenant-aware uniqueness, indexes, authorization, and auditability.

### Explicitly Out of Scope Until Authorized
- Production migration or deployment
- Production secret transfer or reuse
- External provider activation (Telegram, GoPay/QRIS, email)
- Destructive legacy cleanup
- Assumptions about tenant ownership beyond the single legacy deployment

## Source Data Groups and Handling

| Group | Collections / examples | Migration handling |
|---|---|---|
| Financial | purchases, deposits, gopay_payments, balance_adjustments, reseller_commissions/payments/payouts | Preserve `_id`, monetary values, status, timestamps, invoice and provider references; reconcile before/after totals and counts. |
| Catalog & stock | products, inventory_items, stock_events | Preserve product/item linkage, statuses, allocation history, and uniqueness constraints. |
| Identity | admins, bot_users, store_customers, prospects | Classify PII, establish tenant-scoped identity uniqueness and consent/retention rules. |
| Communications | bot_chat_messages, broadcasts, outreach_* , promo_suppressions | Preserve only under approved retention policy; retain suppression/opt-out protections. |
| Telegram state | tg_accounts, tg_groups, processed_updates* | Do not reuse tokens or activate polling/webhooks; determine whether deduplication state should migrate or reset. |
| Promotions | coupons, discounts, promo_* | Preserve active commitments only after business-rule review; empty collections need no data transform. |
| Resellers | reseller_* | Establish whether reseller relationships are tenant-private or platform-managed before transform. |
| Configuration | settings, counters | Replace secrets/environment-specific values; protect counters from collisions. |

## V2 Tenant Migration Design

### Preconditions

- Owner has selected the tenant isolation model and approved IDSE as the first-party tenant mapping.
- V2 schema/repositories enforce tenant context on every tenant-owned read/write.
- Target environment is isolated and backed up.
- Outbound integrations are disabled and sandbox credentials are used if adapters execute.
- Transform rules, reconciliation queries, and rollback procedure have been reviewed.

### Record Mapping

For each tenant-owned legacy record:

1. Retain legacy `_id` unless an approved compatibility mapping requires otherwise.
2. Add the approved `tenant_id` (do not infer a different owner from a deployment artifact).
3. Update uniqueness constraints to include `tenant_id` where a value may legitimately repeat across tenants, for example customer email, Telegram ID, invoice reference, product fingerprint, and coupon code.
4. Preserve cross-record references and transform referenced IDs only through an explicit mapping table.
5. Record migration metadata: migration version, source identifier, transformed timestamp, and checksum/run ID.

### Recommended Execution Sequence

1. **Freeze and backup**: Stop target-side workers; take encrypted backup and record baseline counts/indexes.
2. **Dry run**: Scan source, validate required fields and references, emit transform/reconciliation report without writes.
3. **Provision control plane**: Create approved IDSE tenant record and required tenant configuration.
4. **Create target indexes**: Establish tenant-aware indexes before write where safe; stage unique-index changes carefully.
5. **Transform low-risk reference data**: Products, settings (sanitized), non-secret configuration.
6. **Transform inventory and customers**: Preserve references, PII controls, and uniqueness semantics.
7. **Transform financial and order data**: Purchases, deposits, payments, balances, reseller commissions/payouts; reconcile each subdomain.
8. **Transform communications and integration state**: Apply retention/consent policy; keep integrations disabled.
9. **Reconcile**: Compare collection counts, financial totals, key uniqueness, referential links, and sample lifecycle paths.
10. **Acceptance test and sign-off**: Run tenant-isolation, checkout, inventory, and reconciliation tests before any environment promotion.

## Reconciliation Requirements

A migration run is successful only when it produces, stores, and reviews:

- Source and target document counts per collection/domain
- Missing/extra/error record report
- Count and sum reconciliation for purchases, deposits, provider payments, adjustments, commissions, and payouts
- Unique-key conflict report
- Referential-integrity report (product ↔ inventory ↔ purchase; customer ↔ purchase; reseller ↔ commission/payout)
- Counter/sequence collision assessment
- Tenant-boundary test results
- Selected document-shape and index verification
- Backup location/checksum and tested rollback result

Any mismatch must stop promotion unless explicitly classified and approved.

## Rollback

- Preserve an immutable pre-run backup and migration run log.
- Use a new target database or reversible migration markers where possible; do not mutate the only copy of the restored legacy data.
- If reconciliation or acceptance fails, stop workers, restore the pre-run target backup, verify restore counts, and retain the failed run report for correction.
- Production rollback requires a separately approved runbook and maintenance window.

## Open Decisions

1. Database-per-tenant or shared database with enforced tenant keys
2. Confirm IDSE identifier and ownership mapping for legacy records
3. Which communication history is retained and for how long
4. Per-tenant versus platform-managed reseller model
5. Payment merchant, settlement, refund, and audit policy
6. PII retention, consent, access, and deletion requirements

## Gates

| Gate | Required evidence |
|---|---|
| Development restore | Complete — 46 collections, 3,804 documents, no count discrepancies |
| Architecture approval | Owner tenant-isolation decision |
| Migration design approval | Mapping, indexes, reconciliation, rollback reviewed |
| Development rehearsal | Dry-run and write-run reports pass |
| Staging rehearsal | Integration-disabled/sandbox validation passes |
| Production authorization | Explicit Owner approval, backup, rollback, maintenance plan |
