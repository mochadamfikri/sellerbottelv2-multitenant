"""Additive tenant-owner APIs for physical commerce; no platform URL dependency."""
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File
from pydantic import BaseModel, Field, ConfigDict
from db import db, _resolve_db
from tenant_full_routes import _require_tenant_ctx, _restore_ctx
from commerce.fulfillment_types import CommerceError, FulfillmentType, resolve_fulfillment_type
from commerce.physical.models import VariantBody, create_variant, public_variant
from commerce.physical.stock import PhysicalStock, ensure_indexes
from commerce.physical.workflow import transition, project_shipment, repair_compensation


async def owner_scope(request: Request):
    token = await _require_tenant_ctx(request)
    try:
        yield
    finally:
        _restore_ctx(token)

router = APIRouter(prefix="/api/public/tenant/full/physical", tags=["physical"], dependencies=[Depends(owner_scope)])


class ProductBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    price_idr: float = Field(ge=0, allow_inf_nan=False)
    catalog_name: str = Field(default="", max_length=80)
    has_variants: bool = False
    default_weight: float = Field(default=0, ge=0, allow_inf_nan=False)
    default_length: float = Field(default=0, ge=0, allow_inf_nan=False)
    default_width: float = Field(default=0, ge=0, allow_inf_nan=False)
    default_height: float = Field(default=0, ge=0, allow_inf_nan=False)
    active: bool = True


async def physical_product(pid):
    product = await db.products.find_one({"_id": pid})
    if not product or resolve_fulfillment_type(product) != FulfillmentType.PHYSICAL:
        raise HTTPException(404, "Physical product not found")
    return product


def product_document(body):
    data = body.model_dump()
    profile = {key: data.pop(key) for key in ("has_variants", "default_weight", "default_length", "default_width", "default_height")}
    profile["shipping_enabled"] = True
    return {**data, "fulfillment_type": FulfillmentType.PHYSICAL.value, "product_kind": "physical", "requires_shipping": True,
            "delivery_type": "manual_shipping", "physical_profile": profile, "inventory_enabled": False, "price_usd": 0}


@router.post("/products")
async def add_product(body: ProductBody):
    product = {"_id": str(uuid4()), **product_document(body), "created_at": datetime.now(timezone.utc)}
    await ensure_indexes(_resolve_db())
    await db.products.insert_one(product.copy())
    return product


@router.put("/products/{pid}")
async def edit_product(pid: str, body: ProductBody):
    await physical_product(pid)
    await db.products.update_one({"_id": pid}, {"$set": {**product_document(body), "updated_at": datetime.now(timezone.utc)}})
    return await db.products.find_one({"_id": pid})


@router.post("/products/{pid}/image")
async def upload_image(pid: str, image: UploadFile = File(...)):
    await physical_product(pid)
    from admin_routes import _store_product_image
    from storage import delete_object
    image_data = await _store_product_image(pid, image)
    try:
        await db.products.update_one({"_id": pid}, {"$set": {"image_path": image_data["path"], "image_content_type": image_data["content_type"]}})
    except Exception:
        await delete_object(image_data["path"])
        raise
    return {"ok": True}


@router.get("/products/{pid}/variants")
async def list_variants(pid: str):
    await physical_product(pid)
    variants = await db.physical_variants.find({"product_id": pid}).sort("created_at", 1).to_list(None)
    for variant in variants:
        await PhysicalStock(_resolve_db()).project(variant)
    return [public_variant(v) for v in variants]


@router.post("/products/{pid}/variants")
async def add_variant(pid: str, body: VariantBody):
    await physical_product(pid)
    return await create_variant(_resolve_db(), pid, body)


@router.put("/variants/{vid}")
async def edit_variant(vid: str, body: VariantBody):
    variant = await db.physical_variants.find_one({"_id": vid})
    if not variant:
        raise HTTPException(404, "Variant not found")
    if body.sku != variant["sku"]:
        raise CommerceError("SKU is immutable; deactivate and create a new variant")
    await db.physical_variants.update_one({"_id": vid}, {"$set": {**body.model_dump(), "updated_at": datetime.now(timezone.utc)}})
    return public_variant(await db.physical_variants.find_one({"_id": vid}))


class StockBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(pattern=r"^(RECEIVE|ADJUSTMENT|DAMAGE)$")
    quantity: int = Field(strict=True)
    reference_id: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    reason: str = Field(min_length=1, max_length=240)


@router.post("/variants/{vid}/stock")
async def stock_action(vid: str, body: StockBody):
    if not await db.physical_variants.find_one({"_id": vid}):
        raise HTTPException(404, "Variant not found")
    return await PhysicalStock(_resolve_db()).move(vid, body.type, body.quantity, reference_id=body.reference_id, reason=body.reason, actor="tenant_owner")


@router.get("/variants/{vid}/stock-movements")
async def movements(vid: str):
    if not await db.physical_variants.find_one({"_id": vid}):
        raise HTTPException(404, "Variant not found")
    await PhysicalStock(_resolve_db()).get(vid)
    return await db.stock_movements.find({"variant_id": vid}).sort("created_at", -1).to_list(200)


class ShippingBody(BaseModel):
    manual_shipping_fee: float = Field(ge=0, le=10000000, allow_inf_nan=False)


@router.get("/shipping")
async def get_shipping():
    settings = await db.settings.find_one({"_id": "main"}) or {}
    return {"shipping_mode": "manual_shipping", "manual_shipping_fee": settings.get("manual_shipping_fee", 0)}


@router.put("/shipping")
async def set_shipping(body: ShippingBody):
    await db.settings.update_one({"_id": "main"}, {"$set": {"shipping_mode": "manual_shipping", **body.model_dump()}}, upsert=True)
    return await get_shipping()


class ShipmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    carrier_name: str = Field(default="", max_length=80)
    tracking_number: str = Field(default="", max_length=100)


@router.get("/orders/{oid}")
async def order_physical(oid: str):
    order = await db.purchases.find_one({"_id": oid})
    if not order:
        raise HTTPException(404, "Order not found")
    from commerce.fulfillment.router import current_repository, require_active_context
    repo = current_repository()
    await require_active_context(repo)
    records = [r for r in await repo.list_order(oid) if r["type"] == FulfillmentType.PHYSICAL]
    for record in records:
        await repair_compensation(repo, order, record)
        await project_shipment(repo, record)
    return {"order_status": order["status"], "requires_shipping": order.get("requires_shipping", False), "shipping_address": order.get("shipping_address"), "shipping_fee": order.get("shipping_fee", 0),
            "items": order.get("items", []), "fulfillments": [{k: v for k, v in r.items() if k not in {"claim_token", "lease_expires_at"}} for r in records]}


@router.post("/orders/{oid}/fulfillments/{fid}")
async def shipment_action(oid: str, fid: str, body: ShipmentBody):
    try:
        return await transition(oid, fid, **body.model_dump())
    except CommerceError as error:
        if str(error) == "Physical fulfillment not found":
            raise HTTPException(404, str(error)) from None
        raise


@router.post("/orders/{oid}/recover")
async def recover_paid_order(oid: str):
    """Explicit reconciliation of web initialization; durable claims forbid replay."""
    order = await db.purchases.find_one({"_id": oid, "purchase_source": "WEB", "requires_shipping": True})
    if not order:
        raise HTTPException(404, "Physical web order not found")
    if order.get("status") != "delivery_failed":
        raise HTTPException(409, "Only paid delivery failures require reconciliation")
    from commerce.fulfillment.router import ensure_order_fulfillments
    from commerce.fulfillment.adapters import fulfill_web_order
    from inventory import commit_items
    await ensure_order_fulfillments(order)
    await PhysicalStock(_resolve_db()).consume_order(order)
    if order.get("payment_method") == "qris":
        await commit_items(f"qris:{oid}", oid, order.get("user_tid"), customer_id=order.get("customer_id"))
    states = await fulfill_web_order(order)
    if any(s not in {"pending", "queued", "delivered", "completed", "packing", "ready_to_ship", "shipped"} for s in states):
        raise HTTPException(409, "Delivery claim needs operator reconciliation")
    status = "service_waiting" if "queued" in states else "physical_pending"
    await db.purchases.update_one({"_id": oid, "status": "delivery_failed"}, {"$set": {"status": status, "delivery_error": None}})
    from commerce.physical.workflow import refresh_order
    from commerce.fulfillment.router import current_repository
    await refresh_order(current_repository(), oid)
    return {"ok": True, "status": (await db.purchases.find_one({"_id": oid}))["status"]}
