"""V2 tenant-scoped commerce routes with injected context."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from catalog_repository import CatalogRepository
from customer_identity_repository import find_or_create_customer_by_email
from tenant_context import TenantContext, get_tenant_context
from tenant_inventory import TenantInventoryRepository
from tenant_orders_repository import TenantOrdersRepository
from wallet_ledger import create_ledger_entry, wallet_balance
from platform_rbac import require_tenant_role_dynamic
from auth import get_current_admin

# Authorization dependencies are dynamic because tenant scope comes from
# the X-Tenant-ID-derived TenantContext at request time.
require_tenant_viewer = require_tenant_role_dynamic("tenant_viewer")
require_tenant_operator = require_tenant_role_dynamic("tenant_operator")

VIEWER_ACCESS = [Depends(require_tenant_viewer)]
OPERATOR_ACCESS = [Depends(require_tenant_operator)]

router = APIRouter(tags=["v2-commerce"])


# TODO: Add require_tenant_role authorization once dynamic tenant context dependency is supported
# Current blocker: require_tenant_role cannot receive context tenant dynamically as a regular static dependency


# Pydantic request/response models

class CreateProductRequest(BaseModel):
    name: str
    price: str = Field(..., description="Decimal as string")
    currency: str = "USD"
    description: str | None = None
    category: str | None = None
    active: bool = True


class UpdateProductRequest(BaseModel):
    name: str | None = None
    price: str | None = None
    description: str | None = None
    category: str | None = None
    active: bool | None = None


class AddInventoryRequest(BaseModel):
    product_id: str
    serial_number: str | None = None
    metadata: dict[str, Any] | None = None


class CreateOrderRequest(BaseModel):
    customer_id: str
    invoice_id: str
    total: str = Field(..., description="Decimal as string")
    currency: str = "USD"
    idempotency_key: str | None = None
    items: list[dict[str, Any]] | None = None


class CreateWalletEntryRequest(BaseModel):
    entry_type: Literal["debit", "credit"]
    amount: str = Field(..., description="Decimal as string")
    currency: str
    reference_id: str
    idempotency_key: str
    description: str = ""


class SandboxPaymentRequest(BaseModel):
    order_id: str
    amount: str = Field(..., description="Decimal as string")
    currency: str


# Product endpoints

@router.post("/products", dependencies=OPERATOR_ACCESS)
async def create_product(
    request: CreateProductRequest,
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    """Create a product scoped to the tenant context."""
    repo = CatalogRepository(context)
    product_data = request.model_dump()
    product = await repo.create_product(product_data)
    return product


@router.get("/products", dependencies=VIEWER_ACCESS)
async def list_products(
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> list[dict[str, Any]]:
    """List all products for the tenant context."""
    repo = CatalogRepository(context)
    products = await repo.list_products()
    return products


@router.patch("/products/{product_id}", dependencies=OPERATOR_ACCESS)
async def update_product(
    product_id: str,
    request: UpdateProductRequest,
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    """Update a product scoped to the tenant context."""
    repo = CatalogRepository(context)
    updates = {k: v for k, v in request.model_dump().items() if v is not None}

    updated = await repo.update_product(product_id, updates)
    if updated is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return updated


# Inventory endpoints

@router.post("/inventory", dependencies=OPERATOR_ACCESS)
async def add_inventory(
    request: AddInventoryRequest,
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    """Add an inventory item scoped to the tenant context."""
    repo = TenantInventoryRepository(context)
    item_data = request.model_dump()
    item = await repo.add_item(item_data)
    return item


@router.get("/inventory/{product_id}", dependencies=VIEWER_ACCESS)
async def get_inventory(
    product_id: str,
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    """Get inventory summary for a product without exposing secret fields."""
    repo = TenantInventoryRepository(context)

    # Count items by status
    all_items = await repo.collection.find({
        "tenant_id": context.tenant_id,
        "product_id": product_id,
    }).to_list(length=None)

    available_count = sum(1 for item in all_items if item.get("status") == "available")
    reserved_count = sum(1 for item in all_items if item.get("status") == "reserved")
    sold_count = sum(1 for item in all_items if item.get("status") == "sold")

    return {
        "product_id": product_id,
        "available_count": available_count,
        "reserved_count": reserved_count,
        "sold_count": sold_count,
        "total_count": len(all_items),
    }


# Order endpoints

@router.post("/orders", dependencies=OPERATOR_ACCESS)
async def create_order(
    request: CreateOrderRequest,
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    """Create an order scoped to the tenant context."""
    repo = TenantOrdersRepository(context)

    order_data = {
        "total": request.total,
        "currency": request.currency,
    }
    if request.items:
        order_data["items"] = request.items

    order = await repo.create_order(
        customer_id=request.customer_id,
        invoice_id=request.invoice_id,
        idempotency_key=request.idempotency_key,
        order_data=order_data,
    )

    return order


@router.get("/orders", dependencies=VIEWER_ACCESS)
async def list_orders(
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> list[dict[str, Any]]:
    """List all orders for the tenant context."""
    orders = await context.database.purchases.find({
        "tenant_id": context.tenant_id,
    }).to_list(length=None)
    return orders


# Wallet endpoints

@router.post("/wallet/entries", dependencies=OPERATOR_ACCESS)
async def create_wallet_entry(
    request: CreateWalletEntryRequest,
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    """Create a wallet ledger entry scoped to the tenant context."""
    result = await create_ledger_entry(
        db=context.database,
        context=context,
        entry_type=request.entry_type,
        amount=request.amount,
        currency=request.currency,
        reference_id=request.reference_id,
        idempotency_key=request.idempotency_key,
        description=request.description,
    )
    return jsonable_encoder(result, custom_encoder={ObjectId: str})


@router.get("/wallet/{customer_id}/balance", dependencies=VIEWER_ACCESS)
async def get_wallet_balance(
    customer_id: str,
    currency: str,
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    """Get wallet balance for the tenant context."""
    balance = await wallet_balance(
        db=context.database,
        context=context,
        currency=currency,
    )

    return {
        "customer_id": customer_id,
        "balance": str(balance),
        "currency": currency,
    }


# Sandbox payment endpoint

@router.post("/payments/sandbox", dependencies=OPERATOR_ACCESS)
async def create_sandbox_payment(
    request: SandboxPaymentRequest,
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, Any]:
    """Create a sandbox payment scoped to the tenant context."""
    payment = {
        "id": str(uuid4()),
        "tenant_id": context.tenant_id,
        "order_id": request.order_id,
        "amount": request.amount,
        "currency": request.currency,
        "status": "paid",
        "created_at": datetime.now(timezone.utc),
        "finalized_at": datetime.now(timezone.utc),
    }

    return payment
