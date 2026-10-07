# IDSE Digital Product — Implementation Report

This file summarizes the audit, storefront work, admin fixes, and deployment for the existing IDSE Digital Product system.

## Existing architecture

- Backend: Python FastAPI, Motor, and MongoDB.
- Frontend: React, CRACO, and Tailwind CSS.
- Nginx serves the existing frontend build and proxies API requests to the existing backend service.
- The website reuses the existing products, inventory, users, purchases, deposits, QRIS payments, settings, and coupon data. Telegram bot flows and the existing database were retained.

## Implemented

- Redesigned the storefront as a responsive, light marketplace under the IDSE Digital Product brand. Product availability is prioritized, with filters for Terlaris, Ready Stock, Out of Stock, and Jasa Payment.
- Added email registration and login, OTP verification, password reset, profile/order history, optional Telegram linking, and one-time web-balance transfer when accounts are linked.
- Checkout offers verified QRIS and wallet balance. Email-only accounts use their web wallet; linked accounts use the Telegram wallet after the one-time merge.
- QRIS is labelled “QRIS All Payment.” Web QRIS has its own admin toggle, while the Telegram payment setting remains separate. QR expiry defaults to five minutes, is configurable in the admin panel, and expired QR images are hidden or replaced with expiry guidance.
- Added product image upload, preview, replacement, and removal. JPG/PNG/WEBP uploads are validated and normalized to a 1200 × 1200 WebP canvas without cropping. Per-product minimum purchase is supported.
- Coupon create/edit uses shared validation and supports either one product or all products. Admin customer search includes web-only accounts and linked Telegram identities.
- Completed orders send one email after completion; session-file products use ZIP attachments and account products use TXT attachments.
- Added configurable WhatsApp/Telegram contact bubbles with a two-minute display lifetime and a product inquiry message.
- Corrected signed-in navigation so it shows Keluar, while signed-out navigation shows Masuk and Daftar.

## Root causes addressed

- Web deposit and checkout used to depend on the Telegram `qris_enabled` setting. A separate `store_qris_enabled` setting now controls storefront QRIS without changing the bot switch.
- Admin customer search queried Telegram users only. It now includes email-only web customers and linked Telegram details.
- Coupon edits previously bypassed the validation and normalization used on creation. Both paths now share the same rules used by checkout.

## Data and configuration

- No database reset or destructive restore was performed. Existing collections and records were reused, and a protected database backup was created outside the repository before deployment.
- Secrets remain in server-side `.env` files. Only empty placeholders and variable names are committed in `.env.example`.
- Store QRIS can be enabled or disabled in **Admin → Pengaturan → Gateway Pembayaran → QRIS Front Store**. Existing GoBiz/QRIS provider settings are shared with the bot; the storefront enable switch is independent.
- SMTP and QRIS provider credentials must be configured on the server. No live payment or external email delivery was generated during smoke checks.

## Verification and deployment

- Frontend production build passed.
- Backend syntax compilation passed.
- Targeted tests passed: 14 across checkout/expiry, coupon validation, and storefront authentication.
- Production backend restarted successfully. Store config and both public domains returned HTTP 200; protected endpoints correctly required authentication.
- A low-value QRIS payment and real OTP/order email delivery still need manual acceptance checks.

See [README.md](README.md) for the full project and deployment documentation.
