# V2 Phase Plan — Owner Approval Gates

Status: **Discovery complete. No implementation phase is authorized by this document.**

## Phase 0 — Discovery Completion

**Status**: Complete

**Delivered evidence**:
- Clean Development repository at baseline `3a75b1cc2ab2fbe297556e098bba90d635d631a8`
- Production archive checksum and internal checksum manifest verified
- Isolated Development restore at `sellerbottel_dev`
- 46/46 collection names and 3,804/3,804 document counts reconciled
- Selected critical indexes verified
- Legacy source, data inventory, architecture, migration plan, risk register, and task graph documented
- No production system, credential, database, or outbound integration activated

**Exit**: Owner reviews discovery documents and decides V2 isolation/commercial requirements.

## Phase 1 — Foundation

**Objective**: Make V2 development safe, testable, and tenant-ready.

**Scope**:
- Environment configuration separation and secret-management approach
- CI/test baseline; dependency and secret scanning
- Tenant identity/context model and request authentication skeleton
- Tenant-aware repository/service boundaries
- Audit logging, error handling, observability baseline
- V2 schema/index migration framework
- Development safeguards: disabled outbound integrations and sandbox adapters

**Acceptance criteria**:
- No production secrets in source/runtime configuration
- Tenant context required by new tenant-owned service paths
- CI executes defined test suite and secret checks
- Audit events produced for privileged actions
- Development cannot call production provider endpoints by default

**Gate**: Owner approves tenant isolation model and Foundation scope.

## Phase 2 — Tenant Core and Platform Control Plane

**Objective**: Establish tenant lifecycle and enforce isolation.

**Scope**:
- Platform tenant registry and lifecycle (create/suspend/disable)
- Plans/licenses, quotas, provisioning state
- Platform versus tenant roles and authorization
- Tenant configuration, branding/domain model
- IDSE first-party tenant creation
- Tenant-boundary integration and security tests

**Acceptance criteria**:
- Cross-tenant reads/writes rejected by automated tests
- Platform admin operations audited
- Tenant provisioning creates selected isolation boundary
- IDSE operates as a normal tenant, not hard-coded special behavior

**Gate**: Owner approves tenant lifecycle, roles, plans/licensing requirements, and IDSE mapping.

## Phase 3 — Commerce Core

**Objective**: Deliver tenant-scoped catalog-to-fulfillment flows.

**Scope**:
- Catalog, pricing, product artwork, inventory and stock events
- Storefront/customer accounts and tenant-scoped identity
- Checkout, orders, invoices, fulfillment, post-purchase actions
- Wallet, deposits, balance adjustments, ledger/audit
- Payment adapter boundaries and sandbox reconciliation
- Data migration transform/reconciliation tooling

**Acceptance criteria**:
- Tenant-scoped catalog, checkout, and fulfillment end-to-end tests pass
- Idempotent order/payment paths covered
- Financial reconciliation report passes migration rehearsal
- Inventory cannot allocate an item across tenants
- Payment adapters are sandboxed until separately authorized

**Gate**: Owner approves financial reconciliation and migration-rehearsal result.

## Phase 4 — Channels and Operations

**Objective**: Add tenant-scoped operating channels safely.

**Scope**:
- Telegram bot identity/configuration, groups, updates, message history
- Tenant admin UI and support operations
- Broadcasts, outreach, promotion/coupon controls
- Reseller model implementation after ownership decision
- Domain/branding support
- Operational reporting, monitoring, alerting, support tooling

**Acceptance criteria**:
- Tokens stored securely and never shared between tenants
- Outbound messaging has consent/opt-out and rate controls
- Tenant admin cannot access platform or another tenant data
- Monitoring detects worker/integration failures without leaking PII

**Gate**: Owner approves communication consent, reseller model, domain/branding, and integration activation policy.

## Phase 5 — Commercialization

**Objective**: Turn tenant capability into an approved commercial offering.

**Scope**:
- Subscription/license plans, feature entitlements, quotas
- Billing/subscription events and operational workflows
- Demo/trial/lifetime plan rules
- Source transfer/ownership flow if offered
- Tenant onboarding/offboarding and data export/deletion policy
- Platform analytics/privacy implementation

**Acceptance criteria**:
- Entitlements enforced server-side
- Billing state audited and reconciliation defined
- Tenant lifecycle includes suspension, export, and deletion handling
- Privacy/consent policy implemented for applicable data flows

**Gate**: Owner approves commercial terms, transfer workflow, billing, and privacy policy.

## Phase 6 — Hardening and Release Readiness

**Objective**: Prove V2 can be released through a controlled path.

**Scope**:
- Full migration rehearsal and rollback recovery exercise
- Security review and tenant isolation testing
- Performance/load and failure recovery exercises
- Backup/restore and incident runbooks
- Documentation: operator, tenant admin, architecture, API
- Release checklist and separately authorized deployment plan

**Acceptance criteria**:
- Migration rehearsal reconciles all required data with zero unapproved discrepancies
- Restore and rollback exercises succeed
- Tenant isolation/security tests pass
- Critical external integrations have failure handling/circuit breakers
- Owner signs release-readiness checklist

**Gate**: Explicit Owner production deployment authorization.

## Cross-Phase Rules

- Every phase requires scoped tasks, tests, diff review, secret review, written results, and an approval checkpoint.
- Do not promote data or configuration without backup and rollback evidence.
- Do not reuse production credentials in any non-production environment.
- Keep external messaging/payment operations disabled until their explicit phase gate approves activation.
- Discovery evidence does not grant production deployment authority.
