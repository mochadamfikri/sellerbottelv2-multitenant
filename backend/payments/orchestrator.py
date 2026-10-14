"""Durable order-payment saga. External actions are never blindly retried."""
import os
from datetime import timedelta
from uuid import uuid4, uuid5, NAMESPACE_URL
from pymongo.errors import DuplicateKeyError
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable, uses_digital_inventory
from .models import now, money, public_payment, ensure_indexes, TRANSITIONS
from .credentials import load
from .providers.registry import provider
from .ledger import Ledger

def tenant_identity(database):
    from bot_tenant_scope import get_current_scope
    scope = get_current_scope()
    if not scope or scope.database_name != database.name:
        raise CommerceError("Registered tenant context required")
    return scope.tenant_id

async def resolve(database, platform, tenant_id):
    config = await database.payment_settings.find_one({"_id": "main"}) or {}
    mode = config.get("payment_mode")
    if mode == "self_gateway":
        adapter = await load(database, tenant_id, config.get("credential_id"))
        caps = config.get("capabilities")
        if not caps or caps["environment"] != adapter.environment or caps["provider"] != adapter.name:
            raise CommerceError("Test Connection required")
        return mode, adapter, config["credential_id"], caps
    if mode == "platform_settlement":
        config = await platform.platform_payment_settings.find_one({"_id": "kasera"}) or {}
        if not config.get("credential_id"):
            raise FulfillmentUnavailable("IDSE settlement gateway is not configured")
        adapter = await load(platform, "platform-idse", config["credential_id"])
        if adapter.name != "kasera":
            raise CommerceError("IDSE gateway must be Kasera")
        caps = config.get("capabilities")
        if not caps:
            raise CommerceError("Platform gateway verification required")
        return mode, adapter, config["credential_id"], caps
    raise CommerceError("Payment mode not configured")

async def payment_adapter(database, platform, payment):
    # Snapshot of credential version/mode, never current tenant configuration.
    if payment["payment_mode"] == "platform_settlement":
        adapter = await load(platform, "platform-idse", payment["credential_id"], historical=True)
    else:
        adapter = await load(database, payment["tenant_id"], payment["credential_id"], historical=True)
    if adapter.name != payment["provider"] or adapter.environment != payment["environment"]:
        raise CommerceError("Payment credential scope mismatch")
    return adapter

async def release_order(database, order):
    from commerce.physical.stock import PhysicalStock
    from inventory import release_items
    from promo_service import release_coupon
    await PhysicalStock(database).release_order(order)
    await release_items("gateway:" + order["_id"])
    for line in order["items"]:
        if line.get("reserved_stock_qty"):
            ref = line["line_id"]
            await database.products.update_one({"_id": line["product_id"], "gateway_stock_refs": ref, "gateway_release_refs": {"$ne": ref}}, {"$inc": {"stock": line["qty"]}, "$addToSet": {"gateway_release_refs": ref}})
    await release_coupon(order["_id"])
    await database.purchases.update_one({"_id": order["_id"]}, {"$set": {"stock_release_pending": False}})

async def checkout(database, platform, customer, body):
    from direct_checkout import quote_items
    from commerce.physical.models import normalize_cart
    from commerce.order_items import normalize_order_items
    from commerce.physical.stock import PhysicalStock
    from inventory import reserve_items
    from promo_service import reserve_coupon
    tenant = tenant_identity(database)
    mode, adapter, credential_id, caps = await resolve(database, platform, tenant)
    method = body.payment_method.removeprefix("gateway:")
    if method not in caps["supported_methods"]:
        raise CommerceError("Payment method unavailable")
    if customer.get("telegram_id"):
        bot_user = await database.bot_users.find_one({"telegram_id": customer["telegram_id"]})
        if bot_user and bot_user.get("frozen"):
            raise CommerceError("Customer wallet/account is frozen")
    await ensure_indexes(database, platform)
    # Stable per-customer checkout ID prevents concurrent stock/payment creation.
    oid = str(uuid5(NAMESPACE_URL, f"gateway-order:{database.name}:{customer['_id']}:{body.idempotency_key}"))
    previous = await database.purchases.find_one({"_id": oid})
    if previous:
        return await checkout_response(database, previous)
    cart = normalize_cart(body.items)
    address = body.shipping_address.model_dump() if body.shipping_address else None
    quote = await quote_items({**customer, "customer_id": customer["_id"], "currency": "IDR"}, cart, body.coupon_code, allow_physical=True, shipping_address=address)
    if quote.get("error"):
        raise CommerceError(quote["error"])
    shipping = {k: quote[k] for k in ("shipping_fee", "requires_shipping", "shipping_address", "shipping_mode") if k in quote}
    if quote["requires_shipping"]:
        from shipping.service import checkout_shipping
        shipping = await checkout_shipping(database, tenant, quote, address, body.shipping_rate_id, customer["_id"])
    subtotal = sum(money(item["base_unit_price"]) * item["qty"] for item in quote["items"])
    discount = sum(money(item["discount_total"]) for item in quote["items"]) + money(quote["coupon_amount"])
    total = subtotal - discount + money(shipping["shipping_fee"])
    money(total, positive=True)
    detail = next((m for m in caps.get("method_details", []) if m.get("code") == method), None)
    if detail and not money(detail.get("min_amount", 0)) <= total <= money(detail.get("max_amount", 10**12)):
        raise CommerceError("Order amount outside payment method limits")
    payment_id = str(uuid4())
    lines = normalize_order_items([{**i.get("physical_snapshot", {}), "product_id": i["product"]["_id"], "name": i["product"]["name"], "qty": i["qty"], **{k: money(i[k]) for k in ("unit_price", "base_unit_price", "discount_total", "subtotal")}, "reserved_stock_qty": i["qty"] if i["product"].get("stock") is not None and not uses_digital_inventory(i["product"]) and not i.get("physical_snapshot") else 0} for i in quote["items"]], order_id=oid, products={i["product"]["_id"]: i["product"] for i in quote["items"]})
    order = {"_id": oid, "tenant_id": tenant, "customer_id": customer["_id"], "user_tid": customer.get("telegram_id"), "invoice_id": "G-" + oid[:12].upper(), "customer_email": customer.get("email"), "purchase_source": "WEB", "payment_scope": "gateway", "payment_method": method, "payment_id": payment_id, "status": "preparing_payment", "items": lines, "currency": "IDR", "total": total, "grand_total": total, "items_subtotal": subtotal, "items_total": subtotal - discount, "discount_total": discount, "tax": 0, "payment_fee": 0, "idempotency_key": body.idempotency_key, "commerce_schema_version": 1, "created_at": now().isoformat(), **shipping}
    try:
        await database.purchases.insert_one(order.copy())
    except DuplicateKeyError:
        return await checkout_response(database, await database.purchases.find_one({"_id": oid}))
    try:
        for index, item in enumerate(quote["items"]):
            line, product = lines[index], item["product"]
            if line["fulfillment_type"] == "physical":
                await PhysicalStock(database).move(line["variant_id"], "RESERVATION", line["qty"], reference_id=line["line_id"])
            elif uses_digital_inventory(product):
                rows = await reserve_items(product["_id"], line["qty"], "gateway:" + oid)
                if len(rows) != line["qty"]:
                    raise CommerceError("Inventory unavailable")
            elif line["reserved_stock_qty"]:
                changed = await database.products.update_one({"_id": product["_id"], "active": True, "stock": {"$gte": line["qty"]}, "gateway_stock_refs": {"$ne": line["line_id"]}}, {"$inc": {"stock": -line["qty"]}, "$addToSet": {"gateway_stock_refs": line["line_id"]}})
                if not changed.modified_count:
                    raise CommerceError("Stock unavailable")
        if quote["coupon"] and not await reserve_coupon(quote["coupon"], {"customer_id": customer["_id"]}, oid, quote["coupon_amount"]):
            raise CommerceError("Coupon unavailable")
        payment = {"_id": payment_id, "tenant_id": tenant, "order_id": oid, "payment_mode": mode, "provider": adapter.name, "environment": adapter.environment, "method": method, "credential_id": credential_id, "capabilities": caps, "amount": total, "currency": "IDR", "status": "created", "provider_reference": str(uuid4()), "provider_payment_id": None, "refunded_amount": 0, "refund_reserved": 0, "refunds": [], "created_at": now(), "updated_at": now(), "expires_at": now() + timedelta(minutes=60), "reconciliation": "create_intent"}
        await database.order_payments.insert_one(payment.copy())
        await platform.payment_routes.insert_one({"_id": payment_id, "provider": adapter.name, "provider_reference": payment["provider_reference"], "tenant_id": tenant, "tenant_database": database.name, "order_id": oid, "payment_mode": mode, "environment": adapter.environment, "created_at": now()})
        claimed = await database.purchases.update_one({"_id": oid, "status": "preparing_payment"}, {"$set": {"status": "pending_payment"}})
        if not claimed.modified_count:
            raise CommerceError("Checkout preparation was cancelled")
    except Exception:
        await database.purchases.update_one({"_id": oid}, {"$set": {"status": "failed", "stock_release_pending": True}})
        await release_order(database, order)
        raise
    # Route and intent already durable before the first external call.
    await database.order_payments.update_one({"_id": payment_id, "status": "created"}, {"$set": {"reconciliation": "create_unknown", "external_started_at": now()}})
    try:
        result = await adapter.create_payment(payment)
        if not isinstance(result, dict) or result.get("status") != "pending" or not isinstance(result.get("provider_payment_id"), str):
            raise CommerceError("Malformed provider response")
        bound = await platform.payment_routes.update_one({"_id": payment_id, "$or": [{"provider_payment_id": {"$exists": False}}, {"provider_payment_id": result["provider_payment_id"]}]}, {"$set": {"provider_payment_id": result["provider_payment_id"], "provider_result": result}})
        if not bound.matched_count:
            raise CommerceError("Provider create/confirmation ID conflict")
        await database.order_payments.update_one({"_id": payment_id, "status": "created"}, {"$set": {**result, "updated_at": now(), "reconciliation": None}})
    except Exception:
        await database.order_payments.update_one({"_id": payment_id, "status": {"$in": ["created", "pending"]}}, {"$set": {"reconciliation": "create_unknown"}})
        # Stock retained. Replaying checkout reads the intent; never recharges.
    return await checkout_response(database, await database.purchases.find_one({"_id": oid}))

async def checkout_response(database, order):
    payment = await database.order_payments.find_one({"order_id": order["_id"]})
    return {**{k: order.get(k) for k in ("_id", "invoice_id", "status", "total", "grand_total", "items", "shipping_fee", "shipping_address", "shipping_mode", "shipping_quote", "requires_shipping", "currency", "payment_method")}, "payment": public_payment(payment) if payment else None}

async def apply_event(database, platform, payment, event):
    if event["status"] not in {"paid", "pending", "expired", "failed", "cancelled"}:
        raise CommerceError("Unsupported payment event")
    order = await database.purchases.find_one({"_id": payment["order_id"], "tenant_id": payment["tenant_id"]})
    if not order:
        raise CommerceError("Payment order binding mismatch")
    status = event["status"]
    current = await database.order_payments.find_one({"_id": payment["_id"], "tenant_id": payment["tenant_id"]})
    if status == "paid" and (current["status"] in {"cancelled", "expired", "failed"} or order["status"] in {"cancelled", "expired", "failed"}):
        await database.order_payments.update_one({"_id": current["_id"]}, {"$set": {"reconciliation": "late_paid_requires_refund_or_stock_review", "external_paid": True}})
        return
    if status != current["status"]:
        if status not in TRANSITIONS.get(current["status"], set()):
            # Older notifications do not regress a paid/refunded payment.
            return
        updates = {"status": status, "provider_event_id": event["event_id"], "updated_at": now(), "reconciliation": "paid_effects_pending" if status == "paid" else "terminal_effects_pending"}
        if status == "paid":
            settings = await database.payment_settings.find_one({"_id": "main"}) or {}
            clearing = now() + timedelta(seconds=max(0, int(settings.get("clearing_delay_seconds", 0))))
            updates.update({"paid_at": now(), "clearing_at": clearing, "available_at": clearing + timedelta(seconds=max(0, int(settings.get("available_delay_seconds", 0)))), "platform_fee": money(settings.get("platform_fee", 0))})
        await database.order_payments.update_one({"_id": current["_id"], "status": current["status"]}, {"$set": updates})
    current = await database.order_payments.find_one({"_id": payment["_id"]})
    if current["status"] == "paid":
        await repair_paid(database, platform, current)
    elif current["status"] in {"expired", "cancelled", "failed"}:
        await database.purchases.update_one({"_id": order["_id"], "status": "pending_payment"}, {"$set": {"status": current["status"], "stock_release_pending": True}})
        await release_order(database, order)
        await database.order_payments.update_one({"_id": current["_id"]}, {"$set": {"reconciliation": None}})

async def repair_paid(database, platform, payment):
    from commerce.physical.stock import PhysicalStock
    from inventory import commit_items
    from commerce.fulfillment.adapters import fulfill_web_order
    order = await database.purchases.find_one({"_id": payment["order_id"], "tenant_id": payment["tenant_id"]})
    if order["status"] in {"cancelled", "expired", "failed"}:
        raise CommerceError("Late payment requires operator review")
    await database.purchases.update_one({"_id": order["_id"], "status": "pending_payment"}, {"$set": {"status": "paid", "paid_at": now().isoformat()}})
    order = await database.purchases.find_one({"_id": order["_id"]})
    # Credit and stock operations have durable operation identities. Replays
    # do not replay a failed/running C1 delivery claim.
    if payment["payment_mode"] == "platform_settlement" and "gateway_fee" not in payment:
        adapter = await payment_adapter(database, platform, payment)
        result = await adapter.get_payment(payment)
        if "gateway_fee" not in result:
            raise FulfillmentUnavailable("Verified gateway fee required before settlement credit")
        payment["gateway_fee"] = money(result["gateway_fee"])
        await database.order_payments.update_one({"_id": payment["_id"]}, {"$set": {"gateway_fee": payment["gateway_fee"]}})
    await Ledger(database, payment["tenant_id"]).credit(payment)
    await PhysicalStock(database).consume_order(order)
    await commit_items("gateway:" + order["_id"], order["_id"], order.get("user_tid"), customer_id=order["customer_id"])
    states = await fulfill_web_order(order)
    if any(s not in {"delivered", "completed", "pending", "queued", "packing", "ready_to_ship", "shipped"} for s in states):
        raise FulfillmentUnavailable("Fulfillment claim needs operator reconciliation")
    state = "service_waiting" if "queued" in states else "physical_pending" if any(i["fulfillment_type"] == "physical" for i in order["items"]) else "delivered"
    await database.purchases.update_one({"_id": order["_id"], "status": "paid"}, {"$set": {"status": state}})
    await database.order_payments.update_one({"_id": payment["_id"]}, {"$set": {"reconciliation": None}})
