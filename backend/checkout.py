import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from db import db
from inventory import commit_items, release_items, reserve_items
from rates import get_rate
from pricing import price_for_product
from promo_service import validate_coupon, coupon_discount, reserve_coupon, release_coupon


CUR_FIELD = {"USD": "balance_usd", "IDR": "balance_idr"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def jakarta_date():
    return datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y%m%d")


async def next_invoice_id():
    counter = await db.counters.find_one_and_update(
        {"_id": f"invoice:{jakarta_date()}"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=__import__("pymongo").ReturnDocument.AFTER,
    )
    return f"INV-{jakarta_date()}-{counter['seq']:04d}"


async def product_price(product, currency):
    if currency == "USD":
        return round(float(product.get("price_usd") or 0), 2)
    if product.get("price_idr") is not None:
        return round(float(product["price_idr"]))
    rate = await get_rate()
    return round(float(product.get("price_usd") or 0) * rate / 100) * 100


async def stock_for(product):
    is_inventory = (
        product.get("product_kind") == "digital"
        or product.get("delivery_type") == "inventory"
        or product.get("inventory_enabled")
    )
    if is_inventory:
        available = await db.inventory_items.count_documents({
            "product_id": product["_id"],
            "status": "available",
        })
        if product.get("stock_mode") == "manual" and product.get("manual_stock") is not None:
            marketing = await db.inventory_items.count_documents({"product_id": product["_id"], "status": "marketing_allocated"})
            return min(available, max(0, int(product.get("manual_stock") or 0) - marketing))
        return available

    stock = product.get("stock")
    return None if stock is None else int(stock)




async def _fail_checkout(order_id, allocations, reservation_id, error, message, user=None, field=None, total=0.0,
                        wallet_collection=None, wallet_query=None):
    for allocation in allocations:
        if allocation["kind"] == "stock":
            await db.products.update_one(
                {"_id": allocation["product_id"]},
                {"$inc": {"stock": allocation["qty"]}},
            )
    await release_items(reservation_id)
    await release_coupon(order_id)

    if user is not None and field and total > 0:
        wallet_collection = wallet_collection or db.bot_users
        wallet_query = wallet_query or {"telegram_id": user["telegram_id"]}
        await wallet_collection.update_one(
            {**wallet_query, "checkout_refund_ids": {"$ne": order_id}},
            {
                "$inc": {field: total},
                "$addToSet": {"checkout_refund_ids": order_id},
            },
        )

    await db.purchases.update_one(
        {"_id": order_id},
        {"$set": {"status": "failed", "delivery_error": message}},
    )
    return {"ok": False, "error": error, "message": message}

def _cart_after_purchase(cart, purchased_items):
    remaining = []
    purchase_map = {}
    for item in purchased_items or []:
        pid = str(item.get("pid") or "")
        if pid:
            purchase_map[pid] = purchase_map.get(pid, 0) + max(1, int(item.get("qty", 1)))

    for raw in cart or []:
        if isinstance(raw, str):
            item = {"pid": raw, "qty": 1}
        elif isinstance(raw, dict) and raw.get("pid"):
            item = {"pid": raw["pid"], "qty": max(1, int(raw.get("qty", 1)))}
        else:
            continue

        pid = item["pid"]
        deduct = purchase_map.get(pid, 0)
        if deduct:
            left = item["qty"] - deduct
            purchase_map[pid] = max(0, deduct - item["qty"])
            if left > 0:
                remaining.append({"pid": pid, "qty": left})
        else:
            remaining.append(item)

    return remaining


async def execute_checkout(user, cart_items, preserve_cart=False, coupon_code=None,
                           unit_price_overrides=None, order_metadata=None, purchase_source="BOT"):
    if purchase_source not in {"WEB", "BOT"}:
        raise ValueError("Invalid checkout channel")
    currency = user["currency"]
    field = CUR_FIELD[currency]
    telegram_id = user.get("telegram_id")
    customer_id = user.get("customer_id")
    wallet_collection = db.store_customers if customer_id and not telegram_id else db.bot_users
    wallet_is_bot = wallet_collection.name == "bot_users"
    wallet_query = {"telegram_id": telegram_id} if wallet_is_bot else {"_id": customer_id}
    coupon_buyer = {"customer_id": customer_id} if customer_id else {"user_tid": telegram_id}
    order_id = str(uuid.uuid4())
    reservation_id = f"order:{order_id}"

    items = []
    total = 0.0

    for raw in cart_items:
        product = await db.products.find_one({
            "_id": raw["pid"],
            "active": True,
        })
        if not product:
            continue

        qty = max(1, int(raw.get("qty", 1)))
        minimum_qty = max(1, int(product.get("minimum_purchase_qty") or 1))
        if qty < minimum_qty:
            return {
                "ok": False,
                "error": "minimum_qty",
                "product": product,
                "minimum_qty": minimum_qty,
            }
        stock = await stock_for(product)
        if stock is not None and stock < qty:
            return {
                "ok": False,
                "error": "stock",
                "product": product,
                "stock": stock,
            }

        pricing = await price_for_product(product, currency, qty)
        if unit_price_overrides and product["_id"] in unit_price_overrides:
            override = float(unit_price_overrides[product["_id"]])
            if override <= 0:
                return {"ok": False, "error": "price", "message": "Harga jual tidak valid."}
            pricing = {"unit_price": override, "base_unit_price": override,
                       "discount_per_unit": 0, "discount_total": 0,
                       "discount_id": None, "discount_name": None}
        price = pricing["unit_price"]
        items.append({
            "product": product,
            "qty": qty,
            "unit_price": price,
            "base_unit_price": pricing["base_unit_price"],
            "discount_per_unit": pricing["discount_per_unit"],
            "discount_total": pricing["discount_total"],
            "discount_id": pricing["discount_id"],
            "discount_name": pricing["discount_name"],
            "subtotal": price * qty,
        })
        total += price * qty

    if not items:
        return {"ok": False, "error": "empty"}

    # Kupon tidak ditumpuk dengan discount produk.
    coupon = None
    coupon_discount_amount = 0.0
    if coupon_code:
        base_subtotal = sum(float(item["base_unit_price"]) * item["qty"] for item in items)
        current_subtotal = sum(float(item["subtotal"]) for item in items)
        product_ids = [item["product"]["_id"] for item in items]
        coupon, coupon_error = await validate_coupon(
            coupon_code, coupon_buyer, currency, base_subtotal, product_ids
        )
        if coupon_error:
            return {"ok": False, "error": "coupon", "message": coupon_error}

        eligible_ids = set(coupon.get("product_ids") or [])
        eligible = [
            item for item in items
            if not eligible_ids or item["product"]["_id"] in eligible_ids
        ]
        eligible_base = sum(float(item["base_unit_price"]) * item["qty"] for item in eligible)
        if eligible_base < float(coupon.get("min_purchase") or 0):
            return {"ok": False, "error": "coupon", "message": "Total produk yang memenuhi syarat belum mencapai minimum kupon."}
        eligible_product_discount = sum(float(item["discount_total"]) for item in eligible)
        candidate_coupon_discount = min(coupon_discount(coupon, eligible_base), eligible_base)

        if candidate_coupon_discount > eligible_product_discount:
            coupon_discount_amount = round(candidate_coupon_discount - eligible_product_discount, 2)
            total = round(current_subtotal - coupon_discount_amount, 2)
        else:
            coupon = None

    invoice_id = await next_invoice_id()
    order = {
        "_id": order_id,
        "invoice_id": invoice_id,
        "purchase_source": purchase_source,
        "user_tid": telegram_id,
        "customer_id": customer_id,
        "customer_email": user.get("email"),
        "username": user.get("username", ""),
        "items": [
            {
                "product_id": item["product"]["_id"],
                "name": item["product"]["name"],
                "qty": item["qty"],
                "unit_price": item["unit_price"],
                "base_unit_price": item["base_unit_price"],
                "discount_per_unit": item["discount_per_unit"],
                "discount_total": item["discount_total"],
                "discount_id": item["discount_id"],
                "discount_name": item["discount_name"],
                "subtotal": item["subtotal"],
                "delivery_type": item["product"].get("delivery_type"),
            }
            for item in items
        ],
        "total": total,
        "currency": currency,
        "payment_method": "balance",
        "status": "pending",
        "created_at": now_iso(),
        "paid_at": None,
        "delivered_at": None,
        "delivery_error": None,
        "discount_total": sum(item["discount_total"] for item in items) + coupon_discount_amount,
        "coupon_code": coupon["code"] if coupon else None,
        "coupon_discount": coupon_discount_amount,
        "source_code": user.get("traffic_source_code"),
        "source_kind": user.get("traffic_source_kind"),
    }
    if order_metadata:
        order.update({key: order_metadata[key] for key in (
            "reseller_bot_id", "reseller_admin_tid", "reseller_wholesale", "reseller_margin",
            "idempotency_key", "customer_id", "customer_email"
        ) if key in order_metadata})
    await db.purchases.insert_one(order)

    if coupon:
        reserved_coupon = await reserve_coupon(
            coupon, coupon_buyer, order_id, coupon_discount_amount
        )
        if not reserved_coupon:
            return await _fail_checkout(
                order_id, [], reservation_id, "coupon",
                "Kupon baru saja mencapai batas penggunaan. Silakan coba lagi.",
            )

    allocations = []
    balance_debited = False
    try:
        for item in items:
            product = item["product"]
            qty = item["qty"]

            if product.get("product_kind") == "digital" or product.get("delivery_type") == "inventory" or product.get("inventory_enabled"):
                reserved = await reserve_items(product["_id"], qty, reservation_id)
                if len(reserved) != qty:
                    raise ValueError(f"Stok {product['name']} tidak cukup.")
                allocations.append({
                    "kind": "inventory",
                    "product_id": product["_id"],
                    "items": reserved,
                })
            elif product.get("stock") is not None:
                result = await db.products.update_one(
                    {
                        "_id": product["_id"],
                        "active": True,
                        "stock": {"$gte": qty},
                    },
                    {"$inc": {"stock": -qty}},
                )
                if result.modified_count != 1:
                    raise ValueError(f"Stok {product['name']} tidak cukup.")
                allocations.append({
                    "kind": "stock",
                    "product_id": product["_id"],
                    "qty": qty,
                })

        update = {
            "$inc": {field: -total},
        }
        if preserve_cart:
            fresh_cart_user = await wallet_collection.find_one(wallet_query, {"cart": 1})
            update["$set"] = {
                "cart": _cart_after_purchase(
                    (fresh_cart_user or {}).get("cart", []),
                    cart_items,
                ),
            }
        else:
            update["$set"] = {"cart": []}

        balance_filter = {**wallet_query, field: {"$gte": total}}
        if wallet_is_bot:
            balance_filter["frozen"] = {"$ne": True}
        else:
            balance_filter["account_disabled"] = {"$ne": True}
        balance_result = await wallet_collection.update_one(
            balance_filter,
            update,
        )
        if balance_result.modified_count != 1:
            return await _fail_checkout(
                order_id,
                allocations,
                reservation_id,
                "balance",
                "Saldo tidak cukup atau akun dibekukan.",
                user=user,
                field=field,
                total=0.0,
                wallet_collection=wallet_collection,
                wallet_query=wallet_query,
            )

        balance_debited = True

        await db.purchases.update_one(
            {"_id": order_id, "status": "pending"},
            {"$set": {"status": "paid", "paid_at": now_iso()}},
        )

        if user.get("traffic_source_code") and telegram_id:
            await db.prospects.update_many(
                {"tg_user_id": telegram_id},
                {"$set": {"status": "customer", "customer_order_id": order_id, "converted_at": now_iso()}},
            )

        for allocation in allocations:
            if allocation["kind"] == "inventory":
                await commit_items(reservation_id, order_id, telegram_id, customer_id=customer_id)

        fresh_user = await wallet_collection.find_one(wallet_query, {field: 1})
        remaining_balance = float((fresh_user or {}).get(field, 0))

        return {
            "ok": True,
            "order": order,
            "items": items,
            "allocations": allocations,
            "remaining_balance": remaining_balance,
        }

    except Exception as exc:
        for allocation in allocations:
            if allocation["kind"] == "stock":
                await db.products.update_one(
                    {"_id": allocation["product_id"]},
                    {"$inc": {"stock": allocation["qty"]}},
                )

        await release_items(reservation_id)
        await release_coupon(order_id)

        if balance_debited:
            await wallet_collection.update_one(
                {**wallet_query, "checkout_refund_ids": {"$ne": order_id}},
                {
                    "$inc": {field: total},
                    "$addToSet": {"checkout_refund_ids": order_id},
                },
            )

        await db.purchases.update_one(
            {"_id": order_id},
            {"$set": {
                "status": "failed",
                "delivery_error": str(exc),
            }},
        )
        return {
            "ok": False,
            "error": "checkout",
            "message": str(exc),
        }
