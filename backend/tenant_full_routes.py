"""Tenant-scoped wrappers around admin endpoints.

Setiap endpoint di sini:
1. Validasi JWT tenant owner
2. Install BotTenantScope dengan DB tenant
3. Panggil fungsi admin yang sama (otomatis pakai DB tenant via _TenantDbProxy)
4. Restore scope

Management contracts reuse owner business logic under a validated tenant scope.
"""
from fastapi import APIRouter, Request, HTTPException, status, Depends, UploadFile, File, Form, Query, Response
from typing import Optional
from catalog_routes import CatalogBody, RenameBody, AssignBody

router = APIRouter(prefix="/api/public/tenant/full", tags=["tenant-full"])

async def _require_tenant_ctx(request: Request):
    """Validate the live tenant lifecycle before installing its database/token."""
    from public_registration import _require_tenant_owner, _active_owner_tenant
    from bot_tenant_scope import BotTenantScope, _install
    from db import client
    owner = await _require_tenant_owner(request)
    tenant = await _active_owner_tenant(owner)
    config = (tenant.get("metadata") or {}).get("bot_config") or {}
    bot_token = None
    if config.get("token_encrypted"):
        from inventory import _fernet
        bot_token = _fernet().decrypt(config["token_encrypted"].encode()).decode()
    scope = BotTenantScope(
        tenant_id=str(tenant["_id"]), slug=tenant["slug"],
        database_name=tenant["database_name"], db_handle=client[tenant["database_name"]],
        bot_token=bot_token or "unconfigured-tenant-bot",
        brand_name=config.get("brand_name") or tenant.get("name", ""),
        admin_ids=config.get("admin_ids") or [],
        reseller_enabled=config.get("reseller_enabled", False),
    )
    return _install(scope)


def _restore_ctx(token):
    from bot_tenant_scope import _restore
    _restore(token)


# === PRODUCTS ===
@router.get("/products")
async def tenant_list_products(request: Request):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import list_products
        from bson import ObjectId
        result = await list_products()
        for product in result:
            for field in ("image_url", "catalog_image_url"):
                product[field] = product[field].replace("/api/admin/", "/api/public/tenant/full/")
        # Convert ObjectId ke string
        def _safe(obj):
            if isinstance(obj, ObjectId):
                return str(obj)
            if isinstance(obj, dict):
                return {k: _safe(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_safe(v) for v in obj]
            return obj
        return _safe(result)
    finally:
        _restore_ctx(token)


@router.post("/products")
async def tenant_create_product(
    request: Request,
    name: str = Form(...),
    catalog_name: str = Form("", max_length=80),
    inventory_fields: str = Form("", max_length=4000),
    description: str = Form(""),
    price_usd: float = Form(...),
    price_idr: Optional[float] = Form(None),
    delivery_type: str = Form("link"),
    content: str = Form(""),
    active: bool = Form(True),
    minimum_purchase_qty: int = Form(1),
    stock: Optional[int] = Form(None),
    product_kind: str = Form("digital"),
    stock_mode: str = Form("auto"),
    inventory_mode: str = Form("table"),
    service_wait_minutes: Optional[int] = Form(None),
    service_message_template: str = Form(""),
    image: Optional[UploadFile] = File(None),
    remove_image: bool = Form(False),
    file: Optional[UploadFile] = File(None),
    fulfillment_type: Optional[str] = Form(None),
):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import create_product
        return await create_product(
            name=name, catalog_name=catalog_name, inventory_fields=inventory_fields,
            description=description, price_usd=price_usd, price_idr=price_idr,
            delivery_type=delivery_type, content=content, active=active,
            minimum_purchase_qty=minimum_purchase_qty, stock=stock,
            product_kind=product_kind, stock_mode=stock_mode, inventory_mode=inventory_mode,
            service_wait_minutes=service_wait_minutes,
            service_message_template=service_message_template,
            image=image, remove_image=remove_image, file=file, fulfillment_type=fulfillment_type,
        )
    finally:
        _restore_ctx(token)


@router.put("/products/{pid}")
async def tenant_update_product(
    request: Request,
    pid: str,
    name: str = Form(...),
    catalog_name: str = Form("", max_length=80),
    inventory_fields: str = Form("", max_length=4000),
    description: str = Form(""),
    price_usd: float = Form(...),
    price_idr: Optional[float] = Form(None),
    delivery_type: str = Form("link"),
    content: str = Form(""),
    active: bool = Form(True),
    minimum_purchase_qty: int = Form(1),
    stock: Optional[int] = Form(None),
    product_kind: str = Form("digital"),
    stock_mode: str = Form("auto"),
    inventory_mode: str = Form("table"),
    service_wait_minutes: Optional[int] = Form(None),
    service_message_template: str = Form(""),
    image: Optional[UploadFile] = File(None),
    remove_image: bool = Form(False),
    file: Optional[UploadFile] = File(None),
    fulfillment_type: Optional[str] = Form(None),
):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import update_product
        return await update_product(
            pid=pid, name=name, catalog_name=catalog_name, inventory_fields=inventory_fields,
            description=description, price_usd=price_usd, price_idr=price_idr,
            delivery_type=delivery_type, content=content, active=active,
            minimum_purchase_qty=minimum_purchase_qty, stock=stock,
            product_kind=product_kind, stock_mode=stock_mode, inventory_mode=inventory_mode,
            service_wait_minutes=service_wait_minutes,
            service_message_template=service_message_template,
            image=image, remove_image=remove_image, file=file, fulfillment_type=fulfillment_type,
        )
    finally:
        _restore_ctx(token)


@router.delete("/products/{pid}")
async def tenant_delete_product(request: Request, pid: str):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import delete_product
        return await delete_product(pid)
    finally:
        _restore_ctx(token)


@router.patch("/products/{pid}/toggle")
async def tenant_toggle_product(request: Request, pid: str):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import toggle_product
        return await toggle_product(pid)
    finally:
        _restore_ctx(token)


# === CATALOGS (pakai logic admin langsung via tenant scope) ===
@router.get("/catalogs")
async def tenant_list_catalogs(request: Request):
    token = await _require_tenant_ctx(request)
    try:
        from catalog_routes import list_catalogs
        return await list_catalogs()
    finally:
        _restore_ctx(token)


@router.post("/catalogs")
async def tenant_create_catalog(request: Request, body: CatalogBody):
    token = await _require_tenant_ctx(request)
    try:
        from catalog_routes import create_catalog
        return await create_catalog(body)
    finally:
        _restore_ctx(token)


@router.put("/catalogs/rename")
async def tenant_rename_catalog(request: Request, body: RenameBody):
    token = await _require_tenant_ctx(request)
    try:
        from catalog_routes import rename_catalog
        return await rename_catalog(body)
    finally:
        _restore_ctx(token)


@router.put("/catalogs/assign")
async def tenant_assign_catalog(request: Request, body: AssignBody):
    token = await _require_tenant_ctx(request)
    try:
        from catalog_routes import assign_catalog
        return await assign_catalog(body)
    finally:
        _restore_ctx(token)


@router.delete("/catalogs")
async def tenant_delete_catalog(request: Request, name: str = Query(...)):
    token = await _require_tenant_ctx(request)
    try:
        from catalog_routes import delete_catalog
        return await delete_catalog(name)
    finally:
        _restore_ctx(token)


# === INVENTORY ===
@router.get("/products/{pid}/inventory")
async def tenant_inventory_list(
    request: Request, pid: str,
    status: str = Query("available"), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)
):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import inventory_list
        return await inventory_list(pid=pid, status=status, offset=offset, limit=limit)
    finally:
        _restore_ctx(token)


@router.get("/products/{pid}/inventory/summary")
async def tenant_inventory_summary(request: Request, pid: str):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import inventory_summary
        return await inventory_summary(pid=pid)
    finally:
        _restore_ctx(token)


@router.get("/products/import-template")
async def tenant_product_import_template(request: Request, format: str = Query("xlsx")):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import product_import_template
        return await product_import_template(format=format)
    finally:
        _restore_ctx(token)


@router.post("/products/import")
async def tenant_import_products(
    request: Request,
    file: Optional[UploadFile] = File(None),
    content: str = Form(""),
):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import import_products
        return await import_products(file=file, content=content)
    finally:
        _restore_ctx(token)

from admin_routes import InventoryManualBody
from inventory_admin import SchemaBody, EditBody


@router.post("/products/{pid}/inventory/validate")
async def tenant_validate_inventory(request: Request, pid: str, content: str = Form(""), file: Optional[UploadFile] = File(None), files: list[UploadFile] = File([])):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import validate_inventory
        return await validate_inventory(pid=pid, content=content, file=file, files=files)
    finally:
        _restore_ctx(token)


@router.post("/products/{pid}/inventory/import")
async def tenant_import_inventory(request: Request, pid: str, content: str = Form(""), file: Optional[UploadFile] = File(None), files: list[UploadFile] = File([])):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import import_inventory
        return await import_inventory(pid=pid, content=content, file=file, files=files)
    finally:
        _restore_ctx(token)


@router.post("/products/{pid}/inventory/manual")
async def tenant_add_inventory_manual(request: Request, pid: str, body: InventoryManualBody):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import add_inventory_manual
        return await add_inventory_manual(pid=pid, body=body)
    finally:
        _restore_ctx(token)


@router.delete("/products/{pid}/inventory/{item_id}")
async def tenant_delete_inventory_item(request: Request, pid: str, item_id: str):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import delete_inventory_item
        return await delete_inventory_item(pid=pid, item_id=item_id)
    finally:
        _restore_ctx(token)


@router.get("/products/{pid}/inventory/template")
async def tenant_inventory_template(request: Request, pid: str, format: str = Query("xlsx")):
    token = await _require_tenant_ctx(request)
    try:
        from inventory_admin import inventory_template
        return await inventory_template(pid=pid, format=format)
    finally:
        _restore_ctx(token)


@router.put("/products/{pid}/inventory/schema")
async def tenant_set_schema(request: Request, pid: str, body: SchemaBody):
    token = await _require_tenant_ctx(request)
    try:
        from inventory_admin import set_schema
        return await set_schema(pid=pid, body=body)
    finally:
        _restore_ctx(token)


@router.put("/products/{pid}/inventory/{item_id}")
async def tenant_edit_inventory(request: Request, pid: str, item_id: str, body: EditBody):
    token = await _require_tenant_ctx(request)
    try:
        from inventory_admin import edit_inventory
        return await edit_inventory(pid=pid, item_id=item_id, body=body)
    finally:
        _restore_ctx(token)


@router.post("/products/{pid}/inventory/{item_id}/file")
async def tenant_replace_inventory_file(request: Request, pid: str, item_id: str, file: UploadFile = File(...)):
    token = await _require_tenant_ctx(request)
    try:
        from inventory_admin import replace_inventory_file
        return await replace_inventory_file(pid=pid, item_id=item_id, file=file)
    finally:
        _restore_ctx(token)


@router.post("/products/{pid}/inventory/transform/inspect")
async def tenant_inspect_inventory_file(request: Request, pid: str, file: UploadFile = File(...)):
    token = await _require_tenant_ctx(request)
    try:
        from inventory_transform import inspect_inventory_file
        return await inspect_inventory_file(pid=pid, file=file)
    finally:
        _restore_ctx(token)


@router.post("/products/{pid}/inventory/transform")
async def tenant_transform_inventory_file(request: Request, pid: str, file: UploadFile = File(...), old_domain: str = Form(""), new_domain: str = Form(""), email_column: str = Form(""), password_column: str = Form(""), password_mode: str = Form("keep"), fixed_password: str = Form("")):
    token = await _require_tenant_ctx(request)
    try:
        from inventory_transform import transform_inventory_file
        return await transform_inventory_file(pid=pid, file=file, old_domain=old_domain, new_domain=new_domain, email_column=email_column, password_column=password_column, password_mode=password_mode, fixed_password=fixed_password)
    finally:
        _restore_ctx(token)


@router.get("/orders")
async def tenant_list_orders(request: Request, status: str = Query("all"), search: str = Query(""), limit: int = Query(200, ge=1, le=500)):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import list_orders
        return await list_orders(status=status, search=search, limit=limit)
    finally:
        _restore_ctx(token)


@router.get("/orders/{oid}")
async def tenant_get_order(request: Request, oid: str):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import get_order
        return await get_order(oid=oid)
    finally:
        _restore_ctx(token)


@router.get("/orders/{oid}/fulfillments")
async def tenant_order_fulfillments(request: Request, oid: str):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import get_order
        from commerce.fulfillment.router import current_repository
        await get_order(oid=oid)
        records = await current_repository().list_order(oid)
        return [{key: value for key, value in record.items() if key not in {"claim_token", "lease_expires_at"}} for record in records]
    finally:
        _restore_ctx(token)


@router.post("/orders/{oid}/complete")
async def tenant_complete_service_order(request: Request, oid: str):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import complete_service_order
        return await complete_service_order(oid=oid)
    finally:
        _restore_ctx(token)


@router.post("/orders/{oid}/refund")
async def tenant_refund_order(request: Request, oid: str):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import refund_order
        return await refund_order(oid=oid)
    finally:
        _restore_ctx(token)


@router.post("/orders/{oid}/email/retry")
async def tenant_retry_order_email(request: Request, oid: str):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import retry_order_email
        return await retry_order_email(oid=oid)
    finally:
        _restore_ctx(token)


@router.get("/products/{pid}/image")
async def tenant_admin_product_image(request: Request, pid: str, catalog: bool = Query(False)):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import admin_product_image
        return await admin_product_image(pid=pid, catalog=catalog)
    finally:
        _restore_ctx(token)


@router.get("/stats")
async def tenant_dashboard_stats(request: Request):
    from public_registration import tenant_stats
    return await tenant_stats(request)


@router.get("/users")
async def tenant_bot_users(request: Request):
    from public_registration import tenant_users
    return await tenant_users(request)


@router.post("/broadcasts")
async def tenant_send_broadcast(request: Request, body: dict):
    message = str(body.get("message") or "").strip()
    if not message or len(message) > 4000:
        raise HTTPException(422, "Pesan wajib diisi (maks 4000 karakter).")
    token = await _require_tenant_ctx(request)
    try:
        from bot_tenant_scope import get_current_scope
        if get_current_scope().bot_token == "unconfigured-tenant-bot":
            raise HTTPException(409, "Bot tenant belum dikonfigurasi.")
        from admin_routes import create_broadcast
        return await create_broadcast(text=message, lang="all", search="", status="all",
            button_text="", button_url="", photo=None, product_id="", auto_image=False)
    finally:
        _restore_ctx(token)


@router.get("/broadcasts")
async def tenant_list_broadcasts(request: Request):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import list_broadcasts
        return await list_broadcasts()
    finally:
        _restore_ctx(token)
