"""Tenant-scoped wrappers around admin endpoints.

Setiap endpoint di sini:
1. Validasi JWT tenant owner
2. Install BotTenantScope dengan DB tenant
3. Panggil fungsi admin yang sama (otomatis pakai DB tenant via _TenantDbProxy)
4. Restore scope

Hasil: fitur 100% sama dengan panel utama, tapi data terisolasi per tenant.
"""
from fastapi import APIRouter, Request, HTTPException, status, Depends, UploadFile, File, Form, Query, Response
from typing import Optional
import contextvars

router = APIRouter(prefix="/api/public/tenant/full", tags=["tenant-full"])

# Import after to avoid circular
def _get_tenant_scope(request: Request):
    """Validasi JWT dan return (owner, tenant, db_handle)."""
    from auth import get_jwt_secret, JWT_ALGORITHM
    import jwt as _jwt
    from bson import ObjectId
    from db import client as _client
    from tenant_db import resolve_platform_database_name
    import os

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login dulu.")
    try:
        payload = _jwt.decode(auth[7:], get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        owner_id = payload.get("sub")
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token tidak valid.")

    pdb = _client[resolve_platform_database_name(os.environ)]
    try:
        owner = pdb["tenant_owners"].find_one({"_id": ObjectId(owner_id)})
    except Exception:
        owner = None
    # Note: sync find_one, need async - use async version below
    return None


async def _require_tenant_ctx(request: Request):
    """Async: validasi JWT, install scope, return restore token."""
    from auth import get_jwt_secret, JWT_ALGORITHM
    import jwt as _jwt
    from bson import ObjectId
    from db import client as _client
    from tenant_db import resolve_platform_database_name
    from dependencies import get_tenant_registry
    from bot_tenant_scope import BotTenantScope, _install
    import os

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login dulu.")
    try:
        payload = _jwt.decode(auth[7:], get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        owner_id = payload.get("sub")
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token tidak valid.")

    pdb = _client[resolve_platform_database_name(os.environ)]
    try:
        owner = await pdb["tenant_owners"].find_one({"_id": ObjectId(owner_id)})
    except Exception:
        owner = None
    if not owner:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Akun tidak ditemukan.")

    registry = get_tenant_registry()
    tenant = await registry.get_tenant(owner.get("tenant_slug"))
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant tidak ditemukan.")

    # Install scope dengan DB tenant
    from db import client as db_client
    tenant_db = db_client[tenant.get("database_name")]
    scope = BotTenantScope(
        tenant_id=str(tenant.get("_id")),
        slug=tenant.get("slug"),
        database_name=tenant.get("database_name"),
        db_handle=tenant_db,
    )
    token = _install(scope)
    return token


def _restore_ctx(token):
    from bot_tenant_scope import _restore
    try:
        _restore(token)
    except Exception:
        pass


# === PRODUCTS ===
@router.get("/products")
async def tenant_list_products(request: Request):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import list_products
        from bson import ObjectId
        result = await list_products()
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
            image=image, remove_image=remove_image, file=file,
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
            image=image, remove_image=remove_image, file=file,
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
async def tenant_create_catalog(request: Request, body: dict):
    token = await _require_tenant_ctx(request)
    try:
        from catalog_routes import create_catalog, CatalogBody
        return await create_catalog(CatalogBody(name=body.get("name", "")))
    finally:
        _restore_ctx(token)


@router.put("/catalogs/rename")
async def tenant_rename_catalog(request: Request, body: dict):
    token = await _require_tenant_ctx(request)
    try:
        from catalog_routes import rename_catalog, RenameBody
        return await rename_catalog(RenameBody(old_name=body.get("old_name", ""), name=body.get("name", "")))
    finally:
        _restore_ctx(token)


@router.put("/catalogs/assign")
async def tenant_assign_catalog(request: Request, body: dict):
    token = await _require_tenant_ctx(request)
    try:
        from catalog_routes import assign_catalog, AssignBody
        return await assign_catalog(AssignBody(name=body.get("name", ""), product_ids=body.get("product_ids", [])))
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
        from bson import ObjectId
        # Convert string ID ke ObjectId
        try:
            pid_obj = ObjectId(pid)
        except:
            pid_obj = pid
        return await inventory_list(pid=pid_obj, status=status, offset=offset, limit=limit)
    finally:
        _restore_ctx(token)


@router.get("/products/{pid}/inventory/summary")
async def tenant_inventory_summary(request: Request, pid: str):
    token = await _require_tenant_ctx(request)
    try:
        from admin_routes import inventory_summary
        from bson import ObjectId
        try:
            pid_obj = ObjectId(pid)
        except:
            pid_obj = pid
        return await inventory_summary(pid=pid_obj)
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
