# Legacy Inventory System Architecture Audit

**Audit Date**: 2026-10-03  
**Repository**: `/opt/sellerbottel-v2/repo`  
**Codebase**: Python (FastAPI backend), MongoDB database  

---

## Executive Summary

The legacy system implements a **digital goods inventory management platform** with Telegram bot integration. Core architecture centers on encrypted, schema-flexible inventory tracking with automatic stock monitoring and multi-channel catalog delivery.

**Key Stats** (from backup):
- 37 products
- 1,080 inventory items
- 42 stock events
- Primary collections: `products`, `inventory_items`, `stock_events`, `counters`

---

## 1. Core Architecture Components

### 1.1 Database Schema (MongoDB)

**Collections**:
- **products**: Product catalog with pricing, metadata, and inventory config
- **inventory_items**: Encrypted digital goods records with lifecycle tracking
- **stock_events**: Restock/sold-out notification log
- **counters**: Invoice ID sequence generators
- **bot_users**: Telegram customer accounts and balances
- **purchases**: Order history with item allocation tracking
- **discounts**, **promo_coupons**: Pricing rules
- **broadcasts**, **marketing_campaigns**: Notification delivery

**Index Strategy** (`backend/db.py`):
```python
# Unique fingerprint per product prevents duplicate inventory
inventory_items: [(product_id, fingerprint), unique=True]

# Fast status queries for stock checks
inventory_items: [(product_id, status)]

# Marketing allocation guard
inventory_items: [marketing.event_id, unique=True, partial]
```

### 1.2 Product → Inventory Relationship

**Product Document Structure**:
```python
{
    "_id": "uuid",
    "product_kind": "digital" | "service",  # Service products have no inventory
    "delivery_type": "inventory" | "service" | "link" | "file",
    "inventory_enabled": True,
    "inventory_schema": ["email", "password", "recovery"],  # Flexible per product
    "inventory_mode": "table" | "telegram_session",  # Table=CSV/XLSX, session=.session files
    "stock_mode": "auto" | "manual",  # Auto counts available, manual caps display
    "manual_stock": 100,  # Optional display cap
    "catalog_name": "ChatGPT",  # Groups products in bot UI
}
```

**Inventory Item Document Structure**:
```python
{
    "_id": "uuid",
    "product_id": "uuid",  # FK to products
    "fingerprint": "sha256(canonical_json)",  # Deduplication key
    "secret": "fernet_encrypted_base64",  # Encrypted payload
    "status": "available" | "reserved" | "sold" | "marketing_allocated",
    "reservation_id": "order:uuid" | "qris:uuid" | None,
    "order_id": "uuid" | None,
    "user_tid": 123456789,  # Telegram ID of buyer
    "customer_id": "uuid",  # Web storefront customer
    "created_at": "2026-10-03T19:00:00Z",
    "reserved_at": "2026-10-03T19:05:00Z",
    "sold_at": "2026-10-03T19:06:00Z",
    "marketing": {  # For marketing_allocated status
        "event_id": "uuid",
        "campaign_id": "marketing:admin:request_id",
        "allocated_at": "2026-10-03T18:00:00Z"
    },
    "marketing_audit": [  # Stock event receipts for marketing allocations
        {
            "_id": "marketing:allocate:event_id",
            "event_type": "OWNER_MARKETING_ALLOCATION",
            "quantity": -1,
            "product_id": "uuid",
            "campaign_id": "marketing:admin:request_id",
            "status": "recorded",
            "created_at": "2026-10-03T18:00:00Z"
        }
    ]
}
```

**Encryption** (`backend/inventory.py`):
- **Key**: `INVENTORY_ENCRYPTION_KEY` environment variable (Fernet key)
- **Algorithm**: Fernet (AES-128-CBC + HMAC-SHA256)
- **Payload format**: JSON `{"field": "value"}` or legacy `{"value": "raw_string"}`
- **Key rotation**: Not supported (would require re-encryption of all items)

**Encrypted Payload Examples**:
```json
// Table mode (standard)
{"email": "user@example.com", "password": "secret123", "recovery": "backup@example.com"}

// Telegram session mode
{
    "Session File": "account.session",
    "__file_name": "account.session",
    "__file_data_b64": "base64_encoded_session_bytes"
}
```

---

## 2. Inventory Lifecycle & Stock Tracking

### 2.1 State Machine

```
┌──────────┐  reserve_items()  ┌──────────┐  commit_items()  ┌──────┐
│available │ ────────────────> │ reserved │ ───────────────> │ sold │
└──────────┘                   └──────────┘                  └──────┘
     ^                               │
     │                               │ release_items()
     └───────────────────────────────┘

┌──────────┐  marketing_campaigns.allocate()  ┌──────────────────────┐
│available │ ──────────────────────────────> │marketing_allocated   │
└──────────┘                                  └──────────────────────┘
```

**Core Operations** (`backend/inventory.py`):

1. **reserve_items(product_id, quantity, reservation_id)**
   - Atomically moves `quantity` items from `available` → `reserved`
   - Sets `reservation_id` for tracking
   - Rolls back entire reservation if quantity unavailable
   - Used by: checkout flow, QRIS payment creation

2. **commit_items(reservation_id, order_id, user_tid, customer_id)**
   - Moves `reserved` items to `sold` status
   - Records final buyer and order
   - Triggered after successful payment

3. **release_items(reservation_id)**
   - Returns `reserved` items to `available`
   - Called on: checkout failure, QRIS expiry, payment cancellation
   - Triggers stock_monitor scan for restock notifications

4. **available_count(product_id)**
   - Returns count of `status="available"` items
   - Used by stock display, checkout validation

### 2.2 Stock Calculation Logic

**Effective Stock** (`backend/admin_routes.py:_effective_admin_stock`):
```python
def _effective_admin_stock(product, inventory_stock, marketing):
    if product_kind != "digital":
        return None  # Service products have unlimited "stock"
    
    if stock_mode == "manual":
        # Admin-set cap minus marketing allocations
        return min(inventory_stock, max(0, manual_stock - marketing))
    
    return inventory_stock  # Auto mode shows actual available count
```

**Stock Display** (`backend/checkout.py:stock_for`):
- Returns `None` for unlimited/service products
- Returns actual `available` count for auto mode
- Respects manual cap for admin-controlled display

### 2.3 Reservation Pattern

**Reservation IDs** encode checkout context:
- `order:{uuid}` – Standard bot checkout
- `qris:{uuid}` – QRIS payment flow
- `bot2:{uuid}` – Reseller bot checkout

**Timeout Handling**:
- QRIS orders: Auto-release after `gopay_qr_timeout_minutes` (default 5 min)
- No timeout for standard balance checkouts (atomic payment)
- Background worker (`backend/direct_checkout.py:_expire_qris_orders`) monitors expiry

---

## 3. Stock Monitoring & Restock Logic

### 3.1 Zero-Crossing Detection

**Stock Monitor** (`backend/stock_monitor.py`):
```python
async def scan_stock(product_id=None):
    # Tracks last known availability state per product
    for product in active_products:
        current_stock = await stock_for(product)
        previous_available = product.get("stock_notice_available")
        
        if previous_available != (current_stock > 0):
            # Zero-crossing detected: emit stock event
            event_type = "restocked" if current_stock > 0 else "sold_out"
            await db.stock_events.insert_one({
                "event_type": event_type,
                "from_count": previous_count,
                "to_count": current_stock,
                "targets": configured_broadcast_chats,
                "status": "pending"
            })
```

**Trigger Points**:
- `schedule_stock_scan(product_id)` called after:
  - Inventory import (`add_records`)
  - Item release (`release_items`)
  - Item deletion (admin action)
- Periodic background scan every 30 seconds

**Event Delivery** (`deliver_pending`):
- Generates product image with stock status
- Sends to configured broadcast channels
- Tracks delivery per chat to avoid duplicates
- Retries failed deliveries on next scan

### 3.2 Restock Requests

**Bot2 Restock Tracking** (`backend/bot2.py`):
```python
# Users can subscribe to restock notifications per product
bot2_restock_requests: {
    "user_tid": 123456789,
    "product_id": "uuid",
    "created_at": "2026-10-03T19:00:00Z"
}
# Unique index prevents duplicate subscriptions
```

**Notification Flow**:
1. User clicks "🔔 Notif Restok" button in product detail
2. Record created in `bot2_restock_requests`
3. Stock monitor detects restock event
4. Targeted notification sent to subscribed users

---

## 4. Catalog Structure

### 4.1 Catalog Grouping

**Dynamic Classification** (`backend/product_catalog.py`):
```python
def catalog_name(product):
    # Priority 1: Admin explicit assignment
    if product.get("catalog_name"):
        return product["catalog_name"]
    
    # Priority 2: Pattern matching on product name
    patterns = {
        r"\bclaude\b": "Claude Pro",
        r"\bchat\s*gpt\b": "ChatGPT",
        r"\baws\b": "AWS",
        r"\btelegram\b": "Telegram",
        r"\bgmail\b": "Gmail",
        # ... more patterns
    }
    
    # Priority 3: Default fallback
    if product_kind == "service":
        return "Jasa Payment"
    return "Produk Lainnya"
```

**Catalog Token**: SHA256 hash (16 chars) of normalized catalog name
- Used for stable callback IDs in bot navigation
- Independent of product count or name length

### 4.2 Catalog Navigation

**Pagination** (`catalog_slice`):
- Default page size: 8 products
- Two-level hierarchy: catalog list → product list
- Sorted by: catalog name (alpha), then product name (natural sort with numbers)

**Bot Display** (`backend/bot.py:show_products`):
```
📚 Katalog produk
Pilih katalog untuk melihat varian, harga, dan stok.

[ChatGPT · 3 pilihan]
[Claude Pro · 2 pilihan]
[Telegram · 5 pilihan]
[Produk Lainnya · 12 pilihan]

Halaman 1/1
[🔄 Perbarui stok] [🏠 Menu Utama]
```

---

## 5. SKU & Serial Handling for Digital Goods

### 5.1 Schema-Flexible Design

**No Traditional SKU**: System uses **content fingerprint** instead of SKU
- Fingerprint = SHA256(canonical JSON of all fields)
- Prevents duplicate inventory even with flexible schemas
- Unique per product (same data allowed across products)

**Schema Per Product**:
```python
# Product A: Email accounts
inventory_schema = ["email", "password", "recovery"]

# Product B: License keys
inventory_schema = ["license_key", "activation_code"]

# Product C: Telegram sessions
inventory_schema = ["Session File"]  # Special mode
```

**Schema Enforcement**:
- Schema locked after first inventory import
- Cannot change schema while items exist (prevents orphaned data)
- Admin can set schema manually or auto-detect from first upload

### 5.2 Inventory Input Formats

**Table Mode** (`backend/admin_routes.py:_parse_inventory_input`):
- **XLSX**: Header row + data rows, multiple sheets supported
- **CSV**: Auto-detects delimiter (`,` or `|`)
- **TXT**: Pipe-delimited (`|`) format
- **Manual entry**: Web form input for single items

**Session Mode** (Telegram accounts):
- Upload raw `.session` files (Telethon/Pyrogram format)
- File stored as base64 in encrypted payload
- Filename preserved for buyer delivery
- Max 10MB per file

**Validation Flow**:
```
Upload → Parse → Normalize → Fingerprint → Check Duplicates → Encrypt → Store
```

### 5.3 Deduplication Strategy

**Normalization** (`inventory.py:normalize_record`):
```python
def normalize_record(record, schema):
    # 1. Trim whitespace
    # 2. Convert float integers to int (1.0 → 1)
    # 3. Stringify all values
    # 4. Sort keys (canonical order)
    # 5. Generate SHA256 fingerprint
    
    canonical = json.dumps(clean, sort_keys=True, separators=(',', ':'))
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
```

**Duplicate Detection**:
- Pre-insert: Check against existing fingerprints
- Race condition: Unique index catches concurrent inserts
- Skipped duplicates returned in validation response

---

## 6. Checkout & Allocation Flow

### 6.1 Two-Phase Checkout

**Phase 1: Reservation** (`backend/checkout.py:execute_checkout`):
```python
1. Validate cart items (active, stock available)
2. Calculate pricing (with discounts/coupons)
3. Reserve inventory (reserve_items) or decrement stock
4. Debit user balance (atomic update with balance check)
5. Mark order as "paid"
```

**Phase 2: Commit**:
```python
6. Commit reserved items to sold status
7. Clear cart (or preserve with qty adjustment)
8. Trigger delivery (bot message, email, etc.)
```

**Rollback on Failure**:
- Release reservations
- Refund balance (idempotency via `checkout_refund_ids`)
- Mark order as "failed"

### 6.2 Multi-Product Allocation

**Mixed Product Types** supported:
- Inventory products (encrypted records)
- Stock-tracked products (simple counter)
- Service products (no allocation needed)

**Allocation Record** (per checkout):
```python
allocations = [
    {"kind": "inventory", "product_id": "uuid", "items": [...]},
    {"kind": "stock", "product_id": "uuid", "qty": 5},
]
```

### 6.3 QRIS Payment Integration

**Direct Checkout** (`backend/direct_checkout.py`):
- Reserves inventory before QR generation
- Locks stock for `gopay_qr_timeout_minutes`
- Background worker auto-releases expired orders
- Payment verification commits allocation

**Race Condition Prevention**:
- Unique index on `active_payment_amount` prevents amount reuse
- Reservation guards against double-allocation

---

## 7. Marketing & Campaign Allocation

### 7.1 Marketing Status

**Special Status**: `marketing_allocated`
- Removes item from customer-facing stock
- Reserved for broadcast campaigns
- Tracked separately in admin stock displays

**Allocation Flow** (`backend/marketing_campaigns.py:allocate`):
```python
1. Find eligible products (has inventory, meets minimum qty)
2. Atomically move one available item to marketing_allocated
3. Record stock event receipt in marketing_audit array
4. Create stock_events record for ledger
5. Use item for broadcast message (with delivery tracking)
```

**Stock Event as Ledger**:
```python
# Embedded in inventory_item.marketing_audit
{
    "_id": "marketing:allocate:event_id",
    "event_type": "OWNER_MARKETING_ALLOCATION",
    "quantity": -1,  # Deduction
    "product_id": "uuid",
    "campaign_id": "marketing:admin:request_id",
    "status": "recorded"
}

# Also stored in stock_events collection
await db.stock_events.update_one(
    {"_id": receipt["_id"]},
    {"$setOnInsert": receipt},
    upsert=True
)
```

### 7.2 Campaign Types

**Persistent Campaigns** (`broadcasts` collection):
- `kind: "marketing_campaign"`
- Pre-allocates N items from eligible products
- Delivers one item per scheduled interval (randomized delay)
- Tracks sent/pending status per event

**Stock Notifications** (`stock_events` collection):
- Automatic zero-crossing announcements
- No item allocation needed
- Broadcasts to configured channels

---

## 8. Critical Code Paths

### 8.1 Inventory Import

**File**: `backend/admin_routes.py`  
**Endpoints**:
- `POST /api/admin/products/{pid}/inventory/validate` – Preview before import
- `POST /api/admin/products/{pid}/inventory/import` – Commit to database

**Flow**:
1. Parse file (XLSX/CSV/TXT/session)
2. Extract schema from header row
3. Normalize records + generate fingerprints
4. Query existing fingerprints for duplicates
5. Encrypt unique records with Fernet
6. Bulk insert with `ordered=False` (continues on duplicates)
7. Update product schema if first import
8. Trigger stock monitor scan

**Error Handling**:
- Missing encryption key → HTTP 503
- Invalid key → HTTP 503
- Key mismatch → HTTP 500 (data unreadable)
- Duplicate records → Skipped, returned in response
- Write errors → Partial insert logged, returns inserted count

### 8.2 Checkout Execution

**File**: `backend/checkout.py:execute_checkout`  
**Critical Sections**:

1. **Stock Validation**:
```python
stock = await stock_for(product)
if stock is not None and stock < qty:
    return {"ok": False, "error": "stock", "product": product}
```

2. **Reservation**:
```python
reserved = await reserve_items(product_id, qty, reservation_id)
if len(reserved) != qty:
    await release_items(reservation_id)
    return {"ok": False, "error": "stock"}
```

3. **Balance Debit** (atomic):
```python
result = await wallet_collection.update_one(
    {**wallet_query, field: {"$gte": total}, "frozen": {"$ne": True}},
    {"$inc": {field: -total}, "$set": {"cart": []}},
)
if result.modified_count != 1:
    return await _fail_checkout(...)  # Rollback all
```

4. **Commit**:
```python
await commit_items(reservation_id, order_id, user_tid, customer_id)
```

### 8.3 Stock Monitor

**File**: `backend/stock_monitor.py`  
**Background Worker**: `run_stock_monitor(stop_event)`

**Scan Logic**:
```python
async def scan_stock(product_id=None):
    for product in active_inventory_products:
        stock = await stock_for(product)
        previous = product.get("stock_notice_available")
        
        if previous is None:
            # Initialize tracking
            await db.products.update_one(
                {"_id": product_id},
                {"$set": {"stock_notice_available": stock > 0}}
            )
        elif previous != (stock > 0):
            # Zero-crossing detected
            await db.stock_events.insert_one({...})
```

**Delivery Worker**: `deliver_pending()`
- Queries pending stock_events
- Generates product image
- Sends to broadcast targets
- Retries failed sends on next cycle

---

## 9. Data Integrity Mechanisms

### 9.1 Unique Constraints

**Inventory Deduplication**:
```python
# Unique per product
inventory_items: [(product_id, fingerprint), unique=True]

# Prevents marketing double-allocation
inventory_items: [marketing.event_id, unique=True, partial]
```

**Order Idempotency**:
```python
# Storefront checkout idempotency
purchases: [(customer_id, idempotency_key), unique=True, partial]

# Invoice numbering
purchases: [invoice_id, unique=True, sparse]
```

### 9.2 Atomic Operations

**Stock Reservation**:
```python
item = await db.inventory_items.find_one_and_update(
    {"product_id": product_id, "status": "available"},
    {"$set": {"status": "reserved", "reservation_id": rid}},
    sort=[("_id", 1)]  # FIFO
)
```

**Balance Debit**:
```python
result = await db.bot_users.update_one(
    {"telegram_id": tid, "balance_idr": {"$gte": total}, "frozen": {"$ne": True}},
    {"$inc": {"balance_idr": -total}}
)
# Success if modified_count == 1
```

### 9.3 Rollback Idempotency

**Refund Tracking**:
```python
await wallet_collection.update_one(
    {**wallet_query, "checkout_refund_ids": {"$ne": order_id}},
    {
        "$inc": {field: total},
        "$addToSet": {"checkout_refund_ids": order_id}
    }
)
# Array prevents double-refund on retry
```

---

## 10. Key Findings & Migration Considerations

### 10.1 Strengths

✅ **Schema Flexibility**: Products can define custom inventory fields  
✅ **Encryption at Rest**: Fernet ensures inventory data security  
✅ **Atomic Reservations**: Race-free stock allocation  
✅ **Automatic Monitoring**: Zero-crossing detection with notifications  
✅ **Marketing Integration**: Separate allocation tracking for campaigns  
✅ **Deduplication**: Fingerprint-based uniqueness per product  
✅ **Multi-Format Support**: XLSX/CSV/TXT/session files  

### 10.2 Limitations

⚠️ **No Key Rotation**: Changing encryption key orphans all inventory  
⚠️ **No SKU Field**: Traditional SKU-based integrations require mapping  
⚠️ **No Batch Updates**: Schema changes blocked if inventory exists  
⚠️ **Manual Stock Cap**: Only display cap, doesn't prevent overselling marketing  
⚠️ **Single-Use Items**: No concept of renewable/replenishable digital goods  
⚠️ **No Audit Trail**: Deleted items leave no historical record  
⚠️ **No Expiry Tracking**: Cannot mark items as expired  

### 10.3 Migration Risks

🔴 **HIGH**: Encryption key must be preserved or all inventory becomes unreadable  
🟡 **MEDIUM**: Fingerprint algorithm change would allow duplicate imports  
🟡 **MEDIUM**: Schema locked after first import (requires product duplication)  
🟢 **LOW**: Marketing allocations can be bulk-released if needed  
🟢 **LOW**: Stock monitor can be disabled independently  

### 10.4 Data Export Strategy

**For Migration**:
```python
# 1. Export products with schemas
products = await db.products.find({"inventory_enabled": True}).to_list(None)

# 2. Decrypt available inventory per product
for product in products:
    items = await db.inventory_items.find({
        "product_id": product["_id"],
        "status": "available"
    }).to_list(None)
    
    decrypted = decrypt_items(items)  # Requires INVENTORY_ENCRYPTION_KEY
    
    # 3. Write to CSV per product
    schema = product["inventory_schema"]
    with open(f"{product['name']}.csv", "w") as f:
        writer = csv.DictWriter(f, fieldnames=schema)
        writer.writeheader()
        writer.writerows(decrypted)

# 4. Export sold items with buyer mapping
sold_items = await db.inventory_items.find({"status": "sold"}).to_list(None)
# Map to purchases collection via order_id for customer linkage
```

**Preservation Priority**:
1. `INVENTORY_ENCRYPTION_KEY` environment variable (critical)
2. Products collection (metadata + schemas)
3. inventory_items collection (encrypted payload + status)
4. purchases collection (order history + buyer mapping)
5. stock_events collection (marketing ledger)

---

## 11. Technical Debt & Recommendations

### 11.1 Current Technical Debt

1. **Key Management**: No key rotation, no key derivation from master secret
2. **Schema Evolution**: Cannot add fields to existing inventory products
3. **Marketing Stock Tracking**: manual_stock cap doesn't account for marketing allocations in calculation
4. **Error Recovery**: No automated recovery for orphaned reservations (relies on QRIS timeout)
5. **Audit Logging**: Marketing audit trail embedded in item (lost on delete)

### 11.2 Architectural Patterns

**Good Practices**:
- Two-phase commit for checkout (reserve → debit → commit)
- Idempotent refunds via array tracking
- Background workers with locking (monitor_lock)
- Explicit status enums for state machine
- Unique constraints for data integrity

**Anti-Patterns**:
- Mixed concerns (inventory.py handles both storage and checkout logic)
- Global lock for stock monitor (could be per-product)
- Schema validation scattered across multiple files
- Marketing audit stored in inventory item (should be separate collection)

### 11.3 Migration Recommendations

**Phase 1: Data Preservation**
1. Export encryption key to secure vault
2. Full MongoDB dump of critical collections
3. Decrypt and export available inventory to CSV per product
4. Export purchase history with buyer linkage

**Phase 2: Schema Mapping**
1. Map flexible schemas to new system's fixed fields
2. Create SKU mapping table (fingerprint → new SKU)
3. Document catalog hierarchy for category migration
4. Map status values: available→in_stock, reserved→pending, sold→fulfilled

**Phase 3: Cutover Strategy**
1. Freeze new inventory imports 24h before cutover
2. Complete all pending reservations
3. Export final state with reconciliation report
4. Import to new system with validation
5. Parallel run for 1 week (read-only legacy access)

---

## Appendix A: File Inventory

**Core Inventory Files**:
- `backend/inventory.py` (365 lines) – Encryption, CRUD, reservation
- `backend/admin_routes.py` (2260 lines) – Admin API, import/export
- `backend/inventory_admin.py` (149 lines) – Schema management, templates
- `backend/checkout.py` (405 lines) – Reservation, allocation, rollback
- `backend/stock_monitor.py` (150 lines) – Background monitoring, notifications
- `backend/marketing_campaigns.py` (349 lines) – Campaign allocation, ledger
- `backend/product_catalog.py` (50 lines) – Catalog grouping, navigation
- `backend/db.py` (191 lines) – Database schema, indexes

**Supporting Files**:
- `backend/bot.py` (2301 lines) – Telegram bot UI, product display
- `backend/bot2.py` (1300+ lines) – Reseller bot, restock requests
- `backend/direct_checkout.py` (490 lines) – QRIS payment flow
- `backend/pricing.py` – Discount calculation
- `backend/promo_service.py` – Coupon validation

---

## Appendix B: MongoDB Collections Detail

**products**:
```javascript
{
  _id: "uuid",
  name: "ChatGPT Plus",
  catalog_name: "ChatGPT",
  product_kind: "digital" | "service",
  delivery_type: "inventory" | "service",
  inventory_enabled: true,
  inventory_schema: ["email", "password"],
  inventory_mode: "table" | "telegram_session",
  stock_mode: "auto" | "manual",
  manual_stock: 100,
  price_usd: 20.0,
  price_idr: 320000,
  active: true,
  stock_notice_available: true,
  stock_notice_count: 45
}
```

**inventory_items**:
```javascript
{
  _id: "uuid",
  product_id: "uuid",
  fingerprint: "sha256_hex",
  secret: "fernet_base64",
  status: "available" | "reserved" | "sold" | "marketing_allocated",
  reservation_id: "order:uuid",
  order_id: "uuid",
  user_tid: 123456789,
  customer_id: "uuid",
  created_at: "2026-10-03T19:00:00Z",
  reserved_at: "2026-10-03T19:05:00Z",
  sold_at: "2026-10-03T19:06:00Z",
  marketing: { event_id: "uuid", campaign_id: "marketing:x:y" },
  marketing_audit: [{ _id: "marketing:allocate:uuid", event_type: "..." }]
}
```

**stock_events**:
```javascript
{
  _id: "uuid",
  product_id: "uuid",
  product_name: "ChatGPT Plus",
  event_type: "restocked" | "sold_out" | "OWNER_MARKETING_ALLOCATION",
  from_count: 0,
  to_count: 25,
  targets: ["-100123456789"],  // Telegram chat IDs
  delivered: ["-100123456789"],
  status: "pending" | "sent",
  created_at: "2026-10-03T19:00:00Z"
}
```

---

**End of Audit**
