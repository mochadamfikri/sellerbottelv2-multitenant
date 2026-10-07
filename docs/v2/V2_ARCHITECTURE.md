# V2 Architecture — Discovery Recommendation

Status: **Owner review required**. Recommendation checked against verified production source baseline (`3a75b1cc2ab2fbe297556e098bba90d635d631a8`) and restored Development database. Not implementation authorization.

## Legacy System Baseline — Verified

**Source**: Production system snapshot analyzed  
**Code baseline**: GitHub `mochadamfikri/sellerbottel` commit `3a75b1cc2ab2fbe297556e098bba90d635d631a8`  
**Database**: MongoDB 7.0.43, database `sellerbottel`, 46 collections, 3,804 documents  
**Development environment**: Code and data verified, isolated from production

### Current Architecture
Legacy is a **single-tenant** FastAPI + Motor/MongoDB backend with React admin/storefront and integrated Telegram bot. `backend/db.py` selects one MongoDB database using `MONGO_URL` and `DB_NAME`; routers and services access collections directly via Motor. 

**No tenant isolation**: Source code audit (backend and frontend) found no explicit tenant context, no `tenant_id` filtering, and no tenant-scoped authorization. All data resides in a single namespace without boundaries.

Production manifest documents one MongoDB database `sellerbottel` on MongoDB 7.0.43. Development restoration to isolated database `sellerbottel_dev` confirmed all collections and indexes intact.

## Proposed V2 Target Architecture

### Design Principles
1. **Explicit tenant boundaries** — Every tenant-owned record must carry `tenant_id`; all queries must be tenant-scoped
2. **Platform-tenant separation** — Platform control plane data (tenants, licenses, provisioning) must not mix with tenant business records
3. **Authorization at boundaries** — Validate tenant context at service entry points, not within business logic
4. **Financial integrity** — Preserve all IDs, maintain referential integrity, support reconciliation and audit
5. **Security in depth** — Secrets in vault/encrypted store with rotation; no production credentials in config
6. **Safe defaults** — Disabled integrations, sandbox credentials, and explicit gates for production operations

### Proposed Boundaries

#### Platform Control Plane
**Purpose**: Multi-tenant SaaS management  
**Scope**:
- Tenant registry (ID, name, status, created, owner contact)
- Plans and licenses (subscription tier, features, quotas, expiry)
- Provisioning state (database credentials, resource allocation)
- Custom domains and branding
- Billing and subscription events
- Platform-wide analytics and reporting
- Owner audit logs

**Isolation**: Separate database or strictly isolated collection prefix. Tightly authorize all cross-tenant operations. Never mix with tenant business data.

#### Tenant Application Plane
**Purpose**: Per-tenant business operations  
**Scope**:
- Catalog and inventory (products, items, stock)
- Storefront and customers (accounts, auth, profiles)
- Checkout and orders (purchases, invoices, fulfillment)
- Wallet and ledger (deposits, balance, transactions)
- Coupons and promotions (campaigns, redemptions, limits)
- Communications (broadcasts, messages, opt-outs)
- Analytics and reporting (tenant-scoped only)
- Telegram channel configuration (bot tokens, groups)
- Tenant admin users and roles

**Isolation**: Every record has explicit `tenant_id` field. All data access goes through tenant-scoped repositories. Validated tenant context passed through request chain. Separate MongoDB database per tenant provides strongest isolation (credentials, backups, quotas); shared database with enforced tenant keys is operationally simpler but requires comprehensive authorization layer.

**Owner decision required**: Database-per-tenant versus shared-database model.

#### First-Party IDSE Tenant
Current production data represents the owner's own store (IDSE). Represent IDSE as a normal tenant record (`tenant_id: "idse"` or similar), not a privileged hard-coded fork. This preserves migration simplicity and allows owner to use standard tenant features (domain, branding, analytics).

All existing production records should be tagged with IDSE tenant ID during migration. Preserve original `_id`, `invoice_id`, and all financial/referential data.

### Proposed Service Modules

#### Catalog & Inventory
- Product definitions (name, description, pricing, artwork)
- Inventory item pool (digital codes, credentials, status)
- Stock level monitoring and alerts
- Bulk import and transformation

**Tenant scoping**: `tenant_id` on products and inventory_items. Prevent cross-tenant inventory allocation.

#### Orders & Fulfillment
- Checkout and purchase flow
- Invoice generation (`invoice_id` unique per tenant)
- Payment provider integration
- Idempotent order processing (`customer_id + idempotency_key` unique)
- Fulfillment (item allocation, delivery)
- Post-purchase actions

**Tenant scoping**: All orders, invoices, and fulfillment records tenant-isolated. Payment reconciliation per tenant.

#### Wallet & Ledger
- Deposit processing
- Balance tracking
- Transaction history
- Manual adjustments (with audit log)

**Tenant scoping**: Customer wallets and deposits are tenant-private. Cross-tenant balance queries prohibited.

#### Customers & Identity
- Customer accounts (web storefront, Telegram)
- Authentication and sessions
- Profile management
- Access control

**Tenant scoping**: Customers belong to single tenant. Email/telegram_id unique within tenant, not globally.

#### Promotions & Discounts
- Coupon codes and usage limits
- Discount rules and campaigns
- Redemption tracking
- Promotion events

**Tenant scoping**: Coupons and campaigns are tenant-private. Redemption counts per tenant.

#### Communications
- Telegram bot management
- Broadcast campaigns
- Message history
- Outreach and marketing automation
- Consent and suppression lists

**Tenant scoping**: Telegram bot tokens, groups, and message history are tenant-isolated. Broadcasts never cross tenants.

#### Reseller Program
- Reseller onboarding and bots
- Commission calculation
- Payout processing
- Contest management

**Tenant scoping**: Resellers belong to specific tenant. Commission records tenant-private.

#### Analytics & Reporting
- Tenant-scoped dashboards
- Sales and inventory reports
- Customer analytics
- Platform-wide aggregations (control plane only)

**Tenant scoping**: Tenants see only their own analytics. Platform analytics aggregate with privacy controls.

**Owner decision required**: Cross-tenant analytics policy, data anonymization.

#### Platform Management
- Tenant lifecycle (create, suspend, delete)
- License and subscription management
- Resource quota enforcement
- Billing and invoicing
- Platform audit logs

**Authorization**: Platform operations require elevated privileges, never tenant-level access.

### Channel Adapters

#### Telegram Integration
- Bot token management (per tenant)
- Webhook/polling configuration
- Group and channel management
- Message sending and receiving
- Update deduplication

**Tenant isolation**: Each tenant has own bot token(s), group memberships, message history. No shared bot across tenants.

**Security**: Tokens in secret manager, never in config. Production tokens never in Development.

#### Payment Providers
- GoPay/QRIS integration
- Payment initiation and callbacks
- Transaction reconciliation
- Refund processing

**Tenant isolation**: Separate merchant credentials per tenant. Tenant-scoped reconciliation.

**Security**: Merchant secrets in vault. Sandbox credentials for Development. No production payment processing without explicit authorization.

#### Email & Domains
- Custom domain support
- Email delivery (transactional)
- Domain verification

**Tenant isolation**: Tenant-branded emails, custom domains where licensed.

### Data Isolation Options

#### Option A: Database-per-tenant (Recommended for strong isolation)
**Pros**:
- Strongest isolation boundary
- Independent backups and restore
- Per-tenant credentials
- Easier quota enforcement
- Simpler security audit

**Cons**:
- Higher operational overhead (connection pooling, provisioning)
- More complex migrations
- Resource planning for many tenants

**Use when**: Strong isolation and independent data lifecycle are priorities.

#### Option B: Shared database with enforced tenant keys
**Pros**:
- Simpler operational model
- Single backup/restore
- Easier cross-tenant platform queries
- Lower resource overhead

**Cons**:
- Requires comprehensive tenant authorization layer
- Higher risk of tenant data leakage bugs
- Shared database quotas
- Migration rollback affects all tenants

**Use when**: Operational simplicity and shared infrastructure preferred.

**Owner decision required**: Choose isolation model before Foundation phase.

### Migration and Legacy Data

**Goal**: Tag all existing production records with IDSE tenant ID, preserve financial and referential integrity, support rollback.

**Requirements**:
- Preserve all original `_id` values
- Maintain `invoice_id`, `customer_id`, `telegram_id` uniqueness
- Keep counter sequences without collision
- Link deposits ↔ purchases ↔ commissions ↔ payouts
- Maintain inventory item → product → purchase chains
- Preserve Telegram message history and bot associations

**Approach**:
1. Dry-run migration with counts and validation
2. Idempotent transforms (safe to re-run)
3. Before/after reconciliation reports
4. Explicit rollback procedure
5. Separate Development → Staging → Production gates

**Do NOT**:
- Infer tenant ownership from deployment config
- Assume ownership without explicit classification
- Migrate production secrets into runtime configuration
- Apply schema changes without backup and rollback plan

### Security Model

#### Secrets Management
- Telegram bot tokens → secret manager
- Payment provider credentials → encrypted vault
- Database credentials → environment-specific, rotated
- API keys → per-tenant, in secure store

**Never**: Production secrets in source control, config files, or Development environment.

#### Authentication & Authorization
- Platform admin: elevated privileges for tenant management
- Tenant admin: full access within tenant boundary
- Tenant user: role-based permissions within tenant
- API authentication: per-tenant API keys, rate limited

#### Audit & Compliance
- Platform audit log: tenant lifecycle, admin operations
- Tenant audit log: user actions, configuration changes, financial transactions
- Log retention policy per compliance requirements

**Owner decision required**: Audit retention, GDPR/privacy compliance approach.

### Integration Safety

#### Development Environment
- Disabled outbound integrations by default
- Sandbox credentials for payment providers
- Test Telegram bot tokens (non-production)
- No email delivery to real addresses
- Explicit production gateway flags

#### Staging Environment
- Limited integration with sandbox endpoints
- Synthetic test data
- No production secrets
- Separate database from production

#### Production Environment
- Explicit authorization gates for all destructive operations
- Circuit breakers on payment processing
- Rate limits on communications
- Rollback procedures for failed deployments

## Decisions Pending Owner Review

1. **Database isolation model**: Database-per-tenant vs. shared database with tenant keys
2. **IDSE tenant classification**: Confirm existing production data becomes IDSE first-party tenant
3. **Commercial licensing**: Subscription plans, feature tiers, quotas, billing model
4. **Source transfer workflow**: How tenants receive/own source code if licensed
5. **Analytics and privacy**: Cross-tenant aggregation rules, PII retention, consent model
6. **Payment reconciliation**: Per-tenant merchant accounts, reconciliation requirements, refund policy
7. **Custom domains**: Licensing, verification, SSL provisioning
8. **Reseller program**: Multi-tenant reseller model or tenant-private only

## Next Steps

1. **Owner review this document** — Architecture, isolation model, decisions
2. **Approve phase plan** — Foundation, tenant core, commerce, channels, commercialization
3. **Authorize Foundation phase** — Explicit go-ahead for implementation
4. **Risk acceptance** — Review and accept risk register

**No implementation begins until Owner authorization received.**
