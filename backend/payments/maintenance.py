"""Read-only provider expiry polling and trusted receipt/projection repair.

No create/refund/payout is retried by this worker. C2's provider-free expiry
worker remains separate. Only registered tenant records are considered.
"""
import asyncio
import logging
from datetime import datetime
from bot_tenant_scope import BotTenantScope, use_bot_tenant
from .models import now, utc

logger = logging.getLogger(__name__)

async def sweep():
    from db import client, platform_db
    from dependencies import get_tenant_registry
    from .orchestrator import payment_adapter, apply_event
    from .webhook import process_receipt
    platform = platform_db()
    for receipt in await platform.payment_events.find({"$or": [{"state": "accepted"}, {"state": "processing", "lease_until": {"$lte": now()}}]}).limit(50).to_list(50):
        try:
            await process_receipt(platform, client, receipt)
        except Exception as error:
            logger.warning("Payment receipt retry exception=%s", type(error).__name__)
    for tenant in await get_tenant_registry().list_tenants():
        if not tenant.get("database_name"):
            continue
        database = client[tenant["database_name"]]
        scope = BotTenantScope(tenant_id=tenant["_id"], slug=tenant["slug"], database_name=database.name, db_handle=database)
        async with use_bot_tenant(scope):
            for payment in await database.order_payments.find({"tenant_id": tenant["_id"], "status": "pending"}).limit(100).to_list(100):
                try:
                    expiry = payment.get("expires_at")
                    if not expiry or utc(expiry) > now():
                        continue
                    adapter = await payment_adapter(database, platform, payment)
                    result = await adapter.get_payment(payment)
                    if result.get("status") == "paid" and tenant.get("status") != "active":
                        await database.order_payments.update_one({"_id": payment["_id"]}, {"$set": {"reconciliation": "paid_requires_tenant_reactivation", "external_paid": True}})
                        continue
                    if result.get("status") in {"paid", "expired", "failed", "cancelled"}:
                        await apply_event(database, platform, payment, {"status": result["status"], "event_id": f"verified-status:{payment['_id']}:{result['status']}"})
                    else:
                        await database.order_payments.update_one({"_id": payment["_id"]}, {"$set": {"reconciliation": "expired_requires_provider_review"}})
                except Exception as error:
                    logger.warning("Payment expiry read retry tenant=%s exception=%s", tenant["slug"], type(error).__name__)

async def run(stop):
    while not stop.is_set():
        try:
            await sweep()
        except Exception as error:
            logger.warning("Payment maintenance retry exception=%s", type(error).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
