# Backend Architecture Audit

**Audit Date:** 2026-10-03  
**Repository:** /opt/sellerbottel-v2/repo  
**Backend Path:** /opt/sellerbottel-v2/repo/backend  
**Total Backend LOC:** ~19,400 lines of Python

---

## Executive Summary

The backend is a **single-tenant monolithic FastAPI application** with MongoDB persistence. It implements a Telegram-first digital goods marketplace with web storefront capabilities, reseller bot white-labeling, and marketing automation. The system is **NOT multi-tenant** and has no tenant isolation mechanisms.

### Critical Findings

1. **No Multi-Tenancy** - Single shared database, no tenant isolation
2. **Single Admin Architecture** - One admin role, no RBAC
3. **Monolithic Design** - Large god objects (2,300+ LOC files)
4. **No Service Layer** - Business logic embedded in route handlers
5. **Direct Database Access** - No ORM, no repository pattern
6. **Limited Test Coverage** - 17 test files for 50+ modules

---

## 1. Technology Stack

### Core Framework
- **FastAPI** 0.110.1 (async/await)
- **Python** 3.11+ (inferred from language features)
- **Uvicorn** 0.25.0 (ASGI server)

### Database
- **MongoDB** via Motor 3.3.1 (async client)
- **PyMongo** 4.6.3 (underlying driver)
- Single database: `DB_NAME` from environment
- Collections: 30+ (products, inventory_items, purchases, deposits, bot_users, store_customers, reseller_bots, broadcasts, etc.)

### Authentication & Security
- **JWT** (PyJWT 2.14.0) - HS256 algorithm
- **bcrypt** 4.1.3 - password hashing
- **Cryptography** 50.0.1 - Fernet inventory encryption
- Cookie-based sessions (httponly, secure)

### External Integrations
- **Telegram Bot API** (webhook-based)
- **Telethon** 1.36+ (MTProto for promotional outreach)
- **SMTP** (email verification/receipts)
- **GoPay** (Indonesian QRIS payment provider)
- **AWS S3** via boto3 (optional storage backend)

### Key Dependencies
- Pydantic 2.13.5 (request/response validation)
- Pillow 12.3.0 (image processing)
- pandas 3.0.6 (data processing)
- stripe 14.4.1 (payment integration)
- google-genai 2.24.0 (AI features)

---

## 2. Architecture Overview

### Entry Point
**File:** `server.py` (258 lines)

```python
app = FastAPI()
- 19 route modules mounted
- CORS middleware
- Error handlers registered
- Background tasks: marketing, stock monitor, daily recap, 
  followup, reseller monitor, GoPay monitor, bot2 payment monitor
- Webhook setup on startup
```

### Route Modules (19 total, ~158 endpoints)

| Module | Prefix | Auth | LOC | Endpoints | Purpose |
|--------|--------|------|-----|-----------|---------|
| auth.py | /api/auth | Public | 113 | 3 | Login/logout/me |
| admin_routes.py | /api/admin | Admin | 2,260 | 56 | Products, inventory, deposits, users |
| storefront_routes.py | /api/store | JWT/Email | 876 | 23 | Customer storefront |
| reseller_routes.py | /api/admin/resellers | Admin | 321 | ~15 | Reseller bot management |
| promo_routes.py | /api/admin/promo | Admin | - | 12 | Promotional campaigns |
| broadcast_composer.py | /api/admin/broadcasts | Admin | 252 | 5 | Marketing broadcasts |
| marketing_campaigns.py | /api/admin/broadcasts/campaigns | Admin | 349 | 7 | Campaign orchestration |
| reporting.py | /api/admin/reports | Admin | 330 | 2 | Analytics/reports |
| balance_admin.py | /api/admin/wallets | Admin | - | 2 | Wallet management |
| admin_user_routes.py | /api/admin | Admin | 228 | 4 | Admin user management |

**Webhook Entry Points:**
- POST `/api/telegram/webhook` - Main bot updates (bot.py)
- POST `/api/telegram/bot2/webhook` - Secondary bot (bot2.py)
- POST `/api/telegram/reseller/{bot_id}` - Reseller bot webhooks

---

## 3. Authentication & Authorization

### Admin Authentication
**File:** `auth.py`

```python
# Single admin seeded from environment
ADMIN_EMAIL, ADMIN_PASSWORD → db.admins collection

# JWT tokens
create_access_token(user_id, email)
  - 12-hour expiry
  - Algorithm: HS256
  - Secret: JWT_SECRET from env

# Session management
- Cookie: access_token (httponly, secure, samesite=lax)
- Fallback: Authorization: Bearer <token>
```

**Authentication Flow:**
1. POST /api/auth/login → validate credentials
2. Rate limiting: 5 attempts per IP:email, 15-minute lockout
3. Return JWT + set cookie
4. Protected routes: `Depends(get_current_admin)`

### Authorization Model
**NONE** - Single admin role, no RBAC

```python
# All protected routes use identical guard
router = APIRouter(dependencies=[Depends(get_current_admin)])

# No role checks, no permissions, no scopes
# Either authenticated admin or rejected
```

### Customer Authentication (Storefront)
**Two mechanisms:**
1. **Email + OTP** - 6-digit code, 10-minute expiry
2. **JWT tokens** - After email verification, same 12-hour expiry
3. **Telegram Identity** - Link Telegram account to email account

---

## 4. Database Schema & Patterns

### Collections (30+)

| Collection | Purpose | Key Fields | Indexes |
|------------|---------|------------|---------|
| settings | Global config | _id: "main" | Primary |
| admins | Admin users | email, password_hash, role | email (unique) |
| bot_users | Telegram users | telegram_id, balance_usd, balance_idr | telegram_id (unique) |
| store_customers | Web customers | email, telegram_id, balance_* | email (unique), telegram_id (unique partial) |
| products | Catalog | name, price_usd, price_idr, active | (active, created_at) |
| inventory_items | Digital goods | product_id, status, encrypted_data | product_id + status, fingerprint |
| purchases | Orders | user_tid, customer_id, items, status, total | invoice_id (unique), customer idempotency |
| deposits | Balance top-ups | user_tid, customer_id, amount, status, currency | tx_hash (unique partial) |
| discounts | Discount rules | active, priority, conditions | (active, priority desc) |
| coupons | Coupon codes | code, discount_*, usage_limit | code (unique) |
| reseller_bots | White-label bots | owner_tid, telegram_bot_id, status | telegram_bot_id (unique) |
| gopay_payments | QRIS payments | active_payment_amount, status | amount (unique partial) |
| broadcasts | Marketing campaigns | kind, status, scheduled_at | (kind, status, scheduled_at) |

### Query Patterns

**Direct MongoDB access everywhere:**
```python
# No ORM, no repository pattern
await db.products.find_one({"_id": pid})
await db.purchases.update_one({"_id": oid}, {"$set": {...}})
await db.inventory_items.count_documents({"status": "available"})

# Aggregation pipelines for analytics
pipeline = [{"$match": {...}}, {"$group": {...}}]
await db.purchases.aggregate(pipeline).to_list()
```

**Idempotency patterns:**
```python
# Purchases: customer_id + idempotency_key (unique)
# Deposits: deposit_credit_ids array (prevent double-credit)
# Webhook updates: processed_updates collection (dedup)
```

**No database migrations** - Indexes managed in `ensure_indexes()` on startup

---

## 5. Multi-Tenancy Analysis

### **RESULT: NO MULTI-TENANCY**

**Evidence:**
1. ❌ No `tenant_id`, `org_id`, or `organization_id` in any collection
2. ❌ Single settings document (`_id: "main"`)
3. ❌ All queries unscoped: `db.products.find()` returns ALL products
4. ❌ Single admin sees all data across entire system
5. ❌ Shared inventory across all reseller bots
6. ❌ No tenant context in request handlers

**Reseller Bot Feature ≠ Multi-Tenancy:**
```python
# Reseller bots create separate Telegram bot instances
# BUT they share:
- Same product catalog (no isolation)
- Same admin dashboard (no access control)
- Same database (no partitioning)
- Only purchases tagged with reseller_bot_id for commission tracking
```

**To Add Multi-Tenancy Would Require:**
1. Tenant collection + tenant_id on every document
2. Tenant context extraction middleware
3. Query rewriting to inject tenant filters
4. Per-tenant admin authentication
5. Data migration for existing records
6. Tenant-aware indexes

---

## 6. API Endpoint Mapping

### Public Endpoints (No Auth)
```
POST   /api/auth/login
POST   /api/auth/logout
GET    /api/store/products
GET    /api/store/products/{pid}
POST   /api/store/auth/request-code
POST   /api/store/auth/verify-code
```

### Admin Endpoints (JWT Required)
```
# Dashboard & Stats
GET    /api/admin/stats
POST   /api/admin/stats/reset

# Products
GET    /api/admin/products
POST   /api/admin/products
GET    /api/admin/products/{pid}
PUT    /api/admin/products/{pid}
DELETE /api/admin/products/{pid}
POST   /api/admin/products/{pid}/toggle

# Inventory
GET    /api/admin/products/{pid}/inventory
POST   /api/admin/products/{pid}/inventory
DELETE /api/admin/products/{pid}/inventory/{item_id}
POST   /api/admin/products/{pid}/inventory/bulk

# Deposits
GET    /api/admin/deposits
POST   /api/admin/deposits/{id}/approve
POST   /api/admin/deposits/{id}/reject

# Users
GET    /api/admin/users
GET    /api/admin/users/{tid}
POST   /api/admin/users/{tid}/credit
POST   /api/admin/users/{tid}/debit

# Resellers
GET    /api/admin/resellers/settings
PUT    /api/admin/resellers/settings
GET    /api/admin/resellers/bots
GET    /api/admin/resellers/bots/{bot_id}
POST   /api/admin/resellers/bots/{bot_id}/block

# Broadcasts
GET    /api/admin/broadcasts/campaigns
POST   /api/admin/broadcasts/campaigns
PUT    /api/admin/broadcasts/campaigns/{id}
POST   /api/admin/broadcasts/campaigns/{id}/publish

# Reports
GET    /api/admin/reports/sales
GET    /api/admin/reports/inventory
```

### Webhook Endpoints (Secret Token Auth)
```
POST   /api/telegram/webhook              # Main bot (HMAC secret)
POST   /api/telegram/bot2/webhook         # Bot2 (separate secret)
POST   /api/telegram/reseller/{bot_id}    # Per-reseller webhooks
```

---

## 7. Business Logic Analysis

### Core Business Flows

#### 1. Product & Inventory Management
**Files:** `admin_routes.py`, `inventory.py`, `inventory_admin.py`

```python
# Product types
- digital: inventory-backed (encrypted records)
- service: no inventory, manual fulfillment

# Inventory modes
- table: CSV-like structured data (username:password)
- file: Binary attachments (.session files)

# Encryption
- Fernet symmetric encryption (INVENTORY_ENCRYPTION_KEY)
- Encrypted at rest in MongoDB
- Decrypted on checkout/delivery
```

#### 2. Checkout Flow
**Files:** `checkout.py` (405 LOC), `direct_checkout.py` (490 LOC)

```python
async def execute_checkout(user, cart_items, ...):
    1. Validate products (active, in stock)
    2. Reserve inventory (status: reserved)
    3. Apply discounts & coupons
    4. Deduct wallet balance (atomic $inc)
    5. Create purchase record
    6. Commit inventory (status: sold)
    7. Update cart, send notifications
    
    # Rollback on failure:
    - Release inventory reservations
    - Refund wallet (idempotency via checkout_refund_ids)
    - Mark purchase as failed
```

**Dual wallet system:**
- `bot_users` collection: Telegram bot users (telegram_id)
- `store_customers` collection: Web users (email, optional telegram_id)
- Wallet merge: when email account links Telegram, balances transfer

#### 3. Payment Processing
**Methods:**
1. **Balance** - Pre-loaded wallet (USD/IDR)
2. **QRIS** - Indonesian QR payment via GoPay provider

**GoPay Integration:**
```python
# gopay_provider.py (386 LOC)
- Browser automation (detect payment via polling merchant page)
- QR code generation from merchant QRIS string
- Amount-based payment matching (unique amounts per order)
- Background monitor: run_gopay_monitor()
```

#### 4. Reseller Bot System
**Files:** `reseller_*.py` (6 modules)

```python
# Reseller flow
1. User purchases bot subscription via main bot
2. Creates reseller_bots record (owner_tid, fees)
3. Admin activates → webhook configured
4. Reseller bot receives own updates
5. Orders tagged with reseller_bot_id
6. Commission calculated (reseller_margin field)
7. Monthly billing cycle (expires_at, renewal_pending)

# Commission model
- Wholesale reduction: products sold at lower price
- Platform fee: per-order fee
- Admin fee: subscription fee
```

#### 5. Marketing & Broadcasts
**Files:** `marketing_campaigns.py`, `broadcast_composer.py`, `central_broadcast.py`

```python
# Campaign types
- scheduled: one-time broadcast
- product_launch: auto-announce new products
- stock_alert: notify when product restocked

# Delivery
- Telegram channels (broadcast_channel_id)
- Telegram groups (broadcast_group_ids)
- Direct messages to bot users

# Image generation
- Dynamic product artwork (PIL-based rendering)
- Brand logo overlays (assets/brands/)
```

---

## 8. Security Audit

### Vulnerabilities & Concerns

#### 1. Authentication
✅ **Good:**
- bcrypt password hashing (cost factor 12)
- JWT with expiry
- httponly cookies
- Rate limiting on login

⚠️ **Concerns:**
- Single admin account (no separation of duties)
- No session revocation mechanism
- No refresh tokens (12-hour hard expiry)
- JWT secret in environment variable

#### 2. Authorization
❌ **Critical Issues:**
- No role-based access control
- All admins have full system access
- No audit logging of admin actions
- No permission granularity

#### 3. Input Validation
✅ **Good:**
- Pydantic models for all request bodies
- FastAPI automatic validation
- Email validation library (email-validator)

⚠️ **Concerns:**
- No centralized input sanitization
- HTML escaping done ad-hoc with `html.escape()`
- MongoDB injection risk (direct dict queries)

#### 4. Data Protection
✅ **Good:**
- Inventory encryption (Fernet)
- HTTPS-only cookies (configurable)
- Separate encryption for sensitive fields

⚠️ **Concerns:**
- Encryption key in environment variable (single key)
- No key rotation mechanism
- Decrypted data logged in exceptions
- No PII masking in logs

#### 5. Webhook Security
✅ **Good:**
- Secret token validation (HMAC compare_digest)
- Duplicate update detection (processed_updates collection)

⚠️ **Concerns:**
- Secrets stored in environment
- No signature verification beyond secret token
- Async task creation without error boundaries

#### 6. API Security
⚠️ **Concerns:**
- No rate limiting on API endpoints
- No request size limits
- No CSRF protection (relies on CORS + httponly cookies)
- Public storefront has no anti-bot protection

---

## 9. Technical Debt Assessment

### Critical Issues (High Priority)

#### 1. God Objects
**bot.py** - 2,301 LOC, **bot2.py** - 1,415 LOC
- Massive switch statements on update types
- Mixed concerns: routing, business logic, formatting
- Impossible to unit test in isolation

**admin_routes.py** - 2,260 LOC
- 56 endpoints in single file
- No separation of concerns
- Business logic embedded in route handlers

#### 2. No Service Layer
```python
# Current: route handler does everything
@router.post("/products")
async def create_product(...):
    # Validate
    # Transform data
    # Direct DB insert
    # Upload image to S3
    # Send notification
    # Return response
```

**Should be:**
```python
@router.post("/products")
async def create_product(...):
    return await product_service.create(data)
```

#### 3. Direct Database Access
- No repository pattern
- `db.collection` calls scattered across 50+ files
- Query logic duplicated
- No transaction management
- Difficult to test (requires real MongoDB)

#### 4. Lack of Type Safety
```python
# Frequent pattern
user = await db.bot_users.find_one(...)
balance = user.get("balance_usd", 0)  # Runtime key access

# Better: define domain models
class BotUser:
    telegram_id: int
    balance_usd: Decimal
```

#### 5. Error Handling
- Inconsistent error responses
- Generic exceptions caught and suppressed
- No structured error codes
- Client-facing errors in Indonesian (not i18n-ready)

### Medium Priority Issues

#### 6. Configuration Management
- All config in environment variables
- No validation on startup
- No secrets management integration
- Feature flags hardcoded (`PROMOTION_ENABLED`)

#### 7. Observability
- Basic logging.info() calls
- No structured logging
- No tracing/APM integration
- No metrics collection
- No health check endpoint

#### 8. Testing
- 17 test files for 50+ modules
- No integration test suite evident
- No fixtures for test data
- Tests depend on live MongoDB

#### 9. Code Organization
```
backend/
  ├── bot.py (2301 LOC) 🔴
  ├── bot2.py (1415 LOC) 🔴
  ├── admin_routes.py (2260 LOC) 🔴
  ├── storefront_routes.py (876 LOC) 🟡
  ├── 45+ other files
  └── No clear domain structure
```

Should be:
```
backend/
  ├── domain/
  │   ├── products/
  │   ├── orders/
  │   ├── users/
  ├── infrastructure/
  │   ├── database/
  │   ├── telegram/
  ├── application/
  │   ├── services/
  │   ├── use_cases/
  └── api/
      ├── routes/
      ├── middleware/
```

---

## 10. Performance Concerns

### Database
1. **No connection pooling** - Motor defaults, not tuned
2. **N+1 queries** - Inventory count queries in loops
3. **Missing indexes** - Some queries unindexed
4. **Large document fetches** - `to_list(length=None)` loads all

### Background Tasks
1. **Polling loops** - GoPay monitor polls every 15 seconds
2. **No job queue** - asyncio.create_task() for async work
3. **No backpressure** - Unlimited concurrent tasks
4. **No retry logic** - Failed tasks lost

### Image Processing
1. **Synchronous PIL operations** - Block event loop
2. **No caching** - Regenerate product artwork on every request
3. **No CDN** - Images served from application

---

## 11. Migration Path to Multi-Tenancy

### Phase 1: Foundation (4-6 weeks)
1. **Add tenant model**
   - Create `organizations` collection
   - Add `tenant_id` to all collections
   - Backfill existing data with default tenant

2. **Tenant context middleware**
   - Extract tenant from JWT claims
   - Inject into request.state.tenant
   - Validate tenant access

3. **Query layer**
   - Create repository classes
   - Automatic tenant_id injection
   - Migrate 20% of critical queries

### Phase 2: Authentication (3-4 weeks)
4. **Multi-admin support**
   - Admin → tenant association
   - Invite system for tenant admins
   - Role-based permissions

5. **Tenant isolation verification**
   - Audit all queries for tenant filtering
   - Integration tests for cross-tenant leakage
   - Security review

### Phase 3: Data Migration (2-3 weeks)
6. **Schema migration**
   - Add tenant_id to all documents
   - Create tenant-aware indexes
   - Remove global indexes

7. **Testing & validation**
   - Multi-tenant test suite
   - Load testing per tenant
   - Rollback plan

### Estimated Total: 12-16 weeks (3-4 months)

---

## 12. Recommendations

### Immediate Actions (Week 1-2)
1. ✅ Add health check endpoint (`/health`)
2. ✅ Implement structured logging
3. ✅ Add rate limiting to public APIs
4. ✅ Create admin action audit log
5. ✅ Document API with OpenAPI tags

### Short-Term (Month 1-2)
1. 🔄 Extract service layer (start with products domain)
2. 🔄 Implement repository pattern for database access
3. 🔄 Add comprehensive integration tests
4. 🔄 Break up god objects (bot.py, admin_routes.py)
5. 🔄 Add RBAC framework (roles, permissions)

### Medium-Term (Month 3-6)
1. 🎯 Implement multi-tenancy (see migration path)
2. 🎯 Add message queue (RabbitMQ/Redis) for background jobs
3. 🎯 Implement caching layer (Redis)
4. 🎯 Add observability (OpenTelemetry, metrics)
5. 🎯 Database migration framework (Alembic/custom)

### Long-Term (6+ months)
1. 🔮 Microservices extraction (inventory, payments, marketing)
2. 🔮 Event-driven architecture for cross-domain communication
3. 🔮 GraphQL API for flexible frontend queries
4. 🔮 ML-based fraud detection
5. 🔮 Real-time analytics dashboard

---

## 13. Conclusion

The backend is a **functional single-tenant monolith** with solid core business logic but significant architectural technical debt. The codebase demonstrates domain expertise (digital goods, reseller networks, Telegram integration) but lacks engineering best practices (service layer, RBAC, testing).

**Strengths:**
- ✅ Functional business flows (checkout, inventory, payments)
- ✅ Async/await throughout (good performance foundation)
- ✅ Encryption for sensitive data
- ✅ Webhook-based Telegram integration
- ✅ Reseller bot system (creative multi-instance approach)

**Critical Gaps:**
- ❌ No multi-tenancy (requires major refactor)
- ❌ Single admin, no RBAC
- ❌ God objects (2,000+ LOC files)
- ❌ No service layer or repository pattern
- ❌ Limited test coverage

**Refactoring Priority:**
1. Multi-tenancy (if product strategy requires)
2. Service layer + repository pattern
3. RBAC implementation
4. God object decomposition
5. Comprehensive test suite

**Estimated refactor effort:** 6-12 months for full modernization with multi-tenancy.
