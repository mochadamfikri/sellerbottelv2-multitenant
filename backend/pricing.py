from datetime import datetime, timezone

from db import db
from rates import get_rate


async def base_price(product, currency):
    if currency == "USD":
        return round(float(product.get("price_usd") or 0), 2)
    if product.get("price_idr") is not None:
        return round(float(product["price_idr"]))
    rate = await get_rate()
    return round(float(product.get("price_usd") or 0) * rate / 100) * 100


def _active_date(doc):
    now = datetime.now(timezone.utc)
    try:
        starts = doc.get("starts_at")
        ends = doc.get("ends_at")
        starts = datetime.fromisoformat(starts) if starts else None
        ends = datetime.fromisoformat(ends) if ends else None
        if starts and starts.tzinfo is None:
            starts = starts.replace(tzinfo=timezone.utc)
        if ends and ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        if starts and now < starts:
            return False
        if ends and now > ends:
            return False
    except (ValueError, TypeError):
        return False
    return doc.get("active", True)


async def price_for_product(product, currency, quantity=1):
    quantity = max(1, int(quantity))
    base = await base_price(product, currency)

    cursor = db.discounts.find({"active": True}).sort(
        [("priority", -1), ("min_qty", -1)]
    )

    best = None
    best_rank = None
    async for discount in cursor:
        if not _active_date(discount):
            continue

        product_ids = discount.get("product_ids") or []
        if product_ids and product["_id"] not in product_ids:
            continue

        min_qty = int(discount.get("min_qty", 1))
        max_qty = discount.get("max_qty")
        if quantity < min_qty:
            continue
        if max_qty is not None and quantity > int(max_qty):
            continue

        mode = discount.get("mode")
        value = float(discount.get("value") or 0)
        if mode == "percent":
            discount_per_unit = base * min(100.0, max(0.0, value)) / 100.0
        elif mode == "fixed":
            fixed_currency = discount.get("fixed_currency") or currency
            fixed_value = max(0.0, value)
            if fixed_currency == "IDR" and currency == "USD":
                rate = await get_rate()
                fixed_value = fixed_value / rate
            elif fixed_currency == "USD" and currency == "IDR":
                rate = await get_rate()
                fixed_value = fixed_value * rate
            discount_per_unit = min(base, fixed_value)
        else:
            continue

        candidate = {
            "discount_id": discount["_id"],
            "name": discount.get("name", ""),
            "discount_per_unit": discount_per_unit,
        }

        rank = (
            int(discount.get("priority", 0)),
            round(float(discount_per_unit), 8),
            int(discount.get("min_qty", 1)),
            str(discount.get("_id") or ""),
        )
        if best_rank is None or rank > best_rank:
            best = candidate
            best_rank = rank

    discount_per_unit = best["discount_per_unit"] if best else 0.0
    if currency == "USD":
        unit_price = round(max(0.0, base - discount_per_unit), 2)
    else:
        unit_price = round(max(0.0, base - discount_per_unit))
    applied_discount = round(base - unit_price, 2)

    return {
        "base_unit_price": base,
        "unit_price": unit_price,
        "discount_per_unit": applied_discount,
        "discount_total": round(applied_discount * quantity, 2),
        "discount_id": best["discount_id"] if best else None,
        "discount_name": best["name"] if best else None,
    }
