"""Stable, additive order-line snapshots; never copy inventory payloads."""
import math
from uuid import uuid5, NAMESPACE_URL
from .fulfillment_types import CommerceError, resolve_fulfillment_type

SNAPSHOT_FIELDS = ("delivery_type", "inventory_mode", "inventory_enabled", "inventory_schema", "product_kind", "service_wait_minutes", "service_message_template")


def normalize_order_item(item, *, order_id, position, product=None):
    product = product or {}
    pid = item.get("product_id") or item.get("pid") or product.get("_id")
    quantity = item.get("quantity", item.get("qty", 1))
    try:
        qty = int(quantity)
        if isinstance(quantity, bool) or qty < 1 or float(quantity) != qty:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise CommerceError("Invalid order item quantity") from None
    if not pid:
        raise CommerceError("Order item requires a product ID")
    try:
        unit_price = float(item.get("unit_price", 0))
        subtotal = float(item.get("subtotal", unit_price * qty))
        if not math.isfinite(unit_price) or not math.isfinite(subtotal) or min(unit_price, subtotal) < 0:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise CommerceError("Invalid order item price") from None
    line_id = item.get("line_id") or str(uuid5(NAMESPACE_URL, f"sellerbottel:line:{order_id}:{position}"))
    # An explicit item classification is the immutable purchase-time truth.
    kind = resolve_fulfillment_type(item if item.get("fulfillment_type") is not None else product or item)
    snapshot = dict(item.get("fulfillment_snapshot") or {})
    for field in SNAPSHOT_FIELDS:
        if field not in snapshot:
            snapshot[field] = item.get(field, product.get(field))
    snapshot["fulfillment_type"] = kind.value
    return {**item, "product_id": str(pid), "name": item.get("name", product.get("name", "Produk")),
            "line_id": line_id, "qty": qty, "quantity": qty,
            "unit_price": unit_price, "subtotal": subtotal,
            "variant_id": item.get("variant_id"), "sku": item.get("sku"),
            "fulfillment_type": kind.value, "fulfillment_group_key": line_id,
            "metadata": {**(item.get("metadata") or {}), **{key: snapshot[key] for key in ("delivery_type", "inventory_mode")}},
            "fulfillment_snapshot": snapshot}


def normalize_order_items(items, *, order_id, products=None):
    products = products or {}
    result = [normalize_order_item(item, order_id=order_id, position=i, product=products.get(str(item.get("product_id") or item.get("pid")))) for i, item in enumerate(items)]
    if len({line["line_id"] for line in result}) != len(result):
        raise CommerceError("Duplicate order line ID")
    return result


def product_for_line(line, current=None):
    """Reuse payload lookup, but never mutable product classification/name."""
    return {**(current or {}), **(line.get("fulfillment_snapshot") or {}),
            "_id": line["product_id"], "name": line["name"], "fulfillment_type": line["fulfillment_type"]}
