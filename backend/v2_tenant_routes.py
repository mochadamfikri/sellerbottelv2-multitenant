"""V2 tenant context verification route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from tenant_context import TenantContext, get_tenant_context

router = APIRouter(tags=["v2-tenant"])


@router.get("/info")
def tenant_info(
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> dict[str, str]:
    """Return verified tenant identity; no tenant business logic yet."""
    return {
        "tenant_id": context.tenant_id,
        "status": context.status,
        "database_name": context.database["database_name"],
    }
