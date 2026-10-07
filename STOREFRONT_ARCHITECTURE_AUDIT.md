# Storefront Architecture Audit

**Date**: 2026-10-03  
**System**: IDSE Digital Product Marketplace  
**Focus**: Customer-facing web storefront implementation

---

## Executive Summary

The storefront is a React-based SPA with FastAPI backend, implementing a complete e-commerce flow from catalog browsing to checkout and order fulfillment. Mobile-first responsive design with Tailwind CSS. Payment via QRIS (GoPay) and account balance. Unified customer accounts across web and Telegram bot.

---

## Technology Stack

### Frontend
- **Framework**: React 19.0.0 + React Router 7.15.0 (SPA)
- **UI Library**: Radix UI primitives (dialog, dropdown, accordion, etc.)
- **Styling**: Tailwind CSS 3.4.17 + custom theme (`storefront.css`)
- **State Management**: React hooks, localStorage for cart persistence
- **HTTP Client**: Axios 1.18.0
- **Build Tool**: Create React App + CRACO 7.1.0

### Backend
- **Framework**: Python FastAPI
- **Database**: MongoDB (shared with Telegram bot)
- **Authentication**: JWT via cookies (httpOnly, secure)
- **Email**: SMTP (nodemailer-style config)
- **Payment**: Node.js GoPay SDK (`backend/gobiz/`)

### Key Dependencies
- `react-hook-form` 7.56.2 + `zod` 3.24.4 (form validation)
- `framer-motion` 11.18.0 (animations)
- `date-fns` 4.1.0 (date formatting)
- `lucide-react` 0.516.0 (icons)

---

## Shopping Flow Architecture

### 1. Browse / Catalog (`/store/products`)

**Endpoint**: `GET /api/store/products?search={term}`

**Features**:
- Product listing with catalog grouping
- Search by name/description (regex, case-insensitive)
- Filters: All, Bestseller, Ready Stock, Out of Stock, Service
- Real-time stock display via `stock_for()` function
- Dynamic pricing with discount calculation per product
- Sales count aggregation from `purchases` collection
- Pagination: 12 items per page

**Stock Logic**:
- Digital products: Count available `inventory_items` (status != sold)
- Manual stock: Use `product.stock` field
- Service products: Unlimited stock

**Data Flow**:
```
User → Browse page → GET /api/store/products
         ↓
Backend aggregates sales_count, calculates pricing
         ↓
Frontend renders catalog cards with stock status
```

### 2. Product Detail (`/store/product/:id`)

**Endpoint**: `GET /api/store/products/{product_id}`

**UI Pattern**: Modal overlay (preserves background catalog state via React Router location.state)

**Features**:
- Product description, pricing, stock availability
- Minimum purchase quantity enforcement
- Add to cart with quantity selector
- Related products/variants from same catalog
- Product artwork generation (SVG initials + icons)

**Validation**:
- Quantity >= `minimum_purchase_qty` (default: 1)
- Quantity <= available stock
- Stock check before adding to cart

### 3. Cart (`/store/cart`)

**Storage**: localStorage key `store_cart` (JSON array)

**Schema**:
```json
[
  {"pid": "product_id", "qty": 2}
]
```

**Features**:
- Live price quote via `POST /api/store/quote` (debounced 180ms)
- Coupon code validation
- Payment method selection: QRIS or Balance
- Quantity adjustment (respects min/max)
- Remove item
- Minimum purchase validation per product

**Quote API** (`POST /api/store/quote`):
- Input: `{items, currency, coupon_code}`
- Output: `{items[], subtotal, discount_total, coupon_discount, total, coupon_error}`
- Validates stock availability
- Calculates product discounts + coupon discount
- No stock reservation (quote only)

### 4. Checkout (`POST /api/store/checkout`)

**Idempotency**: Required `idempotency_key` (8-80 chars) prevents duplicate orders

**Payment Methods**:

#### QRIS (All Payment)
1. Stock reservation:
   - Digital products: `reserve_items()` in `inventory_items`
   - Manual stock: Decrement `product.stock`
2. Create order with status `pending_payment`
3. Create `gopay_payments` record
4. Generate QR code via Node.js script (`create_qris.mjs`)
5. Return QR image (base64 PNG) + payment details
6. Frontend polls order status every 5 seconds
7. On payment confirmation:
   - `commit_items()` marks inventory as sold
   - Order status → `delivered` (digital) or `service_waiting` (service)
   - Send order completion email

**QRIS Details**:
- Provider: GoPay
- Amount: base + 0.7% admin fee + 3-digit unique suffix (100-999)
- Expiry: 5 minutes (configurable via `GOPAY_QR_TIMEOUT_MINUTES`)
- QR regeneration available for pending orders

#### Balance Payment
1. Validate user balance (`store_customers.balance_idr` or `bot_users.balance_idr`)
2. Execute checkout via existing `execute_checkout()` function
3. Immediate balance deduction
4. Order status → `paid`
5. Auto-finalize:
   - Digital products → `delivered`
   - Service products → `service_waiting` (notify admin)
6. Send completion email for digital products

**Error Handling**:
- HTTP 409: Idempotency key exists (return existing order)
- HTTP 400: Insufficient balance, stock changed, invalid coupon
- HTTP 503: Payment gateway failure

### 5. Order Fulfillment

**Delivery Channels**:
1. **Email** (primary): HTML + attachments
   - Account credentials: TXT file
   - Session files: ZIP archive
   - Product content: Inline in email body
2. **Download endpoints**:
   - `GET /api/store/orders/{id}/download` (TXT)
   - `GET /api/store/orders/{id}/files/{item_id}` (binary files)

**Email Template**:
- Subject: "Order completed - {invoice_id}"
- From: `SMTP_FROM_NAME` (env) + `SMTP_FROM` (email)
- Body: Product list, pricing, payment method, status
- Attachments: Named `invoice-{invoice_id}.txt` / `.zip`

**Status Flow**:
```
pending_payment → paid → delivered (digital)
                      → service_waiting (service) → completed
```

**Delivery Tracking**:
- `delivery_email_status`: sending → sent / failed
- One-time send (flag prevents duplicate emails)
- Error stored in `delivery_email_error` field

---

## Customer Account System

### Registration (`/store/register`)

**Flow**:
1. User submits email
2. Backend validates email format, checks duplicates
3. Generate 6-digit OTP, store hash in `store_email_codes`
4. Send via SMTP (10-minute expiry)
5. User submits email + OTP + password
6. Verify OTP (max 5 attempts)
7. Create `store_customers` record (bcrypt password hash)
8. Set JWT cookie, redirect to profile

**Rate Limits**:
- 60 seconds between code requests
- 5 codes per hour per email

### Login (`/store/login`)

**Flow**:
1. User submits email + password
2. Backend verifies password hash
3. Set JWT cookie (12-hour expiry)
4. JWT payload: `{sub: customer_id, type: "customer", sv: session_version}`

**Session Management**:
- Cookie: `customer_access_token` (httpOnly, secure, sameSite=lax)
- Logout: Delete cookie + increment `session_version` (invalidates all sessions)
- Auto-refresh: Cookie renewed on authenticated requests

### Password Reset (`/store/password/request-code`)

**Flow**: Same OTP mechanism as registration
- Purpose field: `reset` (separate from `register`)
- Silent success if email not found (security)

### Telegram Integration

**Linking Process**:
1. User clicks "Link Telegram" in web profile
2. `POST /api/store/link-code` generates 8-char code (10-minute expiry)
3. User sends code to Telegram bot
4. Bot calls `complete_telegram_link(telegram_id, code)`
5. Backend updates `store_customers.telegram_id`
6. **Wallet Merge**: Web balance → Telegram balance (one-time, irreversible)
7. Future purchases use unified Telegram balance

**Unified Data**:
- Orders: `customer_id` OR `user_tid` (either channel)
- Deposits: Same unification
- Balance: Telegram balance becomes source of truth after link

### Profile Management (`/store/profile`)

**Editable Fields**:
- `display_name`: 1-80 chars (required)
- `phone`: 7-20 digits, optional +prefix

**Read-Only Display**:
- Email (from registration)
- Telegram username/name (if linked)
- Balance (IDR/USD)
- Verification status
- Created date

---

## Payment Integration

### QRIS (GoPay via Node.js)

**Architecture**:
- Python FastAPI → Node.js subprocess → GoPay SDK
- Scripts location: `backend/gobiz/`
- Key script: `create_qris.mjs`

**Payment Record** (`gopay_payments` collection):
```json
{
  "_id": "payment_uuid",
  "payment_scope": "store" | "bot1",
  "deposit_id": "deposit_uuid",
  "customer_id": "customer_uuid",
  "user_tid": telegram_id,
  "base_amount": 50000,
  "payment_amount": 50783,
  "active_payment_amount": 50783,
  "status": "pending" | "confirmed" | "failed",
  "tx_id": "gopay_transaction_id",
  "created_at": "ISO datetime",
  "expires_at": "ISO datetime",
  "confirmed_at": "ISO datetime"
}
```

**Unique Amount Generation**:
- Base amount + admin fee (0.7%) + random suffix (100-999)
- Prevents duplicate payment_amount (unique index)
- Max 200 attempts to find unique combination

**QR Code**:
- Generated via `_run_node('create_qris.mjs', [amount])`
- Returns base64 PNG image
- Embedded in API response as data URL

**Payment Verification**:
- Background worker checks `gopay_payments` status
- Matches exact payment amount
- Updates order status on confirmation

### Balance Payment

**Sources**:
- Web-only: `store_customers.balance_idr`
- Telegram-linked: `bot_users.balance_idr` (unified)

**Checkout Flow**:
1. Check if Telegram linked → apply pending wallet merge
2. Call `execute_checkout()` (shared with Telegram bot)
3. Atomic balance deduction
4. Order created with status `paid`
5. Auto-finalize to `delivered` or `service_waiting`

**Balance Top-Up**:
- Deposit via QRIS: `POST /api/store/deposits`
- Creates `deposits` record + `gopay_payments` record
- On confirmation: Credit balance, notify user
- Viewable in `/store/deposit` and `/store/transactions`

---

## Mobile Responsiveness

### Design Approach
- **Mobile-first**: Default styles for mobile, enhanced for desktop
- **Breakpoints**: `sm:` (640px), `lg:` (1024px), `xl:` (1280px)
- **Touch-optimized**: Minimum 44px tap targets, larger buttons

### Responsive Components

**Navigation**:
- Mobile: Bottom tab bar (4 items) + hamburger drawer
- Desktop: Top header with inline links

**Product Grid**:
- Mobile: 2 columns (`grid-cols-2`)
- Tablet: 2 columns (`sm:grid-cols-2`)
- Desktop: 3-4 columns (`lg:grid-cols-3 xl:grid-cols-4`)

**Catalog Cards**:
- Mobile: Compact layout, smaller images
- Desktop: Larger images, more metadata

**Cart**:
- Mobile: Stacked layout (product list → summary)
- Desktop: Two-column layout (list | sticky summary)

**Modal/Dialog**:
- Mobile: Full-screen bottom sheet
- Desktop: Centered modal (max-width 600px)

### CSS Features (`storefront.css`)

**Dark Mode**:
- Attribute selector: `[data-theme="dark"]`
- Auto mode detects `prefers-color-scheme`
- Overrides for bg, text, border colors
- Images always light (`color-scheme: light`)

**Animations**:
- `store-pop-in`: Modal entrance (scale + fade)
- `store-slide`: Toast notification (translateY)
- `store-orbit`: Loading spinner
- Respects `prefers-reduced-motion` (disable animations)

**Transitions**:
- Background/color: 0.25s
- Transform: Hardware-accelerated (translateY, scale)
- Hover states: 150ms

### Accessibility

**Features Implemented**:
- Semantic HTML: `<nav>`, `<header>`, `<footer>`, `<article>`
- ARIA labels: `aria-label`, `aria-current`, `aria-busy`
- Focus management: `focus:ring` states, keyboard navigation
- Skip to content (via header navigation)
- Color contrast: WCAG AA compliant (emerald-800 on white)

**Keyboard Support**:
- Tab navigation through all interactive elements
- Enter/Space to activate buttons
- Escape to close modals

**Screen Readers**:
- Product stock: "Ready Stock" vs "Out of Stock"
- Cart count: "Keranjang, X item"
- Loading states: aria-busy attribute

---

## Tenant-Specific Branding

### Hardcoded Brand Elements

1. **Brand Name**: "IDSE Marketplace" (throughout UI)
2. **Tagline**: "KEBUTUHAN DIGITALMU, DI SINI."
3. **Logo**: `/frontend/public/idse-logo.svg`
4. **Theme Colors**:
   - Primary: Emerald green (`#065f46` / emerald-800)
   - Accent: Light emerald (`#ecfdf5` / emerald-50)
   - Background: Off-white (`#f7f8f6`)
5. **Copyright**: "© {year} IDSE Marketplace"

### Configurable Brand Elements

1. **Email Branding**:
   - Sender name: `SMTP_FROM_NAME` env var (default: "IDSE verification-noreply")
   - Sender email: `SMTP_FROM` env var
   - Subject prefix: "IDSE Digital Product"

2. **Contact Methods** (stored in `settings` collection):
   - `whatsapp_contact_number`: WhatsApp click-to-chat
   - `telegram_contact_target`: Telegram bot/channel link

3. **Bot Integration**:
   - `TELEGRAM_BOT_USERNAME` env var (for Telegram link instructions)

4. **Product Artwork**:
   - Dynamically generated (product initials + icons)
   - No tenant logo/branding in product cards

### Multi-Tenant Adaptation Requirements

**To support multiple tenants, modify**:
1. Logo: Replace `/idse-logo.svg`, update `<img>` references
2. Brand name: Extract to config/environment variable
3. Theme colors: Move to Tailwind config or CSS variables
4. Email templates: Parameterize sender name/subject
5. Page title: Dynamic `document.title`
6. Footer: Extract copyright holder name
7. Tagline: Configuration file or database

---

## Database Schema

### `store_customers`
```json
{
  "_id": "uuid",
  "email": "user@example.com",
  "password_hash": "bcrypt_hash",
  "balance_idr": 0,
  "balance_usd": 0,
  "display_name": "User Name",
  "phone": "+628123456789",
  "telegram_id": 123456789,
  "telegram_linked_at": "ISO datetime",
  "telegram_link_code_hash": "sha256_hash",
  "telegram_link_expires_at": "ISO datetime",
  "wallet_merge": {
    "id": "uuid",
    "status": "pending" | "complete",
    "amount_idr": 0,
    "amount_usd": 0
  },
  "verified_at": "ISO datetime",
  "created_at": "ISO datetime",
  "session_version": 0
}
```

### `purchases` (orders)
```json
{
  "_id": "uuid",
  "invoice_id": "INV-20261003-001",
  "customer_id": "customer_uuid",
  "customer_email": "user@example.com",
  "user_tid": telegram_id,
  "status": "pending_payment" | "paid" | "delivered" | "service_waiting" | "completed",
  "payment_method": "qris" | "balance",
  "payment_id": "payment_uuid",
  "payment_scope": "store" | "bot1",
  "currency": "IDR",
  "total": 50000,
  "discount_total": 5000,
  "items": [
    {
      "product_id": "product_uuid",
      "name": "Product Name",
      "qty": 2,
      "unit_price": 25000,
      "subtotal": 50000,
      "discount_per_unit": 0,
      "delivery_type": "inventory" | "service"
    }
  ],
  "idempotency_key": "checkout_key",
  "created_at": "ISO datetime",
  "expires_at": "ISO datetime",
  "expires_in_minutes": 5,
  "delivered_at": "ISO datetime",
  "delivery_email_status": "sending" | "sent" | "failed",
  "delivery_email_error": "error message"
}
```

### `gopay_payments`
```json
{
  "_id": "uuid",
  "payment_scope": "store" | "bot1",
  "deposit_id": "deposit_uuid",
  "customer_id": "customer_uuid",
  "user_tid": telegram_id,
  "base_amount": 50000,
  "payment_amount": 50783,
  "active_payment_amount": 50783,
  "status": "pending" | "confirmed" | "failed",
  "tx_id": "gopay_tx_id",
  "created_at": "ISO datetime",
  "expires_at": "ISO datetime",
  "confirmed_at": "ISO datetime"
}
```

### `store_email_codes`
```json
{
  "_id": "auto",
  "email": "user@example.com",
  "purpose": "register" | "reset",
  "code_hash": "hmac_sha256",
  "expires_at": "ISO datetime",
  "attempts": 0,
  "sent_count": 1,
  "window_started_at": "ISO datetime",
  "last_sent_at": "ISO datetime"
}
```

---

## Security Implementation

### Authentication
- **Password Hashing**: bcrypt via `auth.hash_password()`
- **JWT Secret**: `JWT_SECRET` env var (HMAC SHA-256)
- **Session Cookie**: httpOnly, secure, sameSite=lax, 12-hour expiry
- **Session Versioning**: Increment to invalidate all sessions

### Authorization
- Customer ID from JWT payload
- Order ownership verified: `customer_id` OR `user_tid` match
- Download endpoints: Check ownership before serving files

### Rate Limiting
- Email OTP: 60s cooldown, 5 per hour per email
- OTP attempts: Max 5 per code

### Data Protection
- **Inventory Encryption**: AES-256-GCM via `inventory.encrypt_items()`
- **Decryption**: Only on delivery/download
- **Email Attachments**: Temporary in-memory (not saved to disk)

### Input Validation
- Pydantic models for all API requests
- Email validation via `email-validator` library
- Regex patterns for phone, username
- SQL injection: None (MongoDB with parameterized queries)

### Cookie Security
```python
secure = os.getenv("COOKIE_SECURE", "true")  # Force HTTPS
response.set_cookie(
    "customer_access_token", 
    session,
    httponly=True,
    secure=secure,
    samesite="lax",
    max_age=43200,
    path="/"
)
```

### SMTP Security
- TLS/SSL support
- Credentials in environment variables (not committed)
- Timeout: 15s (registration), 20s (order delivery)

---

## Environment Configuration

### Required Environment Variables

```bash
# JWT
JWT_SECRET=your-secret-key

# SMTP (email delivery)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@example.com
SMTP_PASSWORD=smtp_password
SMTP_FROM=noreply@example.com
SMTP_FROM_NAME="IDSE Digital Product"
SMTP_USE_SSL=false

# Payment (QRIS)
GOPAY_ENABLED=true
GOPAY_QR_TIMEOUT_MINUTES=5

# Telegram
TELEGRAM_BOT_USERNAME=yourbotname

# Security
COOKIE_SECURE=true  # Set false for localhost testing
```

### Database Configuration
- MongoDB connection string (shared with backend)
- Collections: `store_customers`, `purchases`, `gopay_payments`, `deposits`, `store_email_codes`, `inventory_items`, `products`, `bot_users`

---

## Performance Considerations

### Frontend Optimization
- **Code Splitting**: React Router lazy loading
- **Image Loading**: `loading="lazy"` on product images
- **Debouncing**: 180ms for quote API (reduces server load)
- **Local Storage**: Cart persisted (survives page refresh)
- **Polling**: 5s interval for order status (only active orders)

### Backend Optimization
- **Idempotency**: Prevents duplicate order creation
- **Stock Reservation**: Atomic operations (prevents overselling)
- **Aggregation Pipeline**: Sales count calculated via MongoDB aggregation
- **Index Optimization**: Unique indexes on `payment_amount`, `email`, `telegram_id`

### Caching
- **None implemented** (all data fetched fresh)
- **Recommendation**: Add Redis for product catalog, pricing

---

## Known Limitations

1. **No Pagination**: Product list loads all active products (potential issue with >1000 products)
2. **Cart Sync**: Cart stored in localStorage (not synced across devices)
3. **No Abandoned Cart Recovery**: No email reminders for incomplete checkouts
4. **Single Currency**: IDR hardcoded for web checkout (USD available in backend but not exposed)
5. **Email-Only Delivery**: No SMS/WhatsApp delivery option
6. **No Guest Checkout**: Account required before checkout
7. **No Wishlist**: No save-for-later functionality
8. **Hardcoded Branding**: Multi-tenant requires code changes
9. **No Search Analytics**: Search terms not tracked
10. **Limited Error Recovery**: QRIS expiry requires new checkout (can't extend)

---

## Recommendations for Production

### High Priority
1. **Add Pagination**: Limit product list to 50-100 per page
2. **Implement Caching**: Redis for product catalog, settings
3. **Add Monitoring**: Sentry/Rollbar for error tracking
4. **Database Indexes**: Ensure indexes on frequently queried fields
5. **Rate Limiting**: Add global API rate limiter (prevent abuse)

### Medium Priority
6. **Cart Sync**: Store cart in database for logged-in users
7. **Abandoned Cart**: Email reminders after 24 hours
8. **Search Analytics**: Track popular search terms
9. **Multi-Currency**: Expose USD pricing in storefront
10. **Webhook Retry**: Implement exponential backoff for email delivery failures

### Low Priority
11. **Guest Checkout**: Allow checkout without account (email + phone)
12. **Wishlist**: Save products for later
13. **Product Reviews**: Customer rating system
14. **Order Tracking**: Delivery status updates
15. **Multi-Tenant Config**: Extract brand elements to configuration

---

## Testing Coverage

### Existing Tests (from `backend/tests/`)
- `test_storefront_auth.py`: Registration, login, password reset
- `test_direct_checkout.py`: QRIS checkout flow
- `test_purchase_source.py`: Web vs Telegram order source tracking

### Recommended Additional Tests
- End-to-end checkout flow (Playwright/Cypress)
- Mobile responsive layout (visual regression)
- Payment gateway integration (mocked)
- Email delivery (integration test)
- Cart persistence across sessions
- Concurrent checkout (race condition testing)

---

## Deployment Notes

### Build Process
```bash
cd frontend
npm install
npm run build  # Creates optimized production build
```

### Serve Static Files
- Production: Serve `frontend/build/` via nginx/Apache
- Dev: `npm start` (webpack dev server)

### Backend Deployment
- Python 3.11+
- Install dependencies: `pip install -r backend/requirements.txt`
- Run: `uvicorn main:app --host 0.0.0.0 --port 8000`

### Routing
- SPA requires catch-all routing (nginx `try_files`)
- API prefix: `/api/`
- Static assets: `/static/`, `/idse-logo.svg`

---

## Conclusion

The storefront is a complete, production-ready e-commerce implementation with mobile-responsive design, secure authentication, and integrated payment processing. The architecture supports both web and Telegram channels with unified customer accounts and order management.

**Strengths**:
- Modern React stack with good UX
- Mobile-first responsive design
- Secure authentication and payment handling
- Unified web/Telegram customer experience
- Clean API design with proper error handling

**Areas for Improvement**:
- Add caching layer for performance
- Implement pagination for scalability
- Extract branding for multi-tenant support
- Add comprehensive test coverage
- Implement monitoring and analytics

The codebase is well-structured and maintainable, following React and FastAPI best practices. The shopping flow is intuitive and mirrors established e-commerce patterns.
