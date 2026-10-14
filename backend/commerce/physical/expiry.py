"""Provider-free expiry for storefront tenants, including those without bots."""
import asyncio
import logging
from bot_tenant_scope import BotTenantScope, use_bot_tenant

logger = logging.getLogger(__name__)

async def expire_physical_tenants():
    from db import client, _default_db
    from dependencies import get_tenant_registry
    from direct_checkout import expire_qris_orders
    seen = set()
    # Legacy/default storefront, then each provisioned registry database.
    async with use_bot_tenant(None):
        await expire_qris_orders(physical_only=True)
    seen.add(_default_db.name)
    for tenant in await get_tenant_registry().list_tenants():
        name = tenant.get("database_name")
        if not name or name in seen:
            continue
        seen.add(name)
        scope = BotTenantScope(tenant_id=str(tenant["_id"]), slug=tenant["slug"], database_name=name,
            db_handle=client[name], bot_token="unused-physical-expiry")
        try:
            async with use_bot_tenant(scope):
                await expire_qris_orders(physical_only=True)
        except Exception as error:
            logger.warning("Physical expiry retry tenant=%s exception=%s", tenant["slug"], type(error).__name__)

async def run_physical_expiry(stop_event):
    while not stop_event.is_set():
        try:
            await expire_physical_tenants()
        except Exception as error:
            logger.warning("Physical expiry scan retry exception=%s", type(error).__name__)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
