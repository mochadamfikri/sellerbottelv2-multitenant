# Admin Panel Legacy System Audit

**Audit Date:** 2026-10-03  
**Audited By:** Hermes Subagent  
**Repository:** `/opt/sellerbottel-v2/repo`

---

## Executive Summary

The admin panel is a modern React-based single-page application (SPA) with 16 navigation items managing a digital product sales platform with Telegram bot integration. The UI is built with contemporary web technologies and follows accessibility best practices. The current navigation structure requires reorganization to match Owner role requirements.

---

## 1. Technical Architecture

### 1.1 Frontend Framework & Stack

**Core Framework:** React 19.0.0  
**Router:** React Router DOM 7.15.0  
**Build Tool:** Create React App 5.0.1 with CRACO 7.1.0  
**Styling:** Tailwind CSS 3.4.17 with custom dark theme  
**UI Components:** shadcn/ui pattern with Radix UI primitives

**Key Dependencies:**
- `@tanstack/react-query` 5.56.2 - Server state management
- `axios` 1.18.0 - HTTP client
- `framer-motion` 11.18.0 - Animations
- `recharts` 3.6.0 - Data visualization
- `sonner` 2.0.3 - Toast notifications
- `zod` 3.24.4 - Schema validation
- `react-hook-form` 7.56.2 - Form handling

**Code Quality:**
- ESLint 9.23.0 with React, a11y, and import plugins
- Test infrastructure via react-scripts (Jest + React Testing Library)
- Test IDs implemented for automated testing (`@/constants/testIds/`)

### 1.2 Project Structure

```
frontend/
├── src/
│   ├── pages/           # 18 route components
│   ├── components/      # Reusable UI components + shadcn/ui library
│   ├── context/         # AuthContext for authentication state
│   ├── lib/             # API client, utilities, catalog helpers
│   ├── constants/       # Test IDs organized by feature
│   ├── hooks/           # Custom React hooks (toast, etc.)
│   └── App.js           # Router configuration
├── public/
└── package.json
```

### 1.3 API Integration

**Base URL:** Configured via `REACT_APP_BACKEND_URL` or defaults to `/api`  
**HTTP Client:** Axios instance with `withCredentials: true` (session cookies)  
**Error Handling:** Centralized `formatApiErrorDetail()` function  
**Endpoints Pattern:** RESTful `/admin/*` routes

---

## 2. Authentication & Authorization

### 2.1 Authentication Flow

**Mechanism:** Session-based authentication with HTTP-only cookies  
**Context Provider:** `AuthContext` (`src/context/AuthContext.jsx`)

**User State Management:**
- `null` = Loading/checking session
- `false` = Not authenticated → redirect to `/login`
- `object` = Authenticated user data

**Endpoints:**
- `GET /auth/me` - Session verification on app load
- `POST /auth/login` - Email/password authentication
- `POST /auth/logout` - Session termination

### 2.2 Route Protection

**Protected Component Pattern:**
```javascript
<Protected title="Page Title">
  <PageComponent />
</Protected>
```

**Behavior:**
- Shows loading screen while checking authentication
- Redirects to `/login` if unauthenticated
- Wraps content in Layout component with sidebar navigation

**Public Routes:**
- `/login` - Authentication page
- `/store/*` - Public storefront (9 routes)

**Protected Routes:** 16 admin routes (see Navigation Structure)

---

## 3. Current Navigation Structure

### 3.1 Sidebar Navigation (16 Items)

Defined in `src/components/Layout.jsx` (lines 9-26):

| # | Route | Label | Icon | Page Component |
|---|-------|-------|------|----------------|
| 1 | `/admin` | Ringkasan | LayoutDashboard | Overview.jsx |
| 2 | `/catalogs` | Katalog | Boxes | Catalogs.jsx |
| 3 | `/products` | Produk | Package | Products.jsx |
| 4 | `/inventory` | Kelola Inventory | Boxes | Inventory.jsx |
| 5 | `/orders` | Orders | ClipboardList | Orders.jsx |
| 6 | `/reports` | Rekap | BarChart3 | Reports.jsx |
| 7 | `/deposits` | Deposit | Wallet | Deposits.jsx |
| 8 | `/users` | Pengguna | Users | Users.jsx |
| 9 | `/discounts` | Discount | Percent | Discounts.jsx |
| 10 | `/broadcasts` | Broadcast | Megaphone | Broadcasts.jsx |
| 11 | `/central-broadcasts` | Broadcast Terpusat | Megaphone | CentralBroadcasts.jsx |
| 12 | `/resellers` | Bot Reseller | Bot | Resellers.jsx |
| 13 | `/promotions` | Promosi / Cari Pelanggan | Megaphone | Promotions.jsx |
| 14 | `/messages` | Bot Messages | MessageSquareText | Messages.jsx |
| 15 | `/bot-moderation` | Tindak Lanjut Bot | ShieldOff | BotModeration.jsx |
| 16 | `/settings` | Pengaturan | Settings | SettingsPage.jsx |

**Navigation UX:**
- Responsive slide-out sidebar (mobile menu button)
- Active state highlighting (cyan accent)
- Logout button pinned to bottom
- Header shows current page title

### 3.2 Owner Role Requirements vs Current State

**Required Changes:**

| Requirement | Current State | Gap Analysis |
|-------------|---------------|--------------|
| **Merge Broadcast + Broadcast Terpusat** | Two separate items (#10, #11) | ✗ Need to consolidate into single page with tabs |
| **Merge Rekap + Order** | Two separate items (#5, #6) | ✗ Need unified Orders & Reports page |
| **Create Catalog & Inventory submenu** | Two top-level items (#2, #4) | ✗ Need submenu navigation pattern |
| **Merge Promosi + Cari Pelanggan** | Already merged (#13) | ✓ Single item "Promosi / Cari Pelanggan" |

**Note:** Navigation array is flat; no existing submenu/grouping pattern in Layout.jsx. Will need to implement collapsible sections or route-based sub-navigation.

---

## 4. Admin Module Capabilities

### 4.1 Dashboard & Analytics

**Overview (Ringkasan)** - `Overview.jsx`
- Real-time statistics: Total Deposit, Sales, Circulating Balance, Pending Deposits
- Recent deposits list with status badges
- System status: USD/IDR exchange rate, rate mode
- **Statistics reset capability** (password-protected admin action)
- Auto-refresh: None detected

**Reports (Rekap)** - `Reports.jsx`
- Daily and monthly revenue reports
- Filters: Date range, currency (all/IDR/USD)
- Metrics: Orders, completed/refunded orders, items sold, unique buyers/depositors
- Financial summary: Gross sales, refunds, net sales, deposits, discounts
- Product-level breakdown (qty, orders, revenue)
- Monthly view includes daily breakdown
- **Excel export** via `/admin/reports/export`

### 4.2 Product & Inventory Management

**Catalogs (Katalog)** - `Catalogs.jsx`
- Group products into named catalogs
- Create, rename, delete catalogs
- Bulk product assignment between catalogs
- View catalog in public storefront
- Default catalog: "Produk Lainnya" (cannot be deleted)
- Link to Products page with catalog filter

**Products (Produk)** - `Products.jsx`
- **Product Types:** Digital, Service
- **Pricing:** Dual currency (USD + IDR)
- **Stock Modes:** Auto (from inventory), Manual
- **Inventory Modes:** Table-based, Telegram session-based
- **Delivery Types:** Inventory items, Direct link, Rich content
- **Image Management:** Generated or custom upload
- **Bulk Import:** CSV/text parsing with validation
- **Inventory Import:** Quick-add stock from product page
- **5-second auto-refresh** for stock monitoring

**Inventory (Kelola Inventory)** - `Inventory.jsx` (31,675 bytes - largest page)
- **Comprehensive inventory system** for digital products
- Schema-based multi-field inventory (email:password, account credentials, etc.)
- Status filters: available, reserved, sold
- Pagination: 100 items per page
- **Manual entry:** Add single inventory items
- **Bulk upload:** CSV/Excel import with schema mapping
- **File upload:** Multi-file processing (txt, csv, xlsx)
- **Inventory transformation:** Email domain replacement, password generation
- **Replace mode:** Swap sold-out inventory files
- **Telegram session management:** For account-based products
- Edit individual inventory items
- Delete inventory items with confirmation
- **Real-time updates:** 5-second polling when visible
- Preview before import (first 10 rows)

### 4.3 Order & Transaction Management

**Orders** - `Orders.jsx`
- Status filters: all, pending, pending_payment, paid, service_waiting, delivered, delivery_failed, failed, refunded
- Search: Invoice ID, email, username, Telegram ID
- Order detail modal with full transaction history
- **Service order completion** workflow
- **Refund capability** for failed/delivery_failed orders
- **Email retry** for failed delivery notifications
- Order items list with quantities
- Discount and coupon tracking
- Delivery status and notes

**Deposits (Deposit)** - `Deposits.jsx`
- Status filters: all, pending, approved, rejected, cancelled
- Payment methods: Crypto (SOL/POL/BNB/AVAX), QRIS (GoPay), Bank transfer
- **Proof of payment viewer** (image modal)
- **Blockchain explorer links** for crypto transactions
- Approve/reject workflow with admin notes
- Cancel approved deposits (reverses balance)
- User information: Name, username, Telegram ID
- Amount tracking: Requested vs credited (for crypto rate differences)

### 4.4 User Management

**Users (Pengguna)** - `UsersPage.jsx`
- **Unified directory:** Telegram + Web accounts
- **Account linking detection** (shows linked accounts once)
- Source filters: all, telegram, web, linked
- Search: Name, username, email, Telegram ID
- Pagination: 25 users per page
- User details: Balance (USD/IDR), deposits, orders, registration date
- **Balance adjustment tool** (add/subtract with reason)
- **Freeze/unfreeze accounts** with reason tracking
- **Force join group** action for Telegram users
- Balance history and transaction log

### 4.5 Marketing & Promotions

**Discounts** - `Discounts.jsx`
- Discount types: Percentage, Fixed amount (IDR/USD)
- Product selection: All products or specific products
- Quantity-based triggers (min/max qty)
- Priority system for stacking rules
- Date range activation (starts_at/ends_at)
- Active/inactive toggle
- Multi-product selection interface

**Broadcasts** - `Broadcasts.jsx` (16,915 bytes)
- **Three broadcast types:**
  1. Message & Products (custom message + up to 10 products with auto-generated image)
  2. Best Sellers (rankings, units sold, revenue)
  3. Daily Recap (yesterday's sales summary)
- **Target selection:** Channels/groups, all bot users, or both
- Product selection with custom summaries
- **Auto-generated poster images** via AI
- **Preview mode** (see message + image before sending)
- **Test send** to admin Telegram
- Broadcast history with status
- **Stock notification events** tracking
- **Automated daily recap scheduling** (configurable time + target)
- Draft auto-save to localStorage
- Marketing campaigns component integration

**Central Broadcasts (Broadcast Terpusat)** - `CentralBroadcasts.jsx`
- **8 pre-defined announcement topics:**
  1. Reseller Guide (how to become reseller)
  2. Reseller Contest (active contest details)
  3. Active Discounts (from discount rules)
  4. Active Coupons (from coupon system)
  5. Product Update (feature specific products)
  6. Product Restock (announce restocked items)
  7. Deposit Guide (payment methods + checkout)
  8. System Announcement (custom free-form message)
- **Auto-generated posters** for all announcement types
- Reference data selection (picks live discounts/coupons/products/contests)
- Optional custom notes
- Target: channels/groups, all users, or both
- Preview + Test modes
- History filtered to system_update broadcasts

**Promotions (Promosi / Cari Pelanggan)** - `Promotions.jsx` (34,585 bytes - largest module)
- **7-tab interface:** Overview, Accounts, Prospects, Campaigns, Groups, Coupons, Results
- **Telegram account management:**
  - Multi-account login via phone + OTP + 2FA
  - Session persistence and status monitoring
  - Manual prospect entry
- **Prospect database:**
  - Import from CSV/text (Telegram user IDs)
  - Tagging system for segmentation
  - Block/unblock management
- **Marketing campaigns:**
  - Template-based messaging with product links
  - Daily send limits and rate throttling
  - Approval-required mode
  - Time window restrictions (e.g., 09:00-21:00)
  - Source code tracking
  - Account rotation
- **Group posting:**
  - Post to Telegram groups via bot accounts
  - Group membership management
- **Coupon system:**
  - Types: Percentage, fixed amount
  - Currency support (USD/IDR)
  - Quota management (total + per-user limits)
  - Minimum purchase requirements
  - Maximum discount caps
  - Product restrictions
  - Date range activation
  - Usage tracking and redemption history
- **Results tracking:**
  - Source attribution (campaign codes)
  - Conversion metrics
  - Event timeline
- Real-time job queue monitoring

**Resellers (Bot Reseller)** - `Resellers.jsx`
- **Enable/disable reseller program**
- Pricing configuration:
  - Bot creation price (IDR)
  - Admin fee per bot
  - Platform fee structure
  - Wholesale reduction amount
- Bot approval workflow (pending → approved)
- Bot status management (active/suspended/banned)
- Payout requests (approve/reject)
- **Reseller contests:**
  - Create contests with date range
  - Set sales targets (IDR)
  - Prize amounts
  - Leaderboard tracking
  - Winner determination
- Bot detail view: Owner info, sales stats, commission earned
- Payout history

### 4.6 Communication & Moderation

**Bot Messages** - `Messages.jsx`
- Message inbox from bot interactions
- Filter by status/type
- Reply interface
- Thread management
- Archive/delete capabilities

**Bot Moderation (Tindak Lanjut Bot)** - `BotModeration.jsx`
- Follow-up settings configuration
- Automated response rules
- User interaction monitoring
- Escalation workflows

### 4.7 System Configuration

**Settings (Pengaturan)** - `SettingsPage.jsx` (24,720 bytes)
- **Payment Methods:**
  - Crypto: USDT/USDC on SOL, POL, BNB, AVAX networks
  - Bank transfer (account details)
  - QRIS/GoPay with timeout configuration
  - Enable/disable per method
  - Min/max deposit limits (USD/IDR)
- **Exchange Rate:**
  - Mode: Auto or Manual
  - Manual rate setting
- **Contact Information:**
  - WhatsApp contact number
  - Telegram contact target
  - Admin Telegram ID for notifications
- **Bot Integration:**
  - Broadcast channel IDs
  - Group IDs for broadcasts
  - Transaction notification channels
  - Recap notification channels
  - Stock notification toggle
  - Join group target
- **User Onboarding:**
  - Join gate (require channel membership)
  - Fail-open mode
  - Required channels list
- **Automation:**
  - Auto-broadcast new products
  - Transaction success channel notifications
  - Auto-generate broadcast images
  - Stock notifications

---

## 5. UI/UX Patterns

### 5.1 Design System

**Color Palette:**
- Background: `#0B0F17` (dark blue-black)
- Surface: `#0D1220` (elevated dark)
- Borders: slate-800
- Accent: Cyan (primary), Emerald (success), Rose (danger), Amber (warning)

**Typography:**
- Body: System font stack
- Headings: Custom font-heading (likely sans-serif)
- Monospace: For numbers, IDs, amounts

**Components:**
- Cards with border and subtle shadow
- Form inputs with focus states
- Modal dialogs (shadcn/ui Dialog)
- Toast notifications (sonner)
- Status badges with color coding
- Icon buttons and action menus

### 5.2 Accessibility Features

**Implemented:**
- Semantic HTML structure
- ARIA labels on icon-only buttons
- Keyboard navigation support
- Focus management
- Screen reader considerations (role attributes)
- Test IDs for automated testing

**Gaps:**
- No skip-to-content link detected
- Color contrast should be verified (dark theme)
- Form error announcements could be enhanced

### 5.3 Responsive Design

**Breakpoints:**
- Mobile: Default (< 640px)
- Small: sm: (≥ 640px)
- Large: lg: (≥ 1024px)
- Extra Large: xl: (≥ 1280px)

**Mobile Adaptations:**
- Slide-out sidebar navigation
- Collapsible sections
- Horizontal scrolling tables
- Stack grid layouts

---

## 6. Data Flow & State Management

### 6.1 State Management Patterns

**Local State:** `useState` for component-specific data  
**Global State:** AuthContext (user session)  
**Server State:** Direct axios calls (no React Query usage detected despite dependency)  
**Form State:** react-hook-form + zod validation  
**Local Storage:** Broadcast draft auto-save

### 6.2 Real-time Updates

**Polling Strategy:**
- Products page: 5-second interval when visible
- Inventory page: 5-second interval when visible + active product
- No WebSocket or Server-Sent Events detected

**Visibility API:** Used to pause polling when tab is hidden

---

## 7. Testing & Quality Assurance

### 7.1 Test Infrastructure

**Test IDs:**
- Organized by feature (`auth.js`, `home.js`)
- Naming convention: `<feature>-<element>` (kebab-case)
- Usage: `data-testid={LOGIN.submitButton}`

**Test Runners:**
- Jest (via react-scripts)
- React Testing Library

**Detected Test Files:**
- `src/lib/catalog.test.js` - Catalog utility tests

### 7.2 Code Quality

**Linting:** ESLint with React, a11y, and import plugins  
**Type Safety:** None (no TypeScript)  
**Security:** Dependency resolutions for known vulnerabilities

---

## 8. Performance Considerations

### 8.1 Bundle Size

**Large Pages:**
- Promotions.jsx: 34,585 bytes (marketing automation suite)
- Inventory.jsx: 31,675 bytes (complex inventory management)
- Products.jsx: 31,992 bytes (product CRUD)
- SettingsPage.jsx: 24,720 bytes (comprehensive config)

**Optimization Opportunities:**
- Code splitting by route (not currently implemented)
- Lazy loading for heavy components
- Image optimization (products use generated/uploaded images)

### 8.2 API Efficiency

**Polling:** Multiple pages poll every 5 seconds  
**Batching:** Some pages batch initial requests (Promise.all)  
**Caching:** No client-side cache detected beyond React state

---

## 9. Security Assessment

### 9.1 Authentication Security

✓ HTTP-only session cookies  
✓ Credentials included in requests  
✓ Protected route enforcement  
✓ Admin actions require confirmation (refunds, deletes)  
⚠ No CSRF token visible (may be server-handled)  
⚠ No session timeout UI

### 9.2 Data Handling

✓ Error messages sanitized via `formatApiErrorDetail`  
✓ Admin password required for sensitive actions (stats reset)  
✓ Confirmation dialogs for destructive operations  
⚠ Sensitive data (inventory passwords) visible in UI during management

---

## 10. Integration Points

### 10.1 External Services

**Telegram Bot API:** Core integration for bot functionality  
**Payment Gateways:** Crypto wallets, QRIS, Bank transfer  
**Image Generation:** AI-powered poster creation for broadcasts  
**Email:** SMTP for order confirmations and delivery notifications  
**Blockchain Explorers:** Links for transaction verification

### 10.2 Backend API

**Base Path:** `/api`  
**Authentication:** Session-based  
**Error Format:** `{ detail: string | object | array }`  
**Success Format:** `{ data: object }`  
**Special Features:**
- Excel export (blob responses)
- Image upload (multipart/form-data)
- Proof of payment download (blob)

---

## 11. Maintenance & Observability

### 11.1 Error Handling

**User-facing:** Toast notifications via sonner  
**Centralized:** `formatApiErrorDetail()` utility  
**API Errors:** Extracted from `err.response?.data?.detail`

### 11.2 Logging

❌ No console logging strategy visible  
❌ No analytics integration detected  
❌ No error reporting service (Sentry, etc.)

---

## 12. Recommendations for Owner Navigation Restructure

### 12.1 Navigation Consolidation

**Priority 1: Merge Broadcast Pages**
- Create tabbed interface in `Broadcasts.jsx`
- Tab 1: "Pesan & Produk" (current Broadcasts content)
- Tab 2: "Pengumuman Terpusat" (current CentralBroadcasts content)
- Keep separate routes for deep linking: `/broadcasts` and `/broadcasts/central`
- Remove `/central-broadcasts` from sidebar
- Update icon to single Megaphone

**Priority 2: Merge Orders & Reports**
- Create tabbed interface combining Orders.jsx + Reports.jsx
- Tab 1: "Daftar Order" (order list + filters)
- Tab 2: "Rekap & Laporan" (reports + analytics)
- New combined route: `/orders` (make Reports a sub-route `/orders/reports`)
- Remove `/reports` from sidebar
- Update icon to ClipboardList or BarChart3

**Priority 3: Catalog & Inventory Submenu**
- Implement collapsible menu section in Layout.jsx
- Parent: "Katalog & Inventory" (Boxes icon)
- Child 1: "Kelola Katalog" → `/catalogs`
- Child 2: "Kelola Inventory" → `/inventory`
- Add expand/collapse arrow indicator

### 12.2 Implementation Pattern

**Suggested Approach:**
```javascript
// Layout.jsx - Add submenu support
const navWithSubmenus = [
  { to: "/admin", label: "Ringkasan", icon: LayoutDashboard },
  { 
    label: "Katalog & Inventory", 
    icon: Boxes, 
    children: [
      { to: "/catalogs", label: "Kelola Katalog" },
      { to: "/inventory", label: "Kelola Inventory" }
    ]
  },
  { to: "/products", label: "Produk", icon: Package },
  // ... rest
];
```

### 12.3 Final Owner Navigation (16 → 13 items)

1. Ringkasan
2. **Katalog & Inventory** ↓
   - Kelola Katalog
   - Kelola Inventory
3. Produk
4. **Orders & Laporan** (merged)
5. Deposit
6. Pengguna
7. Discount
8. **Broadcast** (merged, with tabs)
9. Bot Reseller
10. Promosi / Cari Pelanggan
11. Bot Messages
12. Tindak Lanjut Bot
13. Pengaturan

---

## 13. Migration Risks & Considerations

### 13.1 Technical Risks

**Route Changes:**
- `/reports` → `/orders?tab=reports` (need redirect)
- `/central-broadcasts` → `/broadcasts?tab=central` (need redirect)

**Bookmarks & External Links:**
- Document old URLs and implement redirects
- Communicate changes to admin users

**Testing Requirements:**
- Verify all sub-navigation state persists on refresh
- Test keyboard navigation with new menu structure
- Ensure mobile menu still collapses properly

### 13.2 User Training

**Required Documentation:**
- Updated navigation screenshots
- "Where did X go?" quick reference
- Video walkthrough of new structure

---

## Appendix A: File Inventory

**Page Components (18 files):**
- Resellers.jsx, Discounts.jsx, Users.jsx, Deposits.jsx, Reports.jsx
- Inventory.jsx, Storefront.jsx, Overview.jsx, CentralBroadcasts.jsx
- Login.jsx, Promotions.jsx, Catalogs.jsx, SettingsPage.jsx
- Messages.jsx, Products.jsx, Orders.jsx, BotModeration.jsx, Broadcasts.jsx

**Key Components:**
- Layout.jsx (sidebar navigation)
- AuthContext.jsx (authentication)
- BalanceAdjustment.jsx, StoreProductDialog.jsx, BroadcastOptions.jsx
- MarketingCampaigns.jsx, StatusBadge.jsx, FollowupSettings.jsx

**Utility Libraries:**
- lib/api.js (axios instance + formatters)
- lib/catalog.js (catalog utilities)
- lib/utils.js (general utilities)

**UI Components:** 40+ shadcn/ui components in `components/ui/`

---

## Appendix B: Route Mapping

| Current Route | Component | Public/Protected |
|--------------|-----------|------------------|
| `/login` | Login | Public |
| `/` | HomeRoute (hostname-based) | Public/Protected |
| `/store/*` | Storefront | Public (9 routes) |
| `/admin` | Overview | Protected |
| `/products` | Products | Protected |
| `/catalogs` | Catalogs | Protected |
| `/orders` | Orders | Protected |
| `/reports` | Reports | Protected |
| `/inventory` | Inventory | Protected |
| `/deposits` | Deposits | Protected |
| `/users` | UsersPage | Protected |
| `/settings` | SettingsPage | Protected |
| `/broadcasts` | Broadcasts | Protected |
| `/central-broadcasts` | CentralBroadcasts | Protected |
| `/discounts` | Discounts | Protected |
| `/messages` | Messages | Protected |
| `/bot-moderation` | BotModeration | Protected |
| `/promotions` | Promotions | Protected |
| `/resellers` | Resellers | Protected |

---

**End of Admin Panel Audit**
