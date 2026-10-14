"""Validated physical variant and Indonesian-default address contracts."""
import re
from datetime import datetime, timezone
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator
from ..fulfillment_types import CommerceError, FulfillmentType, resolve_fulfillment_type
from .stock import ensure_indexes


class Address(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    recipient_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=7, max_length=30, pattern=r"^[+0-9 ()-]+$")
    address_line_1: str = Field(min_length=3, max_length=240)
    address_line_2: str = Field(default="", max_length=240)
    district: str = Field(default="", max_length=100)
    city: str = Field(min_length=1, max_length=100)
    province: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=3, max_length=12)
    country: str = Field(default="ID", pattern=r"^[A-Z]{2}$")
    notes: str = Field(default="", max_length=300)

    @field_validator("postal_code")
    @classmethod
    def postal(cls, value, info):
        # Country is validated again below because postal_code precedes country.
        if not re.fullmatch(r"[A-Za-z0-9 -]{3,12}", value):
            raise ValueError("Invalid postal code")
        return value


def address_snapshot(raw):
    try:
        address = Address.model_validate(raw or {}).model_dump()
        if address["country"] == "ID" and not re.fullmatch(r"[0-9]{5}", address["postal_code"]):
            raise ValueError
        return address
    except ValueError:
        raise CommerceError("Valid shipping address required") from None


class VariantBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sku: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    barcode: str = Field(default="", max_length=80)
    option_values: dict[str, str] = Field(default_factory=dict, max_length=12)
    price_override: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    weight: float = Field(default=0, ge=0, allow_inf_nan=False)
    length: float = Field(default=0, ge=0, allow_inf_nan=False)
    width: float = Field(default=0, ge=0, allow_inf_nan=False)
    height: float = Field(default=0, ge=0, allow_inf_nan=False)
    active: bool = True

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value):
        return value.upper()

    @field_validator("option_values")
    @classmethod
    def options(cls, value):
        if any(not k.strip() or not v.strip() or len(k) > 40 or len(v) > 80 or any(ord(c) < 32 for c in k + v) for k, v in value.items()):
            raise ValueError("Invalid variant options")
        if len({key.strip() for key in value}) != len(value):
            raise ValueError("Duplicate normalized variant option")
        return {k.strip(): v.strip() for k, v in value.items()}


async def create_variant(database, product_id, body):
    product = await database.products.find_one({"_id": product_id})
    if not product or resolve_fulfillment_type(product) != FulfillmentType.PHYSICAL:
        raise CommerceError("Physical product not found")
    await ensure_indexes(database)
    now = datetime.now(timezone.utc)
    variant = {"_id": str(uuid4()), "product_id": product_id, **body.model_dump(), "on_hand": 0, "reserved": 0,
               "stock_version": 0, "stock_events": [], "created_at": now, "updated_at": now}
    from pymongo.errors import DuplicateKeyError
    try:
        await database.physical_variants.insert_one(variant.copy())
    except DuplicateKeyError:
        raise CommerceError("SKU already exists in this tenant") from None
    return public_variant(variant)


def public_variant(variant):
    result = {k: v for k, v in variant.items() if k not in {"stock_events", "stock_version"}}
    result["available"] = variant.get("on_hand", 0) - variant.get("reserved", 0)
    result["label"] = " / ".join(variant.get("option_values", {}).values()) or variant["sku"]
    return result


async def checkout_variant(database, product, variant_id):
    variant = await database.physical_variants.find_one({"_id": variant_id, "product_id": product["_id"], "active": True})
    if not variant:
        raise CommerceError("Active physical variant required")
    return variant


def line_snapshot(variant):
    return {"variant_id": variant["_id"], "sku": variant["sku"], "variant_options": dict(variant["option_values"]),
            "variant_label": " / ".join(variant["option_values"].values()) or variant["sku"], "weight": variant["weight"],
            "dimensions": {k: variant[k] for k in ("length", "width", "height")}}


async def shipping_quote(database, products, address=None, *, require_address=True):
    physical = any(resolve_fulfillment_type(product) == FulfillmentType.PHYSICAL for product in products)
    if not physical:
        return {"shipping_fee": 0, "requires_shipping": False}
    settings = await database.settings.find_one({"_id": "main"}) or {}
    try:
        fee = float(settings.get("manual_shipping_fee", 0))
        import math
        if not math.isfinite(fee) or fee < 0:
            raise ValueError
    except (ValueError, TypeError):
        raise CommerceError("Manual shipping configuration invalid") from None
    result = {"shipping_fee": round(fee, 2), "requires_shipping": True, "shipping_mode": "manual_shipping"}
    if require_address:
        result["shipping_address"] = address_snapshot(address)
    return result


def normalize_cart(items):
    quantities = {}
    for item in items:
        pid, vid = str(item.get("pid") or ""), item.get("variant_id")
        raw_qty = item.get("qty", 1)
        try:
            qty = int(raw_qty)
            if isinstance(raw_qty, bool) or float(raw_qty) != qty or qty < 1 or qty > 100:
                raise ValueError
        except (ValueError, TypeError):
            raise CommerceError("Invalid cart quantity") from None
        if not pid or (vid is not None and not isinstance(vid, str)):
            raise CommerceError("Invalid cart item")
        key = (pid, vid)
        quantities[key] = quantities.get(key, 0) + qty
        if quantities[key] > 1000:
            raise CommerceError("Invalid cart quantity")
    if not quantities:
        raise CommerceError("Empty cart")
    return [{"pid": pid, "variant_id": vid, "qty": qty} for (pid, vid), qty in quantities.items()]
