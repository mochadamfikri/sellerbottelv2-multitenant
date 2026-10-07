# IDSE Digital Product

**Agent handover terbaru:** baca [AGENT_HANDOVER.md](AGENT_HANDOVER.md) sebelum
melanjutkan pekerjaan. Dokumen tersebut merangkum rilis IDSE Marketplace, lokasi
backup, perlindungan data production, dan pengujian yang aman.

Telegram digital-product marketplace with an admin dashboard, per-product inventory, encrypted inventory records, deposits, discounts, and Telegram delivery.

## Current Fix: Product + Inventory Upload / Schema

This version fixes the inventory upload flow and documents the inventory contract.

### Root cause addressed

The upload button previously had a client-side state dependency that could prevent the upload handler from running. That was fixed in the frontend.

After the request reached the backend, the remaining HTTP 400 was caused by the inventory parser enforcing the product's existing schema with an opaque error. The backend now:

1. Accepts XLSX, CSV, and TXT inventory uploads.
2. Uses the first row of XLSX/CSV as the file header/schema.
3. If a digital product has no schema yet, a successful validation establishes that file header as the product schema.
4. If a product already has a schema, the uploaded file must contain the same field names.
5. Column order is allowed to differ.
6. Field comparison ignores surrounding whitespace and letter case.
7. Records are remapped to the canonical product schema before validation/import.
8. A schema mismatch returns a useful 400 message containing both the required schema and the received file headers.
9. The Products page displays the required inventory schema for every product.
10. The Manage Inventory page displays the same required schema before upload.
11. Product/service separation remains enforced: digital products use inventory; service products do not.

FastAPI file uploads use multipart/form-data with File/UploadFile. This project includes python-multipart in backend requirements.

---

## Product Types

### A. Produk Digital / Data

Digital products use per-product inventory.

- Inventory upload: enabled.
- Stock mode:
  - auto: stock follows available inventory.
  - manual: stock is capped by the configured manual stock and cannot exceed real available inventory.
- Inventory schema belongs to the product.
- Bulk upload is handled from the Product page and Manage Inventory page.
- Manual single-item input is handled from Manage Inventory.

### B. Produk Jasa

Service products do not use inventory.

- Inventory upload: disabled.
- Stock: Unlimited.
- Delivery can be:
  - Link
  - License
  - File

---

## Inventory Schema Contract

A product schema is a list of field names, for example:

```text
email · password · recovery_email · 2fa
```

An XLSX/CSV file should therefore have:

```text
email | password | recovery_email | 2fa
```

The actual separator depends on the file format.

### XLSX / CSV

- Row 1 is the header.
- Remaining rows are inventory records.
- Header names must match the product schema.
- Column order may differ.
- Case and surrounding whitespace are ignored.
- Different field names are not automatically guessed or translated.

Example:

Product schema:

```text
email · password · recovery_email · 2fa
```

This is accepted:

```text
2FA | EMAIL | Password | Recovery_Email
```

because field comparison is case-insensitive and order-independent.

This is rejected:

```text
email | kata sandi | recovery | 2fa
```

if the product schema is:

```text
email · password · recovery_email · 2fa
```

because kata sandi and recovery are different field names. The backend reports the expected and received headers in the 400 response.

### TXT

TXT supports pipe-separated fields:

```text
email|password|recovery_email|2fa
```

For a single-field schema, each non-empty line can be treated as one value.

---

## Schema Lifecycle

### New digital product

A newly created digital product may have no schema yet.

Flow:

1. Create the digital product.
2. Open Products → Input Data or Manage Inventory.
3. Upload an XLSX/CSV/TXT file.
4. Validate.
5. If the file is valid, its schema becomes the product's schema.
6. Import the validated inventory.
7. Future uploads must follow that schema.

The schema is shown on the Products page and Manage Inventory page.

### Existing digital product

If a product already has a schema:

1. Select the product.
2. Read the displayed required schema.
3. Prepare the file using those field names.
4. Validate.
5. Import.

Do not silently change field names between uploads.

---

## Admin Pages

### Products

The Products page manages ready-for-sale products.

Features:

- Product name and description.
- Product type.
- USD/IDR price.
- Active/inactive status.
- Stock mode for digital products.
- Unlimited status for services.
- Inventory schema column.
- Input Data / Inventory action for digital products.
- Excel product import.

The inventory schema is displayed directly in the product table.

### Manage Inventory

The Manage Inventory page is the dedicated inventory management area.

Features:

- Select an existing digital product.
- Show Available / Reserved / Sold counts.
- Show required product schema.
- Bulk XLSX/CSV/TXT upload.
- Validate upload before import.
- Import bulk inventory.
- Manual single-item input using the product schema.
- Filter inventory by status.
- Delete available inventory records.
- Sold inventory credentials are not exposed in the panel.

The page does not create products. Product selection always comes from the Products page data.

---

## Backend Inventory API

Base prefix:

```text
/api/admin
```

### List products

```http
GET /api/admin/products
```

Digital products include:

```json
{
  "product_kind": "digital",
  "inventory_enabled": true,
  "inventory_schema": ["email", "password", "recovery_email", "2fa"],
  "inventory_stock": 10,
  "stock_mode": "auto"
}
```

Service products include:

```json
{
  "product_kind": "service",
  "inventory_enabled": false,
  "stock": null,
  "stock_mode": "unlimited"
}
```

### Inventory list

```http
GET /api/admin/products/{pid}/inventory?status=available
```

### Validate upload

```http
POST /api/admin/products/{pid}/inventory/validate
Content-Type: multipart/form-data
```

Form fields:

- content: optional text input.
- file: XLSX, CSV, or TXT.

Successful response:

```json
{
  "schema": ["email", "password", "recovery_email", "2fa"],
  "valid_count": 10,
  "duplicate_count": 2,
  "preview": []
}
```

### Import upload

```http
POST /api/admin/products/{pid}/inventory/import
Content-Type: multipart/form-data
```

### Manual inventory

```http
POST /api/admin/products/{pid}/inventory/manual
Content-Type: application/json
```

Body:

```json
{
  "data": {
    "email": "example@example.com",
    "password": "example",
    "recovery_email": "recovery@example.com",
    "2fa": "123456"
  }
}
```

### Delete available inventory

```http
DELETE /api/admin/products/{pid}/inventory/{item_id}
```

Only available inventory can be deleted.

---

## Inventory Encryption

Inventory records are encrypted before being stored.

Implementation:

- backend/inventory.py
- Fernet encryption.
- SHA-256 fingerprint for duplicate detection.
- MongoDB stores encrypted inventory in inventory_items.

The encryption key is controlled by:

```text
INVENTORY_ENCRYPTION_KEY
```

Never replace this key after inventory data has been stored.

Generate a new key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Project Structure

```text
sellerbottel/
├── backend/
│   ├── .env
│   ├── .env.example
│   ├── server.py
│   ├── admin_routes.py
│   ├── admin_user_routes.py
│   ├── inventory.py
│   ├── auth.py
│   ├── db.py
│   ├── error_handlers.py
│   ├── bot.py
│   ├── join_gate.py
│   ├── tgapi.py
│   ├── services.py
│   ├── storage.py
│   ├── requirements.txt
│   └── ...
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Products.jsx
│   │   │   ├── Inventory.jsx
│   │   │   └── Users.jsx
│   │   ├── lib/
│   │   │   └── api.js
│   │   └── ...
│   ├── public/
│   ├── build/
│   ├── package.json
│   └── craco.config.js
│
└── README.md
```

---

## Important Inventory Code Responsibilities

### backend/admin_routes.py

Responsible for:

- Product CRUD.
- Product type normalization.
- Product stock mode.
- Product list data.
- Inventory upload endpoints.
- XLSX/CSV/TXT parsing.
- Inventory schema comparison.
- Inventory schema establishment.
- Admin inventory listing.

### backend/inventory.py

Responsible for:

- Inventory normalization.
- Fingerprinting.
- Duplicate detection.
- Encryption.
- Database insertion.
- Available stock count.
- Reservation/release/sold transitions.
- Decryption for admin display where allowed.

### backend/error_handlers.py

Provides JSON responses for inventory errors:

```json
{
  "detail": "..."
}
```

This prevents the frontend from hiding the actual inventory error behind a generic message.

### frontend/src/pages/Products.jsx

Responsible for:

- Product management UI.
- Product type selection.
- Product stock UI.
- Product schema display.
- Product-level inventory upload.

### frontend/src/pages/Inventory.jsx

Responsible for:

- Product selection.
- Required schema display.
- Bulk inventory upload.
- Validation/import actions.
- Manual inventory entry.
- Inventory table.

### frontend/src/lib/api.js

Creates the Axios API client:

```text
\${REACT_APP_BACKEND_URL}/api
```

and formats backend error responses.

---

## Required Backend Environment

Create:

```text
/opt/sellerbottel/backend/.env
```

Minimum required configuration:

```env
TELEGRAM_TOKEN=
TELEGRAM_WEBHOOK_SECRET=
WEBHOOK_SECRET=
PUBLIC_BASE_URL=https://idseshop.my.id
CORS_ORIGINS=https://idseshop.my.id
COOKIE_SAMESITE=lax
TRUST_PROXY=true

JWT_SECRET=
ADMIN_EMAIL=
ADMIN_PASSWORD=
ADMIN_TELEGRAM_ID=

MONGO_URL=mongodb://localhost:27017
DB_NAME=sellerbottel

INVENTORY_ENCRYPTION_KEY=

LOCAL_STORAGE_DIR=/opt/sellerbottel/backend/storage_data
```

### Optional GoPay / QRIS

Only required when the GoPay/QRIS integration is enabled:

```env
GOPAY_ENABLED=false
GOPAY_LOGIN_METHOD=email_otp
GOPAY_EMAIL=
GOPAY_PASSWORD=
GOPAY_PHONE=
GOPAY_QRIS_STRING=
GOPAY_POLL_INTERVAL=15
```

Do not commit the real .env file to Git.

---

## Frontend Environment

The production frontend reads its backend URL at build time.

Recommended:

```env
REACT_APP_BACKEND_URL=https://your-domain.example
```

For a same-domain deployment, the API is exposed under:

```text
https://your-domain.example/api
```

After changing frontend environment variables, rebuild the frontend.

## Customer Storefront

The customer storefront is served at `/` (also `/store`); the admin overview is at `/admin`, and the rest of the existing admin routes remain unchanged. The storefront reads active products, customer balances, orders, and discounts from the existing MongoDB collections and checkout service. Customers can register and sign in with verified email; linking Telegram is optional. Product stock and bot operations continue using the existing database and Telegram integrations.

Set `TELEGRAM_BOT_USERNAME` in `backend/.env` to the connected bot's username without `@`. The existing `TELEGRAM_TOKEN` and `JWT_SECRET` are used to verify Telegram login and sign the HTTP-only customer session cookie. No customer database or parallel order store is created.

The storefront uses `https://idseshop.my.id` as its public origin. Since DNS is not configured yet, apply the following when ready:

1. In the domain registrar's DNS page, add an `A` record with host `@` and value equal to the VPS public IPv4 address. If IPv6 is configured on the VPS, add its matching `AAAA` record too. Optionally add `CNAME` host `www` pointing to `idseshop.my.id`.
2. Allow inbound TCP ports 80 and 443 in the VPS firewall. Wait until `dig +short idseshop.my.id` returns the VPS address.
3. Update the existing Nginx HTTPS virtual host's `server_name` to include `idseshop.my.id`, set `root /opt/sellerbottel/frontend/build`, and serve SPA paths with `try_files $uri /index.html;`. Keep the existing `/api/` reverse proxy to `http://127.0.0.1:8000`.
4. Issue an HTTPS certificate for `idseshop.my.id` using the VPS's existing certificate workflow (for example, Certbot with the Nginx plugin), then verify `https://idseshop.my.id` loads the storefront and `/api/store/products` returns JSON.
5. In Telegram, send `/setdomain` to `@BotFather`, choose the bot used by `TELEGRAM_TOKEN`, and link `idseshop.my.id` for the login widget. Telegram requires the website domain to be linked before the widget can authorize sign-ins. [Telegram Login Widget setup](https://core.telegram.org/widgets/login/)
6. Set `PUBLIC_BASE_URL=https://idseshop.my.id`, add `https://idseshop.my.id` to the comma-separated `CORS_ORIGINS` list (preserving any other active admin origins), and set `TELEGRAM_BOT_USERNAME` (the bot username without `@`) in `backend/.env`. Keep cookies secure over HTTPS. Build the frontend and restart the backend only after DNS, Nginx, and HTTPS are ready.

`PUBLIC_BASE_URL` also controls the Telegram webhook URL. Restarting the backend after setting it will register the existing bot webhook on the custom domain.

Build the combined admin and customer frontend with:

```bash
cd /opt/sellerbottel/frontend
npm run build
```

---

## Production Deployment

### Backend

The current deployment uses a Python virtual environment:

```text
/opt/sellerbottel/backend/venv
```

Backend service:

```text
sellerbottel.service
```

Typical service commands:

```bash
systemctl restart sellerbottel
systemctl status sellerbottel --no-pager
```

Logs:

```bash
journalctl -u sellerbottel -f --no-pager
```

### Frontend

Build:

```bash
cd /opt/sellerbottel/frontend
npm run build
```

The production build is:

```text
frontend/build/
```

Nginx serves that directory.

Reload:

```bash
nginx -t && systemctl reload nginx
```

---

## Nginx Production Layout

Expected:

```text
server_name your-domain.example;
root /opt/sellerbottel/frontend/build;

location /api/ {
    proxy_pass http://127.0.0.1:8000;
}

location / {
    try_files $uri /index.html;
}
```

Do not expose backend/.env through Nginx.

---

## Verification Checklist

### 1. Backend

```bash
systemctl is-active sellerbottel
```

Expected:

```text
active
```

### 2. Frontend build

```bash
cd /opt/sellerbottel/frontend
npm run build
```

Expected:

```text
Compiled successfully
```

### 3. Nginx

```bash
nginx -t
```

Expected:

```text
syntax is ok
test is successful
```

### 4. Login

Open the admin dashboard and verify:

- GET /api/auth/me
- GET /api/admin/products

return 200.

### 5. Product schema

For every digital product:

- Schema column is visible.
- Existing schema is displayed.
- Empty schema explicitly says it is not yet established.

For service products:

- Inventory is disabled.
- Stock is Unlimited.

### 6. Inventory validation

Select a digital product and upload a valid file.

Expected backend log:

```text
POST /api/admin/products/<pid>/inventory/validate ... 200 OK
```

### 7. Inventory import

After successful validation:

```text
POST /api/admin/products/<pid>/inventory/import ... 200 OK
```

### 8. Stock

After import:

- Available inventory increases.
- Product stock in auto mode follows available inventory.
- Manual mode never exceeds real available inventory.

---

## Troubleshooting

### HTTP 400: schema mismatch

The backend now returns:

```text
Schema wajib: [...]
Header file: [...]
```

Make the file headers match the displayed product schema.

Column order does not matter.

### HTTP 400: invalid XLSX

The parser first uses openpyxl.

If that fails because an XLSX contains malformed/unsupported style metadata, the backend uses a direct XLSX XML fallback.

If both fail, the file itself is not a readable XLSX.

### HTTP 503: encryption configuration

Check that the variable exists without printing its secret value:

```bash
grep '^INVENTORY_ENCRYPTION_KEY=' /opt/sellerbottel/backend/.env
```

Then:

```bash
systemctl restart sellerbottel
journalctl -u sellerbottel -n 100 --no-pager
```

### Upload button produces no POST

Check:

```text
Browser → Network → inventory/validate
```

The request must reach:

```text
POST /api/admin/products/<pid>/inventory/validate
```

If there is no POST, inspect the frontend build/cache/event layer.

If a POST exists but returns 400, inspect the JSON detail; the backend now reports the expected and received schema.

### Backend only shows GET requests

The browser did not submit the upload request. This is a frontend/client issue, not an inventory parser issue.

---

## Data Safety

Inventory contains potentially sensitive account credentials.

Rules:

1. Never commit .env.
2. Never expose INVENTORY_ENCRYPTION_KEY.
3. Never paste raw inventory credentials into public logs.
4. Do not replace the encryption key while encrypted inventory exists.
5. Sold inventory is intentionally hidden from the admin table.
6. Use HTTPS for the admin dashboard.
7. Keep MongoDB inaccessible from the public internet unless explicitly secured.

---

## Change Summary

This fix changes the inventory contract without changing the product/business model:

- Digital products = inventory-backed.
- Service products = unlimited.
- Product schema is persistent.
- First successful inventory validation can establish an empty schema.
- Existing schema is enforced.
- Header order is flexible.
- Header case/whitespace is flexible.
- Schema mismatch errors are explicit.
- Products page shows schema.
- Manage Inventory shows schema.
- Bulk inventory remains available.
- Manual inventory remains available only through Manage Inventory.
- XLSX fallback remains supported.
- Inventory remains encrypted.

## Final Acceptance Criteria

The inventory feature is considered operational when all of these are true:

- [ ] Every digital product displays its inventory schema.
- [ ] Every service product clearly shows that inventory is not applicable.
- [ ] New digital products can establish a schema through their first valid inventory file.
- [ ] Existing products reject incompatible field names with a readable error.
- [ ] Existing products accept the same schema in a different column order.
- [ ] XLSX upload validates successfully.
- [ ] CSV upload validates successfully.
- [ ] TXT upload validates according to the product schema.
- [ ] Bulk import writes encrypted inventory records.
- [ ] Duplicate records are skipped.
- [ ] Stock follows available inventory in auto mode.
- [ ] Manual stock cannot exceed available inventory.
- [ ] Product page and Manage Inventory use the same schema contract.
- [ ] Backend logs show 200 for successful validation/import.
- [ ] INVENTORY_ENCRYPTION_KEY is configured and stable.


---

## Automation, Broadcast & Transaction Notifications

The admin panel now includes optional automation for product and transaction notifications.

### Automation settings

Under **Pengaturan → Automation & Broadcast**:

- **Auto Broadcast Product Baru**: when a new product is created/imported, a product notice is sent to the configured broadcast channel.
- **Transaction Success → Channel**: after a transaction is fully delivered, a privacy-safe public transaction notice is sent to the configured channel.
- **Auto Generate Picture**: enables automatic black/purple visual generation for supported product/transaction broadcasts.
- **Channel Broadcast ID**: explicit Telegram channel ID or @username used for channel broadcasts.
- **Target Join Group**: public group username/link or private invite link used by the connected-account join action.

The existing Telegram admin sales notification is intentionally unchanged and still contains buyer information. Only the channel notification is privacy-filtered.

### Transaction success channel format

Channel notifications intentionally contain no buyer name, username, or Telegram ID:

```text
🛒 Transaction Succes!!

Invoice: INV-20260923-0010
Produk: Netflix 1P2U ×5, WeTV Premium ×3, YT Premium 1 bulan akun Seller ×7
Total: Rp 286.000
Status: completed
```

### Automatic transaction image

When **Auto Generate Picture** is enabled, a black/purple image is generated from the completed transaction:

- total quantity of items/accounts
- total transaction value
- successful/completed status
- IDSE Network Connect Hub branding

The image is generated locally with Pillow; no external image-generation API is required.

### Broadcast page

**Broadcast → Broadcast Baru** supports:

- user targeting and existing language/status filters
- optional product selection
- optional automatic product image
- manual uploaded image
- button text and URL

**Broadcast ke Channel / Pengguna** supports:

- manual channel message
- all active products
- one selected product
- automatic discount/stock broadcast
- automatic product image for the selected product
- user queue broadcast

The global **Auto Generate Picture** setting must be enabled before automatic images can be generated.

### QRIS expiry

The storefront and Telegram payment flows label the code **QRIS All Payment**. QR validity comes from `GOPAY_QR_TIMEOUT_MINUTES` (default 5 minutes), with the admin setting `gopay_qr_timeout_minutes` taking precedence. Expired web QR images are hidden and the page offers a new checkout/deposit; Telegram removes the QR message and tells the customer to request a new code. Payment history is checked before expiry is finalized, so a verified payment made within the validity window is not lost just because polling happens later.

The GoPay active-payment index uses a numeric partial filter so documents with an absent/null `active_payment_amount` cannot collide with another active payment.

### Connected Telegram account → Join Group

The Users page shows a **Join Group** action when the customer has an active connected Telegram account. The action uses that connected account's Telethon session and the **Target Join Group** configured in Settings.

Supported target formats:

- public `@username`
- public `https://t.me/username`
- private invite link `https://t.me/+invitehash`
- legacy private invite link `https://t.me/joinchat/invitehash`

The connected Telegram account must have a valid active session.

---

## Production Update After Pulling These Changes

Run on the VPS:

```bash
cd /opt/sellerbottel

git pull origin main

cd backend
source venv/bin/activate

python -m pip install -r requirements.txt

python -m py_compile   db.py   services.py   gopay_provider.py   broadcast_image.py   admin_user_routes.py   admin_routes.py   bulk_product_import.py   bot.py

cd ../frontend
npm install
npm run build

systemctl restart sellerbottel
systemctl restart sellerbottel-dev-frontend

systemctl status sellerbottel --no-pager
systemctl status sellerbottel-dev-frontend --no-pager

nginx -t && systemctl reload nginx

journalctl -u sellerbottel -n 100 --no-pager
```

After deployment, open **Admin → Pengaturan** and configure:

1. Broadcast Channel ID.
2. Auto Broadcast Product Baru.
3. Transaction Success → Channel.
4. Auto Generate Picture.
5. Target Join Group.

Do not enable the transaction channel notice until the channel ID has been tested and the bot has permission to post there.

## Audit, Redesign, and Deployment Report — 2026-09-26

### Existing architecture

- Backend: Python FastAPI, asynchronous Motor client, MongoDB.
- Frontend: React with CRACO and Tailwind CSS. Nginx serves `frontend/build` for `idseshop.my.id` and `idsedm.duckdns.org`; `/api/` proxies to the existing `sellerbottel` systemd service on port 8000.
- Existing MongoDB collections are reused, including `products`, `inventory_items`, `bot_users`, `store_customers`, `purchases`, `deposits`, `gopay_payments`, `settings`, and promotion/coupon collections.
- Telegram bots and their payment/inventory paths remain in the existing backend. No parallel database, user model, payment gateway, or bot was created.

### Implemented changes

- Reworked the customer storefront into a responsive light marketplace layout, branded as **IDSE Digital Product**. Replaced Emergent branding and its overlay dependencies. The product catalog sorts available stock first and offers Terlaris, Ready Stock, Out of Stock, and Jasa Payment filters.
- Added product-specific artwork fallback, product labels, a square product image display, and mutually exclusive auth navigation: signed-in users see Keluar; signed-out visitors see Masuk and Daftar. The same rule applies to desktop and mobile menus.
- Added email registration/login, OTP verification, password reset, customer profile/history, optional Telegram linking, and a one-time web-wallet-to-Telegram-wallet transfer. Unlinked accounts keep and spend their web balance; linked accounts spend the Telegram balance after the merge.
- Store checkout supports QRIS and saldo. QRIS checkout is a direct verified payment; saldo checkout calls the existing wallet checkout implementation. The web QRIS setting is separate from the Telegram bot switch.
- Deposit and checkout QR images are labelled QRIS All Payment, show supported QRIS-capable e-wallet/mobile-banking instructions, and expire after 5 minutes by default. Admin can change the QR lifetime and toggle storefront QRIS in **Admin → Pengaturan → Gateway Pembayaran → QRIS Front Store**. Telegram removes expired QR messages and sends a replacement-request message.
- Admin product editing supports image upload, preview, replacement, removal, and per-product minimum purchase. Uploads accept JPG/PNG/WEBP up to 5 MB; the backend validates MIME/content/dimensions, normalizes images to a 1200 × 1200 WebP canvas without cropping, and stores them through the existing storage adapter. No database migration was needed.
- Coupon create/edit now uses shared validation and supports one selected product or all products. The admin customer search includes email-only web accounts as well as linked Telegram users.
- Completed web orders send an email once, after completion. Session files are bundled as ZIP and account inventory as TXT. SMTP settings are read from the existing environment variables; no credentials are stored in source.
- Added configurable WhatsApp/Telegram contact bubbles, with a two-minute lifetime and a prefilled product inquiry.

### Bug causes and fixes

- **QRIS deposit/checkout unavailable:** the active database had the Telegram `qris_enabled` setting OFF while bank transfer was ON. Web routes previously checked this same bot switch, so web QRIS was rejected even though the GoBiz QRIS configuration was present. Web now has an independent `store_qris_enabled` setting, defaulted from `GOPAY_ENABLED`; this leaves bot payment settings unchanged. Control it in the Admin settings page noted above.
- **Customer search “not found”:** the original admin search only queried `bot_users`; email-only records in `store_customers` were not considered. The new endpoint searches web email and joins Telegram username/name/ID when linked, with escaped search text and a bounded result set.
- **Coupon edits and discount consistency:** the old coupon update endpoint wrote request fields directly, while create used validated normalization. Edit could therefore leave data that differed from checkout rules. Create/edit now share validation; checkout applies the same product-scoped eligibility, minimum, limit, timezone, and capped-discount rules as the admin data.

### Database, settings, and recovery

- No database reset, collection drop, truncate, destructive seed, or full snapshot restore was performed for this deployment. No new collection is required; settings use existing `settings` and are merged with defaults for older records. Startup retains safe, idempotent indexes.
- A protected pre-deployment database dump was created outside the repository. No database reset, collection drop, truncate, destructive seed, or full snapshot restore was performed. An older snapshot was not restored because the active database contained newer activity.
- Existing production secrets remain in the server-side `.env`; no secret values or backup files are included in this repository. The malformed `GOPAY_POLL_INTERVAL` line ending was corrected. `GOPAY_QR_TIMEOUT_MINUTES` is the fallback variable (default 5); the admin setting takes precedence.

### Verification and remaining checks

- Frontend production build: passed.
- Backend syntax compilation: passed.
- Targeted tests: 14 passed across checkout/expiry, discount validation, and storefront authentication; only dependency deprecation warnings were reported.
- The broad legacy backend suite was not rerun because it previously wrote to the active database. Do not use it against production without an isolated test database.
- QRIS and SMTP configuration entries are present, but no live payment or external email delivery was performed. Verify a low-value QRIS payment and OTP/order emails after deployment. Never mark a payment paid manually based only on the customer pressing a button.
- The supplied Google Drive reference was not readable from this environment, and no marked-up screenshots were present in the repository; the redesign follows the written brief.
- Files changed are grouped in the backend API/payment/auth/admin modules (`admin_routes.py`, `admin_user_routes.py`, `bot.py`, `bot2.py`, `checkout.py`, `db.py`, `direct_checkout.py`, `gopay_provider.py`, `promo_*`, `services.py`, `storage.py`, `storefront_routes.py`, and related modules/tests) and frontend routing, admin pages, product/settings pages, and the new `Storefront.jsx`.
- No new backend runtime dependency was added. Emergent overlay packages were removed; npm lock files were generated for reproducible installation.

### Deploy and manual setup

- Nginx serves the generated frontend directly from `frontend/build`; there is no separate frontend systemd service on this VPS. The backend service is `sellerbottel`.
- Storefront QRIS now defaults ON only when `GOPAY_ENABLED=true` and can be independently switched in Admin settings. Telegram bot QRIS remains controlled by its existing `qris_enabled` setting.
- Optional `STORE_QRIS_ENABLED` overrides the initial storefront QRIS default; if absent, it follows `GOPAY_ENABLED`. The Admin toggle remains the day-to-day control. Existing `GOPAY_QRIS_STRING`, credentials, and poll interval are shared with the bot.
- The web checkout payment selector offers QRIS and Saldo IDR. Accounts without Telegram use their web balance; linked accounts use the Telegram balance after the one-time merge. Deposits still use QRIS and credit whichever wallet is canonical for that account.
- Deployment status: **deployed**. `sellerbottel` restarted successfully; Nginx serves the new frontend build for both domains. Smoke checks returned 200 for `/api/store/config`, both public domains, and the new JavaScript bundle; protected deposits correctly returned 401 without a session, and quote returned validation response 422 rather than the old 404. The initial config smoke check found a missing `get_settings` import; it was fixed, the backend restarted again, and the endpoint then returned 200.
- No authenticated real-money charge was created for testing. The live QR and SMTP delivery still need a low-value/manual acceptance check.
