"""QRIS orders for the main bot. Payments go directly to an order, not a deposit."""
import asyncio
import base64
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from checkout import next_invoice_id, stock_for, _cart_after_purchase
from db import db, get_settings, _resolve_db
from gopay_provider import _run_node, qris_expiry_minutes
from inventory import commit_items, decrypt_items, release_items, reserve_items
from pricing import price_for_product
from promo_service import coupon_discount, release_coupon, reserve_coupon, validate_coupon
from services import notify_transaction_admin, notify_transaction_channel, now_iso
from commerce.fulfillment_types import CommerceError, require_operational, uses_digital_inventory, FulfillmentType, resolve_fulfillment_type
from commerce.order_items import normalize_order_items, product_for_line
from commerce.fulfillment.router import ensure_order_fulfillments, route_item

logger = logging.getLogger(__name__)
PAYMENT_SCOPE = "bot1"


async def qris_ready():
    settings = await get_settings()
    return bool(settings.get("qris_enabled")) and os.environ.get("GOPAY_ENABLED", "").lower() in {"1", "true", "yes"}


async def store_qris_ready():
    """Keep storefront gateway configuration separate from Telegram bot payment settings."""
    settings = await get_settings()
    return bool(settings.get("store_qris_enabled")) and os.environ.get("GOPAY_ENABLED", "").lower() in {"1", "true", "yes"}


async def quote_items(user, cart_items, coupon_code=None, *, allow_physical=False, shipping_address=None, require_address=True):
    items = []
    for raw in cart_items:
        product = await db.products.find_one({"_id": raw.get("pid"), "active": True})
        if not product:
            return {"error": "Produk sudah tidak tersedia."}
        try:
            require_operational(product, allow_physical=allow_physical)
        except CommerceError:
            return {"error": "Fulfillment unavailable"}
        qty = max(1, int(raw.get("qty") or 1))
        minimum_qty = max(1, int(product.get("minimum_purchase_qty") or 1))
        if qty < minimum_qty:
            return {"error": f"Minimum pembelian {minimum_qty} pcs untuk {product['name']}."}
        stock = await stock_for(product)
        if stock is not None and stock < qty:
            return {"error": f"Stok {product['name']} berubah. Tersedia {stock}."}
        physical_snapshot = {}
        if resolve_fulfillment_type(product) == FulfillmentType.PHYSICAL:
            from commerce.physical.models import checkout_variant, line_snapshot
            variant = await checkout_variant(_resolve_db(), product, raw.get("variant_id"))
            if variant["on_hand"] - variant["reserved"] < qty:
                return {"error": "Insufficient physical stock"}
            physical_snapshot = line_snapshot(variant)
            if variant.get("price_override") is not None:
                product = {**product, "price_idr": variant["price_override"]}
        pricing = await price_for_product(product, "IDR", qty)
        items.append({"product": product, "physical_snapshot": physical_snapshot, "qty": qty, **pricing,
                      "subtotal": pricing["unit_price"] * qty})
    if not items:
        return {"error": "Keranjang kosong."}
    total = sum(item["subtotal"] for item in items)
    coupon = None
    coupon_amount = 0
    if coupon_code:
        base = sum(float(item["base_unit_price"]) * item["qty"] for item in items)
        coupon_buyer = {"customer_id": user["customer_id"]} if user.get("customer_id") else user["telegram_id"]
        coupon, error = await validate_coupon(
            coupon_code, coupon_buyer, "IDR", base,
            [item["product"]["_id"] for item in items],
        )
        if error:
            return {"error": error}
        eligible_ids = set(coupon.get("product_ids") or [])
        eligible = [item for item in items if not eligible_ids or item["product"]["_id"] in eligible_ids]
        eligible_base = sum(float(item["base_unit_price"]) * item["qty"] for item in eligible)
        if eligible_base < float(coupon.get("min_purchase") or 0):
            return {"error": "Total produk yang memenuhi syarat belum mencapai minimum kupon."}
        product_discount = sum(float(item["discount_total"]) for item in eligible)
        if coupon_discount(coupon, eligible_base) > product_discount:
            coupon_amount = round(coupon_discount(coupon, eligible_base) - product_discount, 2)
            total = round(total - coupon_amount, 2)
        else:
            coupon = None
    from commerce.physical.models import shipping_quote
    shipping = await shipping_quote(_resolve_db(), [item["product"] for item in items], shipping_address, require_address=require_address)
    items_total = total
    total = int(round(total + shipping["shipping_fee"]))
    if total < 1:
        return {"error": "Total QRIS harus minimal Rp1."}
    return {"items": items, "items_total": items_total, **shipping, "total": total, "coupon": coupon,
            "coupon_amount": coupon_amount}


async def _release_order_stock(order):
    from commerce.physical.stock import PhysicalStock
    await PhysicalStock(_resolve_db()).release_order(order)
    await release_items(f"qris:{order['_id']}")
    for index, item in enumerate(order.get("items", [])):
        if item.get("reserved_stock_qty"):
            reference = f"{order['_id']}:{item.get('line_id') or index}"
            await db.products.update_one({"_id": item["product_id"], "stock_release_refs": {"$ne": reference}},
                {"$inc": {"stock": int(item["reserved_stock_qty"])}, "$addToSet": {"stock_release_refs": reference}})
    await release_coupon(order["_id"])
    await db.purchases.update_one({"_id": order["_id"]}, {"$set": {"stock_release_pending": False}})


async def create_qris_order(user, cart_items, coupon_code=None, preserve_cart=False):
    if not await qris_ready():
        return {"error": "Pembayaran QRIS sedang tidak tersedia."}
    existing = await db.purchases.find_one({"user_tid": user["telegram_id"],
        "payment_scope": PAYMENT_SCOPE, "payment_method": "qris",
        "status": "pending_payment"})
    if existing:
        if existing.get("expires_at", "") <= now_iso():
            return {"error": "QRIS sebelumnya sedang diverifikasi. Coba lagi sebentar."}
        payment = await db.gopay_payments.find_one({"_id": existing.get("payment_id"), "status": "pending"})
        if payment:
            data = await asyncio.to_thread(_run_node, "create_qris.mjs", [str(payment["payment_amount"])])
            return {"order": existing, "payment": payment,
                    "image": base64.b64decode(data["image_base64"], validate=True)}
        return {"error": "Pembayaran QRIS sebelumnya sedang diproses. Coba lagi sebentar."}
    quote = await quote_items(user, cart_items, coupon_code)
    if quote.get("error"):
        return quote

    order_id = str(uuid.uuid4())
    reservation_id = f"qris:{order_id}"
    expires_in_minutes = await qris_expiry_minutes()
    expires = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
    order_items = []
    order = {"_id": order_id, "items": order_items}
    payment_id = str(uuid.uuid4())
    try:
        for item in quote["items"]:
            product = item["product"]
            qty = item["qty"]
            stock_qty = 0
            if uses_digital_inventory(product):
                reserved = await reserve_items(product["_id"], qty, reservation_id)
                if len(reserved) != qty:
                    raise ValueError(f"Stok {product['name']} baru saja habis.")
            elif product.get("stock") is not None:
                changed = await db.products.update_one(
                    {"_id": product["_id"], "active": True, "stock": {"$gte": qty}},
                    {"$inc": {"stock": -qty}},
                )
                if changed.modified_count != 1:
                    raise ValueError(f"Stok {product['name']} baru saja habis.")
                stock_qty = qty
            order_items.append({
                "product_id": product["_id"], "name": product["name"], "qty": qty,
                "unit_price": item["unit_price"], "base_unit_price": item["base_unit_price"],
                "discount_per_unit": item["discount_per_unit"], "discount_total": item["discount_total"],
                "discount_id": item["discount_id"], "discount_name": item["discount_name"],
                "subtotal": item["subtotal"], "delivery_type": product.get("delivery_type"),
                "reserved_stock_qty": stock_qty,
            })

        if quote["coupon"] and not await reserve_coupon(
            quote["coupon"], {"customer_id": user["customer_id"]} if user.get("customer_id") else user["telegram_id"],
            order_id, quote["coupon_amount"]
        ):
            raise ValueError("Kupon baru saja mencapai batas penggunaan.")

        admin_fee = max(1, int(round(quote["total"] * 0.007)))
        invoice_id = await next_invoice_id()
        linked_customer = await db.store_customers.find_one({"telegram_id": user["telegram_id"]}, {"_id": 1, "email": 1})
        order.update({
            "invoice_id": invoice_id, "user_tid": user["telegram_id"], "purchase_source": "BOT",
            "customer_id": linked_customer.get("_id") if linked_customer else None,
            "customer_email": linked_customer.get("email") if linked_customer else None,
            "username": user.get("username", ""), "total": quote["total"],
            "currency": "IDR", "payment_method": "qris", "payment_id": payment_id,
            "payment_scope": PAYMENT_SCOPE, "status": "pending_payment",
            "created_at": now_iso(), "expires_at": expires.isoformat(),
            "expires_in_minutes": expires_in_minutes,
            "paid_at": None, "delivered_at": None, "delivery_error": None,
            "discount_total": sum(item["discount_total"] for item in quote["items"]) + quote["coupon_amount"],
            "coupon_code": quote["coupon"]["code"] if quote["coupon"] else None,
            "coupon_discount": quote["coupon_amount"], "preserve_cart": bool(preserve_cart),
            "source_code": user.get("traffic_source_code"),
            "source_kind": user.get("traffic_source_kind"),
        })
        order["items"] = normalize_order_items(order["items"], order_id=order_id,
            products={str(item["product"]["_id"]): item["product"] for item in quote["items"]})
        order["commerce_schema_version"] = 1
        await db.purchases.insert_one(order)
        payment = None
        for _ in range(200):
            code = secrets.randbelow(900) + 100
            amount = quote["total"] + admin_fee + code
            try:
                payment = {"_id": payment_id, "payment_scope": PAYMENT_SCOPE,
                           "payment_type": "checkout", "order_id": order_id,
                           "user_tid": user["telegram_id"], "base_amount": quote["total"],
                           "admin_fee": admin_fee, "platform_code": code,
                           "payment_amount": amount, "active_payment_amount": amount,
                           "status": "pending", "tx_id": None,
                           "created_at": order["created_at"], "expires_at": expires.isoformat(),
                           "confirmed_at": None}
                await db.gopay_payments.insert_one(payment)
                break
            except DuplicateKeyError:
                payment = None
        if payment is None:
            raise RuntimeError("Nominal QRIS unik tidak tersedia.")
        data = await asyncio.to_thread(_run_node, "create_qris.mjs", [str(payment["payment_amount"])])
        image = base64.b64decode(data["image_base64"], validate=True)
        from stock_monitor import schedule_stock_scan
        for item in order_items:
            schedule_stock_scan(item["product_id"])
        return {"order": order, "payment": payment, "image": image}
    except Exception:
        await _release_order_stock(order)
        await db.gopay_payments.delete_one({"_id": payment_id})
        await db.purchases.update_one({"_id": order_id}, {"$set": {"status": "failed"}})
        raise


async def create_store_qris_order(customer, cart_items, coupon_code=None, idempotency_key=None, shipping_address=None, shipping_rate_id=None):
    """Create a QRIS order for an authenticated web customer without charging a wallet."""
    if not await store_qris_ready():
        return {"error": "Pembayaran QRIS sedang tidak tersedia."}
    customer_id = str(customer["_id"])
    if idempotency_key:
        existing = await db.purchases.find_one({"customer_id": customer_id, "idempotency_key": idempotency_key})
        if existing:
            payment = await db.gopay_payments.find_one({"_id": existing.get("payment_id"), "status": "pending"})
            if existing.get("status") == "pending_payment" and payment:
                data = await asyncio.to_thread(_run_node, "create_qris.mjs", [str(payment["payment_amount"])])
                return {"order": existing, "payment": payment,
                        "image": base64.b64decode(data["image_base64"], validate=True)}
            return {"order": existing, "payment": None, "image": None}

    quote = await quote_items({**customer, "customer_id": customer_id, "currency": "IDR"}, cart_items, coupon_code, allow_physical=True, shipping_address=shipping_address)
    if quote.get("error"):
        return quote
    from bot_tenant_scope import get_current_scope
    scope = get_current_scope()
    if scope and quote["requires_shipping"]:
        from shipping.service import checkout_shipping
        selection = await checkout_shipping(_resolve_db(), scope.tenant_id, quote, shipping_address, shipping_rate_id, customer_id)
        quote.update(selection)
        quote["total"] = int(round(quote["items_total"] + selection["shipping_fee"]))

    order_id = str(uuid.uuid4())
    reservation_id = f"qris:{order_id}"
    expires_in_minutes = await qris_expiry_minutes()
    expires = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
    payment_id = str(uuid.uuid4())
    order = {"_id": order_id, "items": []}
    try:
        order["items"] = normalize_order_items([{
            **item.get("physical_snapshot", {}), "product_id": item["product"]["_id"], "name": item["product"]["name"],
            "qty": item["qty"], **{key: item[key] for key in ("unit_price", "base_unit_price", "discount_per_unit", "discount_total", "discount_id", "discount_name", "subtotal")},
            "delivery_type": item["product"].get("delivery_type"), "reserved_stock_qty": 0,
        } for item in quote["items"]], order_id=order_id, products={str(item["product"]["_id"]): item["product"] for item in quote["items"]})
        for index, item in enumerate(quote["items"]):
            product, qty = item["product"], item["qty"]
            line = order["items"][index]
            if resolve_fulfillment_type(product) == FulfillmentType.PHYSICAL:
                from commerce.physical.stock import PhysicalStock
                await PhysicalStock(_resolve_db()).move(line["variant_id"], "RESERVATION", qty, reference_id=line["line_id"])
            elif uses_digital_inventory(product):
                reserved = await reserve_items(product["_id"], qty, reservation_id)
                if len(reserved) != qty:
                    raise CommerceError("Inventory unavailable")
            elif product.get("stock") is not None:
                changed = await db.products.update_one({"_id": product["_id"], "active": True, "stock": {"$gte": qty}}, {"$inc": {"stock": -qty}})
                if changed.modified_count != 1:
                    raise CommerceError("Stock unavailable")
                line["reserved_stock_qty"] = qty

        buyer = {"customer_id": customer_id}
        if quote["coupon"] and not await reserve_coupon(quote["coupon"], buyer, order_id, quote["coupon_amount"]):
            raise ValueError("Kupon baru saja mencapai batas penggunaan. Silakan coba lagi.")
        total = int(round(quote["total"]))
        admin_fee = max(1, int(round(total * 0.007)))
        invoice_id = await next_invoice_id()
        created_at = now_iso()
        order.update({
            **{key: quote[key] for key in ("shipping_fee", "requires_shipping", "shipping_mode", "shipping_address", "shipping_quote") if key in quote},
            "items_subtotal": sum(item["base_unit_price"] * item["qty"] for item in quote["items"]), "items_total": quote["items_total"], "grand_total": total + admin_fee,
            "tax": 0, "payment_fee": admin_fee,
            "invoice_id": invoice_id, "user_tid": customer.get("telegram_id"), "customer_id": customer_id, "purchase_source": "WEB",
            "customer_email": customer.get("email"), "username": customer.get("username", ""),
            "total": total, "currency": "IDR", "payment_method": "qris", "payment_id": payment_id,
            "payment_scope": "store", "status": "pending_payment", "created_at": created_at,
            "expires_at": expires.isoformat(), "expires_in_minutes": expires_in_minutes,
            "paid_at": None, "delivered_at": None,
            "delivery_error": None,
            "discount_total": sum(item["discount_total"] for item in quote["items"]) + quote["coupon_amount"],
            "coupon_code": quote["coupon"]["code"] if quote["coupon"] else None,
            "coupon_discount": quote["coupon_amount"], "source_code": customer.get("traffic_source_code"),
            "source_kind": customer.get("traffic_source_kind"), "idempotency_key": idempotency_key,
        })
        order["items"] = normalize_order_items(order["items"], order_id=order_id,
            products={str(item["product"]["_id"]): item["product"] for item in quote["items"]})
        order["commerce_schema_version"] = 1
        await db.purchases.insert_one(order)

        payment = None
        for _ in range(200):
            code = secrets.randbelow(900) + 100
            amount = total + admin_fee + code
            try:
                payment = {
                    "_id": payment_id, "payment_scope": "store", "payment_type": "checkout",
                    "order_id": order_id, "user_tid": customer.get("telegram_id"),
                    "customer_id": customer_id, "base_amount": total, "admin_fee": admin_fee,
                    "platform_code": code, "payment_amount": amount,
                    "active_payment_amount": amount, "status": "pending", "tx_id": None,
                    "created_at": created_at, "expires_at": expires.isoformat(), "confirmed_at": None,
                }
                await db.gopay_payments.insert_one(payment)
                break
            except DuplicateKeyError:
                payment = None
        if payment is None:
            raise RuntimeError("Nominal QRIS unik tidak tersedia.")
        data = await asyncio.to_thread(_run_node, "create_qris.mjs", [str(payment["payment_amount"])])
        image = base64.b64decode(data["image_base64"], validate=True)
        from stock_monitor import schedule_stock_scan
        for item in order["items"]:
            schedule_stock_scan(item["product_id"])
        return {"order": order, "payment": payment, "image": image}
    except DuplicateKeyError:
        await _release_order_stock(order)
        await db.gopay_payments.delete_one({"_id": payment_id})
        existing = await db.purchases.find_one({"customer_id": customer_id, "idempotency_key": idempotency_key})
        if existing and existing.get("status") == "pending_payment":
            existing_payment = await db.gopay_payments.find_one({"_id": existing.get("payment_id"), "status": "pending"})
            if existing_payment:
                data = await asyncio.to_thread(_run_node, "create_qris.mjs", [str(existing_payment["payment_amount"])])
                return {"order": existing, "payment": existing_payment,
                        "image": base64.b64decode(data["image_base64"], validate=True)}
        if existing:
            return {"order": existing, "payment": None, "image": None}
        await db.purchases.update_one({"_id": order_id}, {"$set": {"status": "failed"}})
        raise
    except Exception:
        await _release_order_stock(order)
        await db.gopay_payments.delete_one({"_id": payment_id})
        await db.purchases.update_one({"_id": order_id}, {"$set": {"status": "failed"}})
        raise


async def expire_qris_orders(*, physical_only=False):
    now = now_iso()
    async for order in db.purchases.find({"payment_scope": "store" if physical_only else {"$in": [PAYMENT_SCOPE, "store"]},
                                           **({"requires_shipping": True} if physical_only else {}),
                                           "payment_method": "qris",
                                           "$or": [{"status": "pending_payment", "expires_at": {"$lte": now}}, {"status": "expired", "stock_release_pending": True}] }):
        changed = await db.purchases.update_one(
            {"_id": order["_id"], "status": "pending_payment"},
            {"$set": {"status": "expired", "stock_release_pending": True}},
        )
        if changed.modified_count or (order.get("status") == "expired" and order.get("stock_release_pending")):
            await _release_order_stock(order)
            await db.gopay_payments.update_one({"_id": order["payment_id"], "status": "pending"},
                {"$set": {"status": "expired", "expired_at": now}, "$unset": {"active_payment_amount": ""}})
            try:
                if order.get("payment_scope") == PAYMENT_SCOPE and order.get("user_tid"):
                    from tgapi import delete_message, send_message
                    if order.get("qr_message_id"):
                        try:
                            await delete_message(order["user_tid"], order["qr_message_id"])
                        except Exception:
                            logger.exception("Could not delete expired checkout QR message")
                    await send_message(order["user_tid"],
                        f"⌛ <b>Pembayaran kedaluwarsa</b>\nInvoice <code>{order['invoice_id']}</code> sudah expired.\n"
                        "Kode QR tidak berlaku. Silakan request QR baru untuk melanjutkan.")
            except Exception:
                logger.exception("Failed to notify expired QRIS order")


async def finalize_qris_order(order_id, tx_id):
    order = await db.purchases.find_one({"_id": order_id, "payment_scope": {"$in": [PAYMENT_SCOPE, "store"]}})
    if not order:
        return False
    claimed = await db.purchases.update_one(
        {"_id": order_id, "status": "pending_payment"},
        {"$set": {"status": "paid", "paid_at": now_iso(), "payment_tx_id": tx_id}},
    )
    if claimed.modified_count != 1:
        return False
    order["status"] = "paid"

    if order.get("payment_scope") == "store":
        return await _finalize_store_qris_order(order)

    from bot import (deliver_inventory, deliver_product, queue_service_delivery,
                     send_message, user_label, build_invoice_text)
    from services import user_lang
    user = await db.bot_users.find_one({"telegram_id": order["user_tid"]}) or {"telegram_id": order["user_tid"]}
    lang = await user_lang(order["user_tid"])
    all_ok = True
    service_count = 0
    try:
        await ensure_order_fulfillments(order)
        await commit_items(f"qris:{order_id}", order_id, order["user_tid"])
        if order.get("source_code"):
            await db.prospects.update_many({"tg_user_id": order["user_tid"]},
                {"$set": {"status": "customer", "customer_order_id": order_id, "converted_at": now_iso()}})
        if order.get("preserve_cart"):
            fresh = await db.bot_users.find_one({"telegram_id": order["user_tid"]}, {"cart": 1})
            new_cart = _cart_after_purchase((fresh or {}).get("cart", []),
                [{"pid": item["product_id"], "qty": item["qty"]} for item in order["items"]])
        else:
            new_cart = []
        user_update = {"$set": {"cart": new_cart}}
        if order.get("coupon_code"):
            user_update["$unset"] = {"pending_coupon": ""}
        await db.bot_users.update_one({"telegram_id": order["user_tid"]}, user_update)
        await send_message(order["user_tid"], build_invoice_text(order))
        for item in order["items"]:
            product = await db.products.find_one({"_id": item["product_id"]})
            from commerce.fulfillment.adapters import fulfill_bot_line
            state = await fulfill_bot_line(order, item, product, chat_id=order["user_tid"], user=user, lang=lang,
                queue_service_fn=queue_service_delivery)
            if item["fulfillment_type"] == FulfillmentType.SERVICE:
                service_count += 1
            all_ok = all_ok and state in {"delivered", "queued", "completed"}
        final_status = "delivery_failed" if not all_ok else ("service_waiting" if service_count else "delivered")
        await db.purchases.update_one({"_id": order_id}, {"$set": {
            "status": final_status, "delivered_at": now_iso() if all_ok and not service_count else None,
            "delivery_error": None if all_ok else "Satu atau lebih produk gagal dikirim.",
        }})
        if all_ok and not service_count and (order.get("customer_email") or order.get("customer_id")):
            try:
                from storefront_routes import send_order_completion_email
                await send_order_completion_email(order_id)
            except Exception:
                logger.exception("Order completion email failed for QRIS order %s", order_id)
        await send_message(order["user_tid"],
            f"✅ Pembayaran QRIS terverifikasi. Invoice <code>{order['invoice_id']}</code>. "
            + ("Produk sedang dikirim." if all_ok else "Pengiriman membutuhkan bantuan admin."))
        sale = {**order, "status": final_status}
        for notify, args in ((notify_transaction_admin, (sale, user_label(user))),
                             (notify_transaction_channel, (sale,))):
            try:
                await notify(*args)
            except Exception:
                logger.exception("QRIS sale notification failed")
        return all_ok
    except Exception as exc:
        logger.exception("QRIS order delivery failed: %s", order_id)
        await db.purchases.update_one({"_id": order_id},
            {"$set": {"status": "delivery_failed", "delivery_error": str(exc)}})
        try:
            await send_message(order["user_tid"],
                f"⚠️ Pembayaran invoice <code>{order['invoice_id']}</code> berhasil, tetapi pengiriman membutuhkan bantuan admin.")
        except Exception:
            pass
        return False


async def _finalize_store_qris_order(order):
    order_id = order["_id"]
    try:
        await ensure_order_fulfillments(order)
        from commerce.physical.stock import PhysicalStock
        await PhysicalStock(_resolve_db()).consume_order(order)
        await commit_items(f"qris:{order_id}", order_id, order.get("user_tid"), customer_id=order.get("customer_id"))
        from commerce.fulfillment.adapters import fulfill_web_order
        states = await fulfill_web_order(order)
        if any(state not in {"delivered", "queued", "completed", "pending"} for state in states):
            raise CommerceError("Fulfillment delivery incomplete")
        products = []
        for item in order.get("items") or []:
            product = await db.products.find_one({"_id": item.get("product_id")})
            product = product_for_line(item, product)
            products.append((item, product))
        has_service = any(
            item["fulfillment_type"] == FulfillmentType.SERVICE
            for item, product in products
        )
        has_physical = any(item["fulfillment_type"] == FulfillmentType.PHYSICAL for item, _ in products)
        status = "service_waiting" if has_service else "physical_pending" if has_physical else "delivered"
        changed = await db.purchases.update_one({"_id": order_id, "status": "paid"}, {"$set": {
            "status": status, "delivered_at": None if has_service or has_physical else now_iso(), "delivery_error": None,
        }})
        if not changed.modified_count:
            return True
        order["status"] = status
        from services import notify_transaction_channel_safely
        await notify_transaction_channel_safely(order)
        if has_service:
            from services import notify_admin
            names = ", ".join(f"{item.get('name') or 'Produk'} ×{item.get('qty') or 1}"
                               for item, product in products
                               if item["fulfillment_type"] == FulfillmentType.SERVICE)
            await notify_admin(
                "🛎️ <b>Pesanan jasa dari web menunggu tindak lanjut</b>\n"
                f"Invoice: <code>{escape(str(order.get('invoice_id') or ''))}</code>\n"
                f"Pelanggan: {escape(str(order.get('customer_email') or '-'))}\nProduk jasa: {escape(names)}\n"
                "Selesaikan pesanan dari menu Orders setelah pekerjaan selesai."
            )
        elif not has_physical:
            from storefront_routes import send_order_completion_email
            await send_order_completion_email(order_id)
        return True
    except Exception as exc:
        logger.exception("Web QRIS order delivery failed: %s", order_id)
        await db.purchases.update_one({"_id": order_id, "status": "paid"}, {"$set": {
            "status": "delivery_failed", "delivery_error": str(exc)[:500],
        }})
        try:
            from services import notify_admin
            await notify_admin(
                "⚠️ <b>Pesanan web QRIS perlu diperiksa</b>\n"
                f"Invoice: <code>{escape(str(order.get('invoice_id') or order_id))}</code>\n"
                f"Error: {escape(str(exc)[:300])}"
            )
        except Exception:
            pass
        return False
