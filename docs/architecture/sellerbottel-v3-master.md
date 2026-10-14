# SellerBottel V3 — Master Architecture
## Payment Architecture + Physical Commerce Architecture

**Status:** Architecture Draft for Implementation Planning
**Target:** `/home/sellerbottelv2/` development codebase
**Scope:** Extend SellerBottel V2 from digital-first multitenant commerce into a broader multitenant commerce platform that supports digital products, physical products, services, subscriptions, hybrid payments, tenant-owned branding, and future white-label operation.

---

# 1. Product Vision

SellerBottel should no longer be treated as only a bot for selling digital accounts or virtual inventory.

The target vision is:

```text
SELLERBOTTEL
= MULTITENANT COMMERCE INFRASTRUCTURE

Tenant
= Independent Brand / Merchant

Customer
= Buyer of that tenant

SellerBottel
= The commerce engine behind the tenant
```

The tenant should feel that:

```text
"This is my store, my brand, my bot, my domain, my payment setup."
```

not:

```text
"I am only selling inside SellerBottel."
```

SellerBottel should increasingly become invisible infrastructure while each tenant owns the customer-facing identity.

---

# 2. Core Product Principles

## 2.1 Tenant-first branding

Every tenant should be able to own:

- store name
- logo
- favicon
- primary color
- secondary color
- storefront theme
- bot name
- bot branding
- domain/custom domain
- WhatsApp
- Telegram
- social links
- invoice branding
- receipt branding
- email sender name
- storefront description
- contact identity

SellerBottel branding may remain visible depending on package.

Example packaging:

```text
Basic
→ Powered by SellerBottel

Pro
→ Tenant branding dominant

Business
→ White-label capable

Enterprise
→ Full white-label / custom identity
```

---

# 3. Commerce Domain Model

SellerBottel should use one commerce core for all product types.

Do not create isolated checkout systems for digital, physical, service, and subscription products.

Use:

```text
Browse
→ Cart
→ Quote
→ Checkout
→ Payment
→ Order
→ Fulfillment Router
```

The checkout/payment layer should not care how the product is fulfilled.

Fulfillment behavior starts after payment or another fulfillment trigger.

---

# 4. Fulfillment Types

Do not limit the architecture to only:

```text
digital
physical
```

Use a future-proof field:

```text
fulfillment_type
```

Recommended values:

```text
digital_auto
digital_manual
service
physical
subscription
```

Meaning:

## digital_auto

Examples:

- account
- license
- link
- file
- session
- redeem code

Typical behavior:

```text
payment confirmed
→ reserve/consume digital inventory
→ automatic delivery
→ delivered
```

## digital_manual

Examples:

- manual account fulfillment
- custom digital asset
- manually issued access

Behavior:

```text
payment confirmed
→ create fulfillment task
→ tenant/admin fulfills manually
→ delivered
```

## service

Examples:

- KYC service
- setup service
- verification service
- custom work

Behavior:

```text
payment confirmed
→ queue
→ processing
→ completed
```

## physical

Examples:

- shoes
- clothes
- jackets
- hats
- electronics
- accessories
- general retail goods

Behavior:

```text
payment confirmed
→ reserve/consume stock
→ packing
→ ready_to_ship
→ shipped
→ delivered
```

## subscription

Future-proof support for:

- recurring SaaS
- membership
- renewal entitlement
- recurring service

Do not implement recurring billing until explicitly approved, but keep the model extensible.

---

# 5. Product Model

The current digital-first product model should evolve into a general product entity.

Recommended conceptual fields:

```text
product
├── id
├── tenant_id
├── name
├── slug
├── description
├── category_id
├── brand
├── fulfillment_type
├── active
├── base_price
├── currency
├── tax_behavior
├── requires_shipping
├── has_variants
├── image/media
├── created_at
└── updated_at
```

Digital-specific fields and physical-specific fields should not be forced into the same flat schema.

Use extension structures or type-specific data.

---

# 6. Product Variants and SKU

Physical commerce requires variants.

Example:

```text
Product:
Hoodie UrbanDistrict

Variants:
Black / S
Black / M
Black / L
White / M
White / L
```

Each sellable physical variant should have a SKU.

Example:

```text
HUD-BLK-S
HUD-BLK-M
HUD-BLK-L
HUD-WHT-M
HUD-WHT-L
```

Recommended variant fields:

```text
variant
├── id
├── product_id
├── sku
├── barcode
├── option_values
├── price_override
├── weight
├── length
├── width
├── height
├── active
└── media_override
```

SKU should identify the sellable inventory unit.

Do not attach all physical stock only to the parent product if variants exist.

---

# 7. Inventory Architecture

Digital inventory and physical inventory are fundamentally different.

## 7.1 Digital inventory

Existing digital logic may continue to support structured records such as:

```text
email
password
recovery
license
file
session
link
```

Digital inventory can remain item-oriented.

Example:

```text
inventory_item
status:
available
reserved
sold
invalid
```

## 7.2 Physical inventory

Physical inventory should use stock quantities and a stock movement ledger.

Do not use only:

```text
product.stock = 20
```

Recommended stock concepts:

```text
on_hand
reserved
available
```

Formula:

```text
available = on_hand - reserved
```

Use stock movement records:

```text
RECEIVE       +10
SALE           -1
RETURN         +1
DAMAGE         -1
ADJUSTMENT     +/-n
RESERVATION    -1 available
RELEASE        +1 available
```

Recommended entity:

```text
stock_movement
├── id
├── tenant_id
├── variant_id / sku
├── branch/location_id
├── type
├── quantity
├── reference_type
├── reference_id
├── actor
├── reason
└── created_at
```

This makes stock auditable.

---

# 8. Stock Reservation

Reservation should be a shared commerce capability.

Both digital and physical stock can use reservation concepts.

Typical flow:

```text
checkout created
→ stock reserved
→ payment pending
```

If payment succeeds:

```text
reservation
→ consumed
```

If payment expires/fails:

```text
reservation
→ released
```

Reservation must be idempotent.

A repeated payment event must not consume inventory twice.

---

# 9. Mixed Orders

SellerBottel should support a single order containing different fulfillment types.

Example:

```text
ORDER #SB-001

1x Gemini AI Pro
→ digital_auto

1x Hoodie Black L
→ physical

1x VPS Setup Service
→ service
```

Customer pays once.

The order should then create separate fulfillment records.

Example:

```text
ORDER #SB-001
│
├── Fulfillment F1
│   type: digital_auto
│
├── Fulfillment F2
│   type: physical
│
└── Fulfillment F3
    type: service
```

---

# 10. Order State

Recommended global order status:

```text
draft
pending_payment
paid
partially_fulfilled
fulfilled
completed
cancelled
refunded
partially_refunded
```

Do not use one global status to describe all fulfillment details.

Fulfillment records must have their own states.

---

# 11. Fulfillment State Machines

## 11.1 Digital auto

```text
reserved
→ delivering
→ delivered

failure:
→ delivery_failed
```

## 11.2 Digital manual

```text
pending
→ processing
→ delivered
```

## 11.3 Service

```text
queued
→ processing
→ completed

optional:
cancelled
failed
```

## 11.4 Physical

```text
pending
→ packing
→ ready_to_ship
→ shipped
→ delivered

alternative:
cancelled
return_requested
returned
```

---

# 12. Fulfillment Router

Avoid scattered code such as:

```python
if product_kind == "digital":
    ...
elif product_kind == "physical":
    ...
elif product_kind == "service":
    ...
```

in many files.

Use a fulfillment registry.

Concept:

```python
handler = fulfillment_registry.get(item.fulfillment_type)
await handler.process(...)
```

Suggested structure:

```text
commerce/
├── fulfillment/
│   ├── base.py
│   ├── registry.py
│   ├── digital_auto.py
│   ├── digital_manual.py
│   ├── service.py
│   ├── physical.py
│   └── subscription.py
```

---

# 13. Shipping Architecture

Physical products require shipping support.

Recommended domain:

```text
shipping/
├── addresses.py
├── rates.py
├── shipments.py
├── tracking.py
└── providers/
```

Shipping should be provider-independent.

Suggested adapter interface:

```text
get_rates()
create_shipment()
cancel_shipment()
track_shipment()
```

Possible providers in the future:

```text
RajaOngkir
Biteship
Shipper
Manual Courier
Pickup
```

Do not hard-code business logic to one shipping provider.

---

# 14. Customer Address

Physical checkout should support shipping addresses.

Recommended fields:

```text
recipient_name
phone
address_line_1
address_line_2
district
city
province
postal_code
country
notes
```

Address records should belong to the customer within the tenant context.

Tenant A customer address data must never be visible to Tenant B.

---

# 15. Shipping Modes

Tenant should be able to select:

```text
manual_shipping
integrated_shipping
pickup_only
```

## manual_shipping

Tenant determines shipping manually.

## integrated_shipping

SellerBottel requests courier rates through a provider.

## pickup_only

No shipping provider needed.

---

# 16. Order Pricing

Recommended order calculation:

```text
items_subtotal
- discount
+ shipping
+ tax
+ payment_fee
= grand_total
```

Shipping fee belongs to the order/quote.

Payment only pays the final amount.

Do not make shipping fee a payment-provider-specific concept.

---

# 17. Payment Architecture

Payment should pay an order, independent of product type.

Do not create:

```text
digital payment
physical payment
```

Use:

```text
Payment
→ Order
```

One payment can cover mixed digital/physical/service items.

---

# 18. Tenant Payment Modes

SellerBottel should support two primary tenant payment modes.

```text
payment_mode

platform_settlement
self_gateway
```

User-facing names:

```text
1. Settlement IDSE
2. Gateway Saya Sendiri
```

---

# 19. Settlement IDSE

Settlement IDSE should use the IDSE-controlled Kasera gateway, not the personal GoPay Merchant account.

Reasoning:

- GoPay Merchant is better isolated for IDSE personal bot/webshop use.
- Multitenant transaction volume should not depend on the same personal merchant account.
- A single suspension/failure should not risk mixing personal business activity with tenant settlement activity.
- Kasera offers broader payment options such as QRIS and Virtual Account channels.

Conceptual flow:

```text
Customer
↓
Tenant checkout
↓
Settlement IDSE
↓
Kasera IDSE
↓
QRIS / VA / available methods
↓
Payment success
↓
Order paid
↓
Settlement ledger
↓
Tenant available balance
↓
Payout
```

---

# 20. Gateway Individu Tenant

A tenant may instead connect their own gateway.

Planned provider options may include:

```text
Kasera
Midtrans
DOKU
GoPay Merchant
OttoPay
Stripe
```

Future providers may be added through adapters.

SellerBottel must not assume every provider uses exactly one API key.

Different providers may require different credentials.

Examples:

```text
Kasera
- API Key

Midtrans
- Server Key
- Client Key
- Merchant ID

Stripe
- Secret Key
- Webhook Secret
```

The UI should dynamically render the credential form for the selected provider.

---

# 21. Payment Provider Adapter

Suggested structure:

```text
payments/
├── orchestrator.py
├── router.py
├── models.py
├── webhook.py
├── settlement.py
├── ledger.py
└── providers/
    ├── base.py
    ├── registry.py
    ├── kasera.py
    ├── midtrans.py
    ├── doku.py
    ├── gopay.py
    ├── ottopay.py
    └── stripe.py
```

Suggested common interface:

```text
connect()
get_capabilities()
create_payment()
get_payment()
verify_webhook()
cancel_payment()
refund()
```

Checkout code should not care which provider is selected.

---

# 22. Capability Discovery

After a tenant enters provider credentials:

```text
[Test Connection]
```

Backend should:

```text
authenticate provider
↓
validate credentials
↓
fetch merchant/account info where supported
↓
fetch supported payment methods
↓
save capabilities snapshot
```

Tenant UI can show:

```text
Connected ✓

Available:
✓ QRIS
✓ BCA VA
✓ BNI VA
✓ GoPay
✗ Credit Card
```

Do not hard-code that every merchant account has every method.

---

# 23. Provider vs Payment Method

Keep these concepts separate.

Bad:

```text
payment_method = midtrans
```

Better:

```text
provider = midtrans
method = qris
```

Examples:

```text
provider = kasera
method = va_bca

provider = midtrans
method = qris

provider = stripe
method = card
```

---

# 24. Payment Record

Recommended conceptual payment entity:

```text
payment
├── id
├── tenant_id
├── order_id
├── payment_mode
├── provider
├── method
├── amount
├── currency
├── status
├── provider_payment_id
├── provider_event_id
├── expires_at
├── paid_at
├── created_at
└── updated_at
```

Recommended statuses:

```text
created
pending
paid
expired
failed
cancelled
refunded
partially_refunded
```

---

# 25. Payment Routing Index

Webhook handling must not scan every tenant database.

Use a platform-level routing index.

Example:

```text
payment_routes
├── provider
├── provider_payment_id
├── tenant_id
├── tenant_database
├── order_id
├── payment_mode
└── created_at
```

Webhook flow:

```text
provider webhook
↓
verify signature
↓
lookup payment route
↓
resolve tenant
↓
open tenant DB
↓
atomic payment transition
↓
order transition
↓
fulfillment
↓
settlement accounting if applicable
```

---

# 26. Webhook Idempotency

Payment webhook processing must be idempotent.

If a provider sends the same event multiple times:

```text
payment transition once
inventory consume once
settlement ledger entry once
fulfillment once
```

Use unique constraints such as:

```text
provider_event_id
provider_payment_id
```

and atomic state transitions.

---

# 27. Settlement Ledger

Settlement IDSE must not use a mutable balance field as the only source of truth.

Do not rely on:

```text
tenant.balance = 100000
```

Use an immutable or append-only ledger.

Example:

```text
PAYMENT_GROSS      +100,000
GATEWAY_FEE          -1,000
PLATFORM_FEE         -2,000
NET_AVAILABLE       +97,000
```

Recommended settlement states:

```text
pending
clearing
available
reserved
paid_out
refunded
disputed
```

Balance should be derived from ledger entries.

---

# 28. Settlement Delay

A successful customer payment should not necessarily become instantly withdrawable.

Recommended flow:

```text
paid
→ pending
→ clearing
→ available
```

The delay can later be configured according to:

- provider settlement behavior
- risk policy
- refund window
- fraud/dispute exposure
- tenant tier

---

# 29. Tenant Payout

Settlement mode should support payout records.

Recommended payout statuses:

```text
requested
reviewing
processing
paid
failed
rejected
cancelled
```

Tenant payout configuration:

```text
bank_name
account_number
account_holder
verification_status
```

Do not delete payout history.

Keep complete audit records.

---

# 30. Refund Architecture

Refund must be separated from fulfillment return.

## Self Gateway

```text
SellerBottel
→ tenant provider adapter
→ refund through tenant gateway
```

## Settlement IDSE

```text
SellerBottel
→ Kasera IDSE refund/reversal flow
→ settlement ledger reversal
```

If the tenant has already received payout and a later refund creates liability:

```text
negative settlement / tenant liability
```

must be recorded.

Do not silently absorb it.

---

# 31. Return vs Refund

These concepts must remain separate.

```text
Return
= physical goods workflow

Refund
= financial workflow
```

Physical return example:

```text
return_requested
→ approved
→ return_shipped
→ received
→ inspected
→ restock / damaged
→ refund
```

Digital products may have completely different refund policies.

---

# 32. Payment Security

Tenant gateway credentials must be:

- encrypted at rest
- never returned in full after saving
- excluded from logs
- excluded from error traces
- never exposed to browser after save
- scoped to tenant
- revocable
- testable through a backend "Test Connection" action

Frontend should receive only masked metadata:

```json
{
  "provider": "midtrans",
  "configured": true,
  "server_key_masked": "••••••42"
}
```

---

# 33. Settlement IDSE Risk Separation

Keep platform settlement credentials separate from:

- IDSE personal webshop credentials
- IDSE personal bot payment credentials
- tenant-owned gateway credentials

Recommended conceptual config boundaries:

```text
platform_payment_credentials
tenant_payment_credentials
personal_idse_payment_credentials
```

They should never share runtime assumptions accidentally.

---

# 34. Tenant Admin Expansion

Recommended navigation:

```text
Dashboard

Commerce
├── Products
├── Categories
├── Variants
├── Inventory
├── Orders
├── Returns
└── Customers

Payments
├── Payment Settings
├── Transactions
├── Settlement
└── Payout

Shipping
├── Providers
├── Rates
└── Shipments

Marketing
├── Coupons
├── Broadcast
└── Analytics

Store
├── Branding
├── Domain
├── Bot
└── Storefront
```

Visibility can depend on tenant plan and feature status.

---

# 35. Tenant Payment Settings UX

Recommended top-level choice:

```text
Bagaimana Anda ingin menerima pembayaran?

◉ Settlement IDSE
  Tidak perlu memiliki payment gateway sendiri.
  Gunakan metode pembayaran yang tersedia melalui IDSE.
  Dana masuk ke saldo settlement dan dapat dicairkan.

○ Gateway Saya Sendiri
  Hubungkan payment gateway milik Anda.
  Dana langsung diproses oleh akun gateway Anda.
```

If `Settlement IDSE`:

```text
Available methods
Settlement balance
Pending balance
Available balance
Payout account
Payout history
```

If `Gateway Saya Sendiri`:

```text
Provider
Environment
Credentials
Test Connection
Connected capabilities
Webhook status
```

---

# 36. Customer Payment UX

Customer should normally see payment methods, not infrastructure provider names.

Example:

```text
Pilih Pembayaran

QRIS
BCA Virtual Account
BNI Virtual Account
BRI Virtual Account
GoPay
Credit Card
```

Provider may remain hidden unless the tenant wants it displayed.

---

# 37. Tenant Branding Architecture

Recommended tenant branding fields:

```text
brand_name
logo
favicon
primary_color
secondary_color
font
store_description
domain
telegram_bot
whatsapp
email_sender_name
invoice_logo
receipt_footer
social_links
```

These should affect:

- storefront
- tenant bot
- checkout
- invoice
- email
- tracking page
- receipt
- customer notifications

---

# 38. White Label

White-label capability should be a product feature, not a fork.

Recommended behavior:

```text
branding_mode:
platform
co_branded
tenant_only
```

Possible policy:

```text
Basic
→ platform/co-branded

Pro
→ tenant dominant

Business/Enterprise
→ tenant_only allowed
```

Do not maintain separate frontend codebases per tenant.

---

# 39. Multitenant Boundaries

All new commerce domains must obey the current tenant isolation model.

Never allow:

- cross-tenant product access
- cross-tenant customer access
- cross-tenant address access
- cross-tenant shipment access
- cross-tenant payment access
- cross-tenant settlement access
- cross-tenant gateway credential access

Provider webhook routing must resolve the correct tenant before reading tenant business data.

---

# 40. Migration Principles

The current V2 digital commerce behavior should remain compatible during migration.

Do not perform a "big bang" replacement.

Recommended migration:

```text
Current V2 product
→ add fulfillment_type
→ default existing digital products appropriately
→ preserve current digital inventory behavior
→ add physical product extension
→ add variant/SKU model
→ add new fulfillment router
```

Existing digital checkout should keep working during transition.

---

# 41. Backward Compatibility

Current existing flows should not break:

- Telegram `/start`
- product browsing
- digital inventory
- cart
- coupon
- balance checkout
- QRIS/mock checkout
- order history
- service products
- tenant admin
- tenant isolation

The new commerce system should wrap/generalize existing flows rather than replace stable functionality without migration tests.

---

# 42. Implementation Phases

Do not implement all features in one Codex task.

## Phase C1 — Commerce Foundation

Goal:

```text
generalized commerce model
```

Implement:

- `fulfillment_type`
- order item normalization
- fulfillment record model
- fulfillment router interface
- migration/defaults for existing products
- regression tests for old digital behavior

No shipping provider yet.

## Phase C2 — Physical Commerce MVP

Implement:

- physical product type
- variants
- SKU
- physical stock quantities
- stock movement ledger
- stock reservation
- customer shipping address
- manual shipping mode
- packing
- shipped
- delivered
- mixed order support

No automated courier integration yet.

## Phase P1 — Payment Core

Implement:

- payment orchestrator
- provider adapter base
- provider registry
- payment routing index
- payment record
- webhook idempotency framework
- encrypted tenant payment credentials
- capability model
- test connection infrastructure

Do not implement all providers yet.

## Phase P2 — Settlement IDSE

Implement:

- Kasera IDSE provider adapter
- settlement mode
- settlement ledger
- pending/clearing/available balances
- payout account model
- payout request state machine
- refund/reversal accounting
- sandbox/dev tests

No real production settlement until separately approved.

## Phase P3 — Tenant Own Gateway

Start with:

```text
Kasera
Midtrans
```

Implement:

- provider-specific credential schemas
- test connection
- capabilities
- payment creation
- webhook verification
- refund where supported

After stable acceptance:

```text
DOKU
GoPay Merchant
OttoPay
Stripe
```

Add one provider at a time.

## Phase S1 — Shipping Integration

Implement shipping provider interface.

Then add providers incrementally.

Possible initial integration:

```text
RajaOngkir / Biteship / selected provider
```

Exact provider should be decided separately before implementation.

## Phase R1 — Returns & Refund

Implement:

- physical return request
- approval
- inbound return shipment
- received
- inspection
- restock/damaged decision
- refund trigger
- financial reconciliation

## Phase B1 — Branding & White Label

Implement:

- expanded tenant branding
- email branding
- invoice branding
- checkout branding
- tracking page branding
- package-controlled white-label mode

---

# 43. Acceptance Principles

Every phase must include:

- backend tests
- frontend tests where relevant
- multitenant isolation tests
- real Mongo dev validation
- lifecycle compatibility
- failure injection
- idempotency tests
- rollback tests
- secret-safe logging
- no production dependency

No phase should be marked complete with known P0/P1 failures.

---

# 44. Key P0 Risks

Treat these as P0:

- Tenant A seeing Tenant B products/orders/customers/payments
- wrong tenant payment routed
- webhook credited to wrong tenant
- settlement ledger duplicate credit
- duplicate fulfillment
- stock consumed twice
- payout created twice
- tenant gateway secret leak
- payment routed through wrong credentials
- physical stock crossover between tenant DBs
- order mixed fulfillment losing one fulfillment type
- refund applied to wrong merchant/provider

---

# 45. Key P1 Risks

Examples:

- physical stock reservation broken
- variant inventory mismatch
- shipping fee omitted from order total
- settlement available balance incorrect
- payout state stuck
- return does not restore stock correctly
- old digital checkout regression
- provider capability detection incorrect
- failed upload/storage cleanup regression

---

# 46. Non-goals for First Physical Commerce Release

Do not require initially:

- warehouse management
- multi-warehouse routing
- advanced procurement
- dropshipping automation
- international customs
- recurring subscriptions
- complex tax engine
- omnichannel POS
- marketplace seller-to-seller model
- automatic fraud scoring
- production settlement with real money before sandbox acceptance

Keep the first release focused.

---

# 47. Recommended First Physical MVP

A good first target:

```text
Tenant can:
- create physical product
- create variants
- assign SKU
- set stock
- upload product images
- receive customer address
- calculate/store manual shipping fee
- accept payment
- reserve stock
- mark packing
- mark shipped
- add tracking number
- mark delivered
```

Customer can:

```text
browse
select variant
add to cart
checkout
enter address
pay
see order status
see tracking number
```

This is enough to prove real physical commerce before adding courier APIs.

---

# 48. Recommended First Payment MVP

A good first target:

```text
Payment Mode A:
Settlement IDSE
→ Kasera sandbox/dev
→ QRIS/VA capability
→ settlement ledger

Payment Mode B:
Gateway Saya Sendiri
→ Kasera tenant-owned
→ Midtrans tenant-owned
```

Do not implement six providers at once.

Architecture should support them, but provider integrations should be added progressively.

---

# 49. Future Product Positioning

Potential positioning:

```text
SellerBottel

Build your own store.
Sell digital, physical, and services.
Use your own brand.
Use your own domain.
Use your own bot.
Choose your own payment.
```

Or:

```text
SellerBottel
Multitenant Commerce Infrastructure
```

The value proposition is not merely a bot.

It is:

```text
Commerce infrastructure where every tenant can become their own brand.
```

---

# 50. Final Architecture Summary

```text
SELLERBOTTEL PLATFORM
│
├── Tenant Identity / Branding
│
├── Storefront
├── Telegram Commerce
│
├── Commerce Core
│   ├── Products
│   ├── Categories
│   ├── Variants / SKU
│   ├── Cart
│   ├── Checkout
│   ├── Orders
│   └── Customers
│
├── Inventory
│   ├── Digital inventory
│   └── Physical stock ledger
│
├── Fulfillment
│   ├── Digital Auto
│   ├── Digital Manual
│   ├── Service
│   ├── Physical
│   └── Subscription
│
├── Payments
│   ├── Settlement IDSE
│   │   └── Kasera IDSE
│   │
│   └── Gateway Saya Sendiri
│       ├── Kasera
│       ├── Midtrans
│       ├── DOKU
│       ├── GoPay Merchant
│       ├── OttoPay
│       └── Stripe
│
├── Settlement
│   ├── Ledger
│   ├── Pending
│   ├── Clearing
│   ├── Available
│   └── Payout
│
├── Shipping
│   ├── Address
│   ├── Rate
│   ├── Shipment
│   ├── Tracking
│   └── Provider Adapters
│
├── Returns
├── Refunds
│
├── Marketing
├── Analytics
│
└── White Label
```

---

# 51. Implementation Rule

Before Codex starts implementation, create a dedicated implementation plan for each phase.

Do not hand Codex this entire architecture and say:

```text
"build all of this"
```

Instead:

```text
Architecture
→ Phase specification
→ acceptance criteria
→ dependency map
→ implementation
→ tests
→ live dev validation
→ next phase
```

The architecture document is the source of direction.

Each implementation phase must be smaller, testable, reversible, and compatible with the existing SellerBottel V2 multitenant system.

---

# 52. Business Decisions Already Established

The following decisions should be treated as established unless the owner explicitly changes them:

1. SellerBottel must expand beyond digital-only commerce.
2. Physical products such as shoes, clothes, jackets, hats, and similar retail goods are in scope.
3. Tenant identity and branding must be first-class.
4. SellerBottel should act as the infrastructure behind the tenant brand.
5. Payment has two tenant modes:
   - Settlement IDSE
   - Gateway Saya Sendiri
6. Settlement IDSE should use the IDSE-controlled Kasera gateway.
7. IDSE personal GoPay Merchant should remain separated from multitenant settlement use.
8. Tenant own-gateway architecture should support multiple providers through adapters.
9. Planned providers include:
   - Kasera
   - Midtrans
   - DOKU
   - GoPay Merchant
   - OttoPay
   - Stripe
10. Product fulfillment must branch after checkout/payment rather than creating isolated commerce cores.
11. Mixed digital/physical/service orders should be supported by the architecture.
12. Existing SellerBottel V2 digital behavior must remain compatible during migration.
13. White-label capability should be possible as the product matures.

---

# 53. Next Recommended Action

Create the next implementation specification:

```text
PHASE C1 — COMMERCE FOUNDATION
```

That phase should focus only on:

- generalized product/fulfillment type
- order item normalization
- fulfillment records
- fulfillment router
- existing digital migration compatibility
- tests

Do not start payment providers or shipping providers until the commerce foundation is structurally ready.
