# Phase 3 — Commerce Core API Contract [PROPOSAL]

**Status**: Proposal for Owner Review  
**Date**: 2026-10-04  
**Scope**: Tenant-scoped commerce API interface definition  
**Implementation Authorization**: NOT GRANTED — This document defines the contract only

---

## Document Purpose

This contract defines the proposed tenant-scoped REST API interface for Phase 3 Commerce Core. It specifies:

1. **API routes and HTTP methods** for catalog, inventory, checkout, orders, wallet, and customer services
2. **Required tenant context and authorization** for each endpoint
3. **Request/response schemas** informed by legacy data structure
4. **Invariant checks and validation rules** derived from Owner Decisions
5. **Isolation boundaries** to enforce tenant security

**This is a design specification, not an implementation plan.** No code will be written until Owner approves this contract and authorizes Phase 3 execution.

---

## Architectural Context

### Database Isolation Model
**Database-per-tenant** (approved in Phase 2)
- Each tenant has isolated MongoDB database: `sellerbottel_tenant_<normalized_slug>`
- Platform control plane data in `sellerbottel` (or `DB_NAME` configured)
- Tenant context required for all application-plane operations

### Tenant Context Resolution
All tenant-scoped routes require the `X-Tenant-ID` header:

```http
X-Tenant-ID: <tenant-slug>
```

**Resolution flow** (implemented in `backend/tenant_context.py`):
1. Validate tenant slug format
2. Look up tenant in platform registry
3. Verify `status == "active"`
4. Return `TenantContext` with isolated database handle

**HTTP responses**:
- `400 Bad Request` — Invalid or missing `X-Tenant-ID`
- `403 Forbidden` — Tenant not in `active` status
- `404 Not Found` — Unknown tenant slug

### Authorization Model

**Platform operations** (tenant lifecycle, cross-tenant admin):
- Role: `platform_admin`
- Dependency: `Depends(require_platform_admin)`
- Routes: `/api/v2/platform/*`

**Tenant operations** (business data within a tenant):
- Roles: `tenant_viewer`, `tenant_operator`, `tenant_admin`, `tenant_owner`
- Dependency: `Depends(require_tenant_role(tenant_id, min_role))`
- Routes: `/api/v2/tenant/*`
- Membership validated via `tenant_memberships` collection (platform DB)

**Evidence**:
- `/opt/sellerbottel-v2/repo/backend/platform_rbac.py` (lines 100-124)
- `/opt/sellerbottel-v2/repo/backend/tenant_context.py` (lines 108-130)

---

## Owner Decision Integration

### Decision 1: Global Customer Identity
**Source**: `docs/v2/OWNER_DECISIONS.md` (lines 8-28)

**Rule**: Email and Telegram ID are globally unique across all tenants.

**API Impact**:
- `store_customers.email` — UNIQUE global index (no `tenant_id`)
- `store_customers.telegram_id` — UNIQUE global index (no `tenant_id`)
- `bot_users.telegram_id` — UNIQUE global index (no `tenant_id`)
- Customers may have memberships in multiple tenants (via `tenant_memberships`)
- Customer creation returns `409 Conflict` if email/telegram_id already exists globally

**Invariant checks**:
1. Before creating customer: Check email uniqueness across platform DB collection
2. Customer profiles do NOT duplicate; shared identity links to multiple tenants via memberships
3. Tenant-scoped queries filter by membership, not by `customer.tenant_id`

### Decision 2: Per-Tenant Invoice Counters
**Source**: `docs/v2/OWNER_DECISIONS.md` (lines 32-54)

**Rule**: Each tenant has independent invoice sequence.

**API Impact**:
- Invoice format: `<tenant_id>-<counter>` (e.g., `idse-72`, `acme-1`)
- Legacy IDSE invoices (#1-71) preserved without prefix
- `purchases.invoice_id` remains globally UNIQUE for backward compatibility
- Counter stored in tenant database: `{tenant_id, counter_name: "invoice", value: N}`

**Invariant checks**:
1. Invoice generation increments tenant-specific counter atomically
2. Global uniqueness check on `invoice_id` before persist (collision = retry with new counter)
3. No cross-tenant invoice number coordination

### Decision 3: Strict Inventory Isolation
**Source**: `docs/v2/OWNER_DECISIONS.md` (lines 56-79)

**Rule**: Inventory items belong to single tenant only; no cross-tenant sharing or transfer.

**API Impact**:
- `inventory_items` require `tenant_id` field
- Unique index: `(tenant_id, product_id, fingerprint)` replaces `(product_id, fingerprint)`
- Stock queries MUST include `tenant_id` filter
- Cross-tenant inventory transfer endpoints: PROHIBITED (no API)
- Fulfillment allocates from same tenant inventory pool only

**Invariant checks**:
1. Inventory item creation validates `tenant_id` matches request context
2. Stock allocation queries scoped to `context.tenant_id`
3. Order fulfillment rejects if product belongs to different tenant
4. No API endpoints for inter-tenant inventory transfer

---

## API Route Structure

### Base Path Convention

```
Platform Control Plane:  /api/v2/platform/*
Tenant Application Plane: /api/v2/tenant/*
```

**Evidence**: 
- Platform routes: `/opt/sellerbottel-v2/repo/backend/v2_platform_routes.py` (line 21)
- Tenant routes: `/opt/sellerbottel-v2/repo/backend/server.py` (line 116)

---

## 1. Catalog Service

### Endpoints

#### `POST /api/v2/tenant/catalog/products`
**Purpose**: Create a new product in the tenant catalog  
**Authorization**: `tenant_operator` or higher  
**Tenant Context**: Required (`X-Tenant-ID`)

**Request Body**:
```json
{
  "name": "Product Name",
  "description": "Product description",
  "base_price": 50000,
  "category": "digital_code",
  "artwork_url": "https://...",
  "is_active": true
}
```

**Response** (`201 Created`):
```json
{
  "id": "<uuid>",
  "tenant_id": "acme-shop",
  "name": "Product Name",
  "base_price": 50000,
  "category": "digital_code",
  "is_active": true,
  "created_at": "2026-10-04T12:00:00Z"
}
```

**Invariants**:
- Product `tenant_id` must match resolved tenant context
- `base_price` must be non-negative integer
- Product creation audited in tenant database

**Evidence**: Legacy `products` collection structure (3,804 documents migrating with `tenant_id: "idse"`)

---

#### `GET /api/v2/tenant/catalog/products`
**Purpose**: List all products in the tenant catalog  
**Authorization**: `tenant_viewer` or higher  
**Tenant Context**: Required

**Query Parameters**:
- `category` (optional): Filter by category
- `is_active` (optional): Filter by active status
- `limit` (default: 50, max: 100)
- `offset` (default: 0)

**Response** (`200 OK`):
```json
{
  "items": [
    {
      "id": "<uuid>",
      "tenant_id": "acme-shop",
      "name": "Product Name",
      "base_price": 50000,
      "is_active": true
    }
  ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

**Invariants**:
- Query automatically scoped to `tenant_id == context.tenant_id`
- Never returns products from other tenants
- Results paginated with configurable limits

---

#### `PATCH /api/v2/tenant/catalog/products/{product_id}`
**Purpose**: Update product metadata  
**Authorization**: `tenant_operator` or higher  
**Tenant Context**: Required

**Request Body** (partial update):
```json
{
  "name": "Updated Name",
  "base_price": 55000,
  "is_active": false
}
```

**Response** (`200 OK`): Full product object

**Invariants**:
- Product must exist in tenant database
- `404 Not Found` if product belongs to different tenant
- Cannot modify `tenant_id` field (immutable)
- Update audited in tenant database

---

#### `DELETE /api/v2/tenant/catalog/products/{product_id}`
**Purpose**: Soft-delete or archive a product  
**Authorization**: `tenant_admin` or higher  
**Tenant Context**: Required

**Response** (`204 No Content`)

**Invariants**:
- Product marked `is_active: false` (soft delete) or moved to archive
- Cannot delete if active inventory items exist (constraint check)
- `409 Conflict` if product referenced in pending orders
- Deletion audited

---

## 2. Inventory Service

### Endpoints

#### `POST /api/v2/tenant/inventory/items`
**Purpose**: Add inventory items to a product  
**Authorization**: `tenant_operator` or higher  
**Tenant Context**: Required

**Request Body**:
```json
{
  "product_id": "<uuid>",
  "items": [
    {
      "data": "CODE-12345",
      "fingerprint": "sha256:abc...",
      "metadata": {}
    }
  ]
}
```

**Response** (`201 Created`):
```json
{
  "created_count": 1,
  "items": [
    {
      "id": "<uuid>",
      "tenant_id": "acme-shop",
      "product_id": "<uuid>",
      "status": "available",
      "created_at": "2026-10-04T12:00:00Z"
    }
  ]
}
```

**Invariants** (from Owner Decision 3):
1. All items inherit `tenant_id` from context
2. Unique constraint: `(tenant_id, product_id, fingerprint)` enforced
3. Product must exist in same tenant (404 if not found)
4. Duplicate fingerprint within tenant returns `409 Conflict`
5. Data encrypted at rest (per existing inventory encryption)

**Evidence**: 
- Legacy `inventory_items` collection (~500 documents)
- Encryption: `/opt/sellerbottel-v2/repo/backend/inventory.py` (encryption_status)

---

#### `GET /api/v2/tenant/inventory/items`
**Purpose**: List inventory items with filtering  
**Authorization**: `tenant_viewer` or higher  
**Tenant Context**: Required

**Query Parameters**:
- `product_id` (optional): Filter by product
- `status` (optional): `available`, `allocated`, `delivered`, `failed`
- `limit`, `offset`

**Response** (`200 OK`):
```json
{
  "items": [
    {
      "id": "<uuid>",
      "tenant_id": "acme-shop",
      "product_id": "<uuid>",
      "status": "available",
      "allocated_at": null
    }
  ],
  "total": 250,
  "limit": 50,
  "offset": 0
}
```

**Invariants**:
- Query scoped to `tenant_id == context.tenant_id`
- Sensitive `data` field excluded from list responses
- Stock counts per product computed server-side

---

#### `GET /api/v2/tenant/inventory/stock-summary`
**Purpose**: Get available stock counts per product  
**Authorization**: `tenant_viewer` or higher  
**Tenant Context**: Required

**Response** (`200 OK`):
```json
{
  "products": [
    {
      "product_id": "<uuid>",
      "product_name": "Product A",
      "available": 50,
      "allocated": 10,
      "delivered": 200,
      "failed": 2
    }
  ]
}
```

**Invariants**:
- Aggregation scoped to tenant database only
- Real-time counts from `inventory_items` collection
- No cross-tenant visibility

---

## 3. Customer Service

### Endpoints

#### `POST /api/v2/tenant/customers`
**Purpose**: Register a new customer (or link existing global customer to tenant)  
**Authorization**: `tenant_operator` or higher  
**Tenant Context**: Required

**Request Body**:
```json
{
  "email": "customer@example.com",
  "telegram_id": "123456789",
  "name": "John Doe",
  "phone": "+1234567890"
}
```

**Response** (`201 Created` or `200 OK` if exists):
```json
{
  "id": "<uuid>",
  "email": "customer@example.com",
  "telegram_id": "123456789",
  "name": "John Doe",
  "membership": {
    "tenant_id": "acme-shop",
    "role": "tenant_viewer",
    "created_at": "2026-10-04T12:00:00Z"
  }
}
```

**Invariants** (from Owner Decision 1):
1. Check if `email` OR `telegram_id` exists in **platform DB** `store_customers` collection (global)
2. If exists: Create tenant membership only (link existing customer to tenant)
3. If new: Create customer in platform DB + create tenant membership
4. Email/telegram_id globally unique enforced by platform DB indexes
5. Customer profile NOT duplicated across tenants (shared identity)

**Response codes**:
- `201 Created` — New customer created and linked to tenant
- `200 OK` — Existing customer linked to tenant
- `409 Conflict` — Customer already member of this tenant

**Evidence**:
- Owner Decision: `docs/v2/OWNER_DECISIONS.md` (lines 16-28)
- Memberships: `backend/platform_rbac.py` (lines 49-73)

---

#### `GET /api/v2/tenant/customers`
**Purpose**: List customers with membership in this tenant  
**Authorization**: `tenant_viewer` or higher  
**Tenant Context**: Required

**Query Parameters**:
- `search` (optional): Search by email or name
- `limit`, `offset`

**Response** (`200 OK`):
```json
{
  "items": [
    {
      "id": "<uuid>",
      "email": "customer@example.com",
      "name": "John Doe",
      "membership": {
        "tenant_id": "acme-shop",
        "role": "tenant_viewer",
        "created_at": "2026-10-04T10:00:00Z"
      }
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

**Invariants**:
- Join query: `store_customers` (platform DB) ⋈ `tenant_memberships` WHERE `tenant_id == context.tenant_id`
- Returns customers who are members of current tenant only
- Customer data from platform DB (global identity)
- Membership metadata from platform DB `tenant_memberships`

---

#### `GET /api/v2/tenant/customers/{customer_id}`
**Purpose**: Get customer details and purchase history  
**Authorization**: `tenant_viewer` or higher  
**Tenant Context**: Required

**Response** (`200 OK`):
```json
{
  "id": "<uuid>",
  "email": "customer@example.com",
  "name": "John Doe",
  "membership": {
    "tenant_id": "acme-shop",
    "role": "tenant_viewer"
  },
  "stats": {
    "total_orders": 5,
    "total_spent": 250000,
    "wallet_balance": 50000
  }
}
```

**Invariants**:
- Verify customer has membership in current tenant (403 if not)
- Stats computed from tenant database only (orders, wallet scoped to tenant)
- No cross-tenant data leakage

---

## 4. Order & Checkout Service

### Endpoints

#### `POST /api/v2/tenant/orders`
**Purpose**: Create a new order (checkout flow)  
**Authorization**: `tenant_operator` or higher  
**Tenant Context**: Required

**Request Body**:
```json
{
  "customer_id": "<uuid>",
  "items": [
    {
      "product_id": "<uuid>",
      "quantity": 1,
      "unit_price": 50000
    }
  ],
  "payment_method": "gopay",
  "idempotency_key": "checkout-abc123"
}
```

**Response** (`201 Created`):
```json
{
  "id": "<uuid>",
  "tenant_id": "acme-shop",
  "invoice_id": "acme-1",
  "customer_id": "<uuid>",
  "total_amount": 50000,
  "status": "pending",
  "payment_url": "https://...",
  "created_at": "2026-10-04T12:00:00Z"
}
```

**Invariants** (from Owner Decision 2):
1. Invoice ID generated: `<tenant_id>-<counter>` (e.g., `acme-1`)
2. Increment tenant-specific counter in tenant database atomically
3. Legacy IDSE invoices (#1-71) preserved without prefix
4. Global uniqueness check on `purchases.invoice_id` (collision = retry)
5. Idempotency: `(customer_id, idempotency_key)` unique within tenant
6. Customer must have membership in current tenant (403 if not)
7. All products must exist in tenant catalog (404 if not found)
8. Inventory allocation from tenant inventory pool only (Decision 3)
9. Order creation audited in tenant database

**Response codes**:
- `201 Created` — Order created successfully
- `400 Bad Request` — Invalid request data
- `403 Forbidden` — Customer not member of tenant
- `404 Not Found` — Product not found in tenant catalog
- `409 Conflict` — Duplicate idempotency key or insufficient stock
- `422 Unprocessable Entity` — Validation errors

**Evidence**:
- Invoice sequencing: `docs/v2/OWNER_DECISIONS.md` (lines 41-53)
- Legacy `purchases` collection structure (~150 documents)
- Idempotency pattern: existing code uses `customer_id + idempotency_key`

---

#### `GET /api/v2/tenant/orders`
**Purpose**: List orders in the tenant  
**Authorization**: `tenant_viewer` or higher  
**Tenant Context**: Required

**Query Parameters**:
- `customer_id` (optional): Filter by customer
- `status` (optional): `pending`, `paid`, `processing`, `fulfilled`, `failed`
- `limit`, `offset`

**Response** (`200 OK`):
```json
{
  "items": [
    {
      "id": "<uuid>",
      "tenant_id": "acme-shop",
      "invoice_id": "acme-1",
      "customer_id": "<uuid>",
      "total_amount": 50000,
      "status": "fulfilled",
      "created_at": "2026-10-04T12:00:00Z"
    }
  ],
  "total": 75,
  "limit": 50,
  "offset": 0
}
```

**Invariants**:
- Query scoped to `tenant_id == context.tenant_id` (tenant database)
- Never returns orders from other tenants
- Customer filter validates customer has tenant membership

---

#### `GET /api/v2/tenant/orders/{order_id}`
**Purpose**: Get detailed order information  
**Authorization**: `tenant_viewer` or higher  
**Tenant Context**: Required

**Response** (`200 OK`):
```json
{
  "id": "<uuid>",
  "tenant_id": "acme-shop",
  "invoice_id": "acme-1",
  "customer_id": "<uuid>",
  "items": [
    {
      "product_id": "<uuid>",
      "product_name": "Product A",
      "quantity": 1,
      "unit_price": 50000
    }
  ],
  "total_amount": 50000,
  "status": "fulfilled",
  "fulfillment": {
    "fulfilled_at": "2026-10-04T12:05:00Z",
    "inventory_items": ["<uuid>"]
  },
  "created_at": "2026-10-04T12:00:00Z"
}
```

**Invariants**:
- Order must exist in tenant database (404 if not found)
- Inventory items belong to same tenant (Decision 3)
- Fulfillment data includes allocated item IDs

---

#### `POST /api/v2/tenant/orders/{order_id}/fulfill`
**Purpose**: Mark order as fulfilled and allocate inventory  
**Authorization**: `tenant_operator` or higher  
**Tenant Context**: Required

**Request Body**:
```json
{
  "force": false
}
```

**Response** (`200 OK`):
```json
{
  "order_id": "<uuid>",
  "status": "fulfilled",
  "allocated_items": [
    {
      "product_id": "<uuid>",
      "inventory_item_id": "<uuid>",
      "data": "CODE-12345"
    }
  ],
  "fulfilled_at": "2026-10-04T12:05:00Z"
}
```

**Invariants** (from Owner Decision 3):
1. Order must have `status: "paid"` (409 if not paid)
2. Allocate inventory items from tenant database only
3. Inventory items must belong to same tenant (no cross-tenant allocation)
4. Insufficient stock returns `409 Conflict`
5. Allocated items marked `status: "allocated"` with `allocated_at` timestamp
6. Fulfillment idempotent (re-running returns same allocation)
7. Fulfillment audited in tenant database

---

## 5. Wallet & Ledger Service

### Endpoints

#### `POST /api/v2/tenant/wallet/deposits`
**Purpose**: Record a customer deposit (top-up)  
**Authorization**: `tenant_operator` or higher  
**Tenant Context**: Required

**Request Body**:
```json
{
  "customer_id": "<uuid>",
  "amount": 100000,
  "payment_method": "gopay",
  "provider_reference": "gopay-txn-12345"
}
```

**Response** (`201 Created`):
```json
{
  "id": "<uuid>",
  "tenant_id": "acme-shop",
  "customer_id": "<uuid>",
  "amount": 100000,
  "status": "completed",
  "balance_after": 150000,
  "created_at": "2026-10-04T12:00:00Z"
}
```

**Invariants**:
1. Deposit `tenant_id` matches context
2. Customer must have membership in current tenant (403 if not)
3. `amount` must be positive integer
4. Wallet balance updated atomically (transaction)
5. Balance ledger entry created for audit trail
6. Deposit reconciled with payment provider reference
7. Duplicate `provider_reference` within tenant rejected (409)

**Evidence**: Legacy `deposits` collection (~100 documents migrating with `tenant_id: "idse"`)

---

#### `GET /api/v2/tenant/wallet/balance/{customer_id}`
**Purpose**: Get customer wallet balance  
**Authorization**: `tenant_viewer` or higher  
**Tenant Context**: Required

**Response** (`200 OK`):
```json
{
  "customer_id": "<uuid>",
  "tenant_id": "acme-shop",
  "balance": 150000,
  "last_updated": "2026-10-04T12:00:00Z"
}
```

**Invariants**:
- Customer must have membership in current tenant (403 if not)
- Balance scoped to tenant (no cross-tenant balance)
- Balance computed from `deposits` and `purchases` in tenant database

---

#### `GET /api/v2/tenant/wallet/ledger/{customer_id}`
**Purpose**: Get customer transaction history  
**Authorization**: `tenant_viewer` or higher  
**Tenant Context**: Required

**Query Parameters**:
- `limit`, `offset`
- `type` (optional): `deposit`, `purchase`, `adjustment`

**Response** (`200 OK`):
```json
{
  "customer_id": "<uuid>",
  "tenant_id": "acme-shop",
  "transactions": [
    {
      "id": "<uuid>",
      "type": "deposit",
      "amount": 100000,
      "balance_after": 150000,
      "description": "GoPay deposit",
      "created_at": "2026-10-04T12:00:00Z"
    }
  ],
  "total": 25,
  "limit": 50,
  "offset": 0
}
```

**Invariants**:
- Customer must have membership in current tenant
- Ledger entries scoped to tenant database
- Chronological ordering (newest first)
- Immutable audit trail (no deletions)

---

## 6. Payment Provider Integration

### Endpoints

#### `POST /api/v2/tenant/payments/gopay/initiate`
**Purpose**: Initiate GoPay payment for order  
**Authorization**: `tenant_operator` or higher  
**Tenant Context**: Required

**Request Body**:
```json
{
  "order_id": "<uuid>",
  "amount": 50000,
  "callback_url": "https://..."
}
```

**Response** (`200 OK`):
```json
{
  "payment_id": "<uuid>",
  "provider": "gopay",
  "payment_url": "https://gopay.co.id/...",
  "qr_code": "data:image/png;base64,...",
  "expires_at": "2026-10-04T12:15:00Z"
}
```

**Invariants**:
1. Order must exist in tenant database (404 if not found)
2. Order amount matches payment amount (validation)
3. Payment record created in tenant database with `tenant_id`
4. Sandbox credentials used in Development (never production)
5. Payment reconciliation per-tenant (no cross-tenant merchant account)
6. Payment adapter sandboxed until separately authorized (Phase 1 requirement)

**Evidence**:
- Legacy `gopay_payments` collection
- Sandbox requirement: `docs/v2/PHASE_1_FOUNDATION_CHECKLIST.md` (lines 33-34)

---

#### `POST /api/v2/tenant/payments/webhooks/gopay`
**Purpose**: Handle GoPay payment callback  
**Authorization**: Public (signature validated)  
**Tenant Context**: Derived from payment record

**Request Body**: (GoPay webhook payload)

**Response** (`200 OK`): Acknowledgment

**Invariants**:
1. Webhook signature validated (HMAC)
2. Payment record looked up by `provider_reference`
3. Tenant ID derived from payment record
4. Order status updated in tenant database
5. Idempotent (duplicate webhooks ignored)
6. Webhook processing audited

---

## Authorization Matrix

| Endpoint Group | Viewer | Operator | Admin | Owner | Platform Admin |
|---|---|---|---|---|---|
| **Catalog** |  |  |  |  |  |
| List products | ✅ | ✅ | ✅ | ✅ | ❌ |
| Create product | ❌ | ✅ | ✅ | ✅ | ❌ |
| Update product | ❌ | ✅ | ✅ | ✅ | ❌ |
| Delete product | ❌ | ❌ | ✅ | ✅ | ❌ |
| **Inventory** |  |  |  |  |  |
| List items | ✅ | ✅ | ✅ | ✅ | ❌ |
| Add items | ❌ | ✅ | ✅ | ✅ | ❌ |
| Stock summary | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Customers** |  |  |  |  |  |
| List customers | ✅ | ✅ | ✅ | ✅ | ❌ |
| Create customer | ❌ | ✅ | ✅ | ✅ | ❌ |
| View customer | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Orders** |  |  |  |  |  |
| List orders | ✅ | ✅ | ✅ | ✅ | ❌ |
| Create order | ❌ | ✅ | ✅ | ✅ | ❌ |
| View order | ✅ | ✅ | ✅ | ✅ | ❌ |
| Fulfill order | ❌ | ✅ | ✅ | ✅ | ❌ |
| **Wallet** |  |  |  |  |  |
| View balance | ✅ | ✅ | ✅ | ✅ | ❌ |
| Record deposit | ❌ | ✅ | ✅ | ✅ | ❌ |
| View ledger | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Payments** |  |  |  |  |  |
| Initiate payment | ❌ | ✅ | ✅ | ✅ | ❌ |
| Webhook (public) | N/A | N/A | N/A | N/A | N/A |

**Platform Admin** has no access to tenant business data (strong isolation boundary).

**Evidence**: 
- Role hierarchy: `backend/platform_rbac.py` (lines 13-19)
- Tenant membership: `backend/platform_rbac.py` (lines 100-124)

---

## Tenant Isolation Invariants

### Database Boundary
1. ✅ All tenant queries execute against tenant database handle (`context.database`)
2. ✅ Platform control-plane queries execute against platform database (`db`)
3. ✅ No query spans multiple tenant databases
4. ✅ Database handle derived from validated `TenantContext` only

### Data Scoping
1. ✅ Every tenant-owned record has `tenant_id` field matching context
2. ✅ All queries include `tenant_id` filter (automatic via repository layer)
3. ✅ Cross-tenant reads rejected at query time (404 Not Found)
4. ✅ Cross-tenant writes rejected at validation time (403 Forbidden)

### Global Entities (Exception to Tenant Scoping)
Per Owner Decision 1, these entities are globally unique:
- `store_customers.email` (platform DB, global index)
- `store_customers.telegram_id` (platform DB, global index)
- `bot_users.telegram_id` (platform DB, global index)
- `tenant_memberships` (platform DB, links customers to tenants)

### Authorization Boundary
1. ✅ Tenant membership validated before tenant data access
2. ✅ Role hierarchy enforced: `viewer < operator < admin < owner`
3. ✅ Platform admin cannot access tenant business data directly
4. ✅ Tenant users cannot access platform control plane

### Audit Boundary
1. ✅ Tenant operations audited in tenant database
2. ✅ Platform operations audited in platform database
3. ✅ Audit events include `tenant_id` or `platform: "control-plane"` scope
4. ✅ Sensitive metadata redacted before audit persistence

**Evidence**:
- Tenant scoping: `docs/v2/V2_ARCHITECTURE.md` (lines 21-26)
- Global identity: `docs/v2/OWNER_DECISIONS.md` (lines 24-28)
- Audit sanitization: `backend/audit_events.py` (lines 13-29)

---

## Migration Compatibility

### Legacy Data Preservation

**IDSE Tenant** (first-party migration):
- Tenant slug: `idse` (or owner-selected)
- Database: `sellerbottel_tenant_idse`
- All 3,804 legacy documents tagged with `tenant_id: "idse"`

**Preserved Fields**:
- `_id` (all collections) — Original MongoDB ObjectIDs unchanged
- `invoice_id` (purchases) — Legacy invoices #1-71 preserved without prefix
- `customer_id`, `product_id`, `telegram_id` — Referential integrity maintained
- Financial data — All amounts, timestamps, statuses preserved

**Schema Changes**:
| Collection | Index Change | `tenant_id` Required? |
|---|---|---|
| `store_customers` | Email UNIQUE (global, no change) | NO (global identity) |
| `bot_users` | Telegram ID UNIQUE (global, no change) | NO (global identity) |
| `inventory_items` | `(tenant_id, product_id, fingerprint)` UNIQUE | YES |
| `products` | Add `tenant_id` index | YES |
| `purchases` | `invoice_id` UNIQUE (global preserved) | YES |
| `deposits` | Add `tenant_id` index | YES |
| `gopay_payments` | Add `tenant_id` index | YES |
| `counters` | Add `tenant_id` field | YES (per-tenant counter) |

**Evidence**:
- Migration plan: `docs/v2/DATA_MIGRATION_PLAN.md` (lines 58-89)
- IDSE tenant: `docs/v2/PHASE_2_TENANT_CORE_REPORT.md` (lines 228-252)
- Owner decisions: `docs/v2/OWNER_DECISIONS.md` (lines 82-121)

---

## Implementation Evidence from Codebase

### Phase 2 Foundation (Completed)
- ✅ Tenant context resolution: `backend/tenant_context.py`
- ✅ Platform RBAC: `backend/platform_rbac.py`
- ✅ Tenant database naming: `backend/tenant_db.py`
- ✅ Platform routes: `backend/v2_platform_routes.py`
- ✅ Tenant routes skeleton: `backend/v2_tenant_routes.py`
- ✅ Audit events: `backend/audit_events.py`
- ✅ 73 automated tests passing: `backend/tests/test_*.py`

### Legacy Data Structures (Reference)
- Products: `backend/product_catalog.py`
- Inventory: `backend/inventory.py`
- Checkout: `backend/checkout.py`
- Orders: `backend/direct_checkout.py`
- Deposits: `backend/balance_admin.py`
- Payment provider: `backend/gopay_provider.py`

### Configuration (Safety)
- Environment validation: `backend/config.py`
- Database client: `backend/db.py`
- Authentication: `backend/auth.py`
- Server initialization: `backend/server.py`

---

## Acceptance Criteria for Phase 3

This API contract is considered accepted when:

1. ✅ **Owner Review**: Owner confirms API interface aligns with business requirements
2. ✅ **Decision Integration**: All Owner Decisions correctly reflected in invariants
3. ✅ **Isolation Boundaries**: Tenant scoping rules validated against security requirements
4. ✅ **Migration Compatibility**: Legacy data preservation strategy approved
5. ✅ **Authorization Model**: Role matrix approved for tenant operations

Once accepted, Phase 3 implementation may begin with:
- Repository layer implementing tenant-scoped queries
- Service layer enforcing invariant checks
- HTTP routes implementing this contract
- Test suite validating isolation boundaries
- Migration tooling for IDSE tenant data

---

## Open Questions for Owner Review

1. **Invoice Format**: Confirm `<tenant_id>-<counter>` format acceptable (e.g., `acme-1`)?
2. **Customer Onboarding**: Should customers self-register, or operator-only creation?
3. **Wallet Adjustments**: Manual balance adjustments allowed? Requires `tenant_admin` role?
4. **Payment Reconciliation**: Per-tenant merchant accounts or shared with tagging?
5. **Stock Alerts**: Low-stock notifications via email/Telegram? Threshold configurable per product?
6. **Refund Policy**: Refund API endpoints needed? Impact on wallet and order status?
7. **Audit Retention**: How long should tenant audit logs be retained?
8. **API Rate Limits**: Per-tenant rate limits? Global platform limits?

---

## Implementation Authorization

**Status**: ❌ NOT AUTHORIZED

This document defines the proposed API contract only. No implementation code will be written until:

1. Owner reviews and approves this contract
2. Owner answers open questions above
3. Owner explicitly authorizes Phase 3 implementation
4. Phase 3 task breakdown and test plan prepared

**Next Steps**:
1. Owner review meeting scheduled
2. Open questions answered
3. Contract amendments (if needed)
4. Owner sign-off recorded
5. Phase 3 implementation authorized

---

**Document Version**: 1.0  
**Last Updated**: 2026-10-04  
**Prepared By**: Hermes Agent (Subagent)  
**Review Required By**: Owner
