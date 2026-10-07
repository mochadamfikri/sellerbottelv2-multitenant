# Owner Decisions Log — Phase 3 Migration Strategy

**Date**: 2026-10-04  
**Phase**: Phase 3 Commerce Core — Migration Prerequisites

---

## Decision 1: Customer Identity Scoping

**Question**: Email dan Telegram ID unique per-tenant atau global?

**Options**:
- A: Per-tenant unique (sama email bisa join 2 tenant berbeda)
- B: Global unique (1 email = 1 customer across semua tenant)

**Owner Decision**: **OPTION B (Global Unique)**

**Rationale**: 
- Email adalah identifier global di sistem
- Mencegah confusion dan potential fraud (1 user 1 identity)
- Telegram ID juga global unique (nature Telegram platform)

**Implementation Impact**:
- `store_customers.email` tetap UNIQUE global (no tenant_id in index)
- `store_customers.telegram_id` tetap UNIQUE global
- `bot_users.telegram_id` tetap UNIQUE global
- Customer dapat have membership di multiple tenant (via tenant_memberships)
- Cross-tenant customer data TIDAK duplicate (shared identity)

---

## Decision 2: Invoice Sequencing Strategy

**Question**: Invoice counter per-tenant atau preserve legacy?

**Options**:
- A: Per-tenant counter (tenant 'idse' #1-71, tenant 'acme' #1)
- B: Preserve legacy + per-tenant (IDSE keep #1-71, tenant baru #1)
- C: Global counter (semua tenant share 1 counter)

**Owner Decision**: **OPTION A (Per-Tenant Counter)**

**Rationale**:
- Setiap tenant punya invoice sequence independent
- IDSE tenant counter akan preserve legacy #1-71, continue from #72
- Tenant baru mulai dari #1
- Simpler tenant isolation (no global coordination)

**Implementation Impact**:
- `purchases.invoice_id` tetap UNIQUE global untuk backward compatibility
- New invoice generation: `<tenant_id>-<counter>` format (e.g., "idse-72", "acme-1")
- Legacy IDSE invoices #1-71 preserved unchanged (no prefix)
- Counter collection: per-tenant counter document (`{tenant_id: "idse", counter_name: "invoice", value: 71}`)

---

## Decision 3: Inventory Isolation Policy

**Question**: Inventory items bisa shared antar tenant?

**Options**:
- A: NEVER shared (strict boundary: 1 item = 1 tenant only)
- B: Shared pool allowed (platform inventory, tenants draw from pool)

**Owner Decision**: **OPTION A (Strict Isolation)**

**Rationale**:
- Multi-tenant security: prevent cross-tenant data leakage
- Simpler fulfillment logic (no cross-tenant stock transfer)
- Clear ownership: inventory_items belong to single tenant
- Digital product nature: once sold, cannot be resold

**Implementation Impact**:
- `inventory_items` add `tenant_id` field
- Unique index: `(tenant_id, product_id, fingerprint)` replaces `(product_id, fingerprint)`
- Stock queries MUST include tenant_id filter
- Cross-tenant inventory transfer: PROHIBITED (no API endpoint)
- Fulfillment: items allocated from same tenant inventory pool only

---

## Migration Strategy Approved

### Stage 1: Platform Control Plane (Development)
✅ **Approved to Execute**
- Create IDSE tenant record in platform registry
- Seed platform admin
- Verify tenant queries
- Risk: LOW (fully reversible)

### Stage 2: Tenant Database Dry-Run (Development)
✅ **Approved to Execute**
- Provision `sellerbottel_tenant_idse` database
- Test-tag 1 sample record per collection with `tenant_id: "idse"`
- Verify tenant isolation queries
- Delete test records (rollback)
- Risk: MEDIUM (validates schema, no production data)

### Stage 3: Full Legacy Migration (Development)
⚠️ **BLOCKED until Stage 2 passes**
- Tag all 3,804 records with `tenant_id: "idse"`
- Migrate from `sellerbottel_dev` → `sellerbottel_tenant_idse`
- Full reconciliation (counts, financial totals, integrity)
- Risk: HIGH (requires Owner sign-off after Stage 2 success)

---

## Schema Changes Summary

| Collection | Index Change | tenant_id Required? |
|------------|--------------|---------------------|
| `store_customers` | Email UNIQUE (global, no change) | NO (global identity) |
| `bot_users` | Telegram ID UNIQUE (global, no change) | NO (global identity) |
| `inventory_items` | `(tenant_id, product_id, fingerprint)` UNIQUE | YES |
| `products` | Add `tenant_id` index | YES |
| `purchases` | `invoice_id` UNIQUE (global preserved) | YES |
| `deposits` | Add `tenant_id` index | YES |
| `gopay_payments` | Add `tenant_id` index | YES |
| `reseller_commissions` | Add `tenant_id` index | YES |
| `counters` | Add `tenant_id` field | YES (per-tenant counter) |

---

**Approved By**: Owner  
**Decision Date**: 2026-10-04  
**Next Gate**: Stage 2 Dry-Run Success + Owner Review
