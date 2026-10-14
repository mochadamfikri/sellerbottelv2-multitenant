"""Durable per-line routing; financial and reservation logic stays in V2."""
import logging
from ..fulfillment_types import CommerceError, FulfillmentUnavailable, resolve_fulfillment_type
from ..order_items import normalize_order_items
from .base import FulfillmentContext
from .registry import registry
from .repository import FulfillmentRepository, ensure_fulfillment_indexes

logger = logging.getLogger(__name__)
PAID_STATES = {"paid", "service_waiting", "delivered", "completed", "delivery_failed"}


def current_repository():
    from db import _resolve_db
    from bot_tenant_scope import get_current_scope
    database = _resolve_db()
    scope = get_current_scope()
    return FulfillmentRepository(database, scope.tenant_id if scope else "legacy:" + database.name, tenant_slug=scope.slug if scope else None)


async def require_active_context(repo):
    from bot_tenant_scope import get_current_scope
    scope = get_current_scope()
    if scope is None:
        return
    if scope.db_handle is None or scope.database_name != repo.database.name or str(scope.tenant_id) != repo.tenant_id:
        raise CommerceError("Tenant fulfillment context mismatch")
    from dependencies import get_tenant_registry
    registry_doc = await get_tenant_registry().get_tenant(scope.slug)
    if scope.slug == "central":
        # Central uses its explicit owner database rather than a tenant named central.
        from db import client
        from tenant_db import resolve_platform_database_name
        import os
        registry_doc = await client[resolve_platform_database_name(os.environ)].tenants.find_one({"database_name": repo.database.name})
    if registry_doc is None or registry_doc.get("status") != "active" or registry_doc.get("database_name") != repo.database.name:
        raise CommerceError("Tenant fulfillment unavailable")
    if scope.slug != "central" and str(registry_doc["_id"]) != repo.tenant_id:
        raise CommerceError("Tenant fulfillment context mismatch")


async def ensure_order_fulfillments(order):
    repo = current_repository()
    await require_active_context(repo)
    saved = await repo.database.purchases.find_one({"_id": order["_id"]})
    if saved is None or saved.get("status") not in PAID_STATES:
        raise CommerceError("Paid order required for fulfillment")
    if saved.get("tenant_id") not in repo.allowed_order_tenant_ids:
        raise CommerceError("Tenant fulfillment context mismatch")
    items = saved.get("items") or []
    if not items:
        return []  # Historical service fixtures/orders may have no item details.
    if not all(item.get("line_id") and item.get("fulfillment_type") for item in items):
        products = {str(item.get("product_id") or item.get("pid")): await repo.database.products.find_one({"_id": item.get("product_id") or item.get("pid")}) for item in items}
        # Legacy order lines already captured delivery_type. Preserve that fact
        # instead of substituting a classification from an edited live product.
        legacy_lines = [dict(line) for line in items]
        for line in legacy_lines:
            if line.get("delivery_type") and not line.get("fulfillment_type"):
                line["fulfillment_type"] = resolve_fulfillment_type(line).value
        items = normalize_order_items(legacy_lines, order_id=saved["_id"], products=products)
        changed = await repo.database.purchases.update_one({"_id": saved["_id"], "items": saved["items"]}, {"$set": {"items": items, "commerce_schema_version": 1, "commerce_snapshot_origin": "legacy_reconstructed"}})
        if not changed.modified_count:
            refreshed = await repo.database.purchases.find_one({"_id": saved["_id"]})
            if not refreshed or not all(line.get("line_id") and line.get("fulfillment_type") for line in refreshed.get("items", [])):
                raise FulfillmentUnavailable("Order snapshot changed; retry")
            items = refreshed["items"]
    order["items"] = items
    await ensure_fulfillment_indexes(repo.database)
    records = [await repo.create(saved, item) for item in items]
    logger.info("fulfillment records ensured tenant=%s order=%s count=%s", repo.tenant_id, order["_id"], len(records))
    return records


async def route_item(order, item, execute=None):
    repo = current_repository()
    await require_active_context(repo)
    records = await ensure_order_fulfillments(order)
    record = next((r for r in records if r["line_id"] == item["line_id"]), None)
    if record is None:
        raise CommerceError("Order fulfillment line not found")
    # Always use the persisted snapshot, not caller-supplied classification.
    saved_item = next(line for line in order["items"] if line["line_id"] == record["line_id"])
    for key in ("product_id", "fulfillment_type", "qty", "fulfillment_snapshot"):
        if item.get(key) != saved_item.get(key):
            raise CommerceError("Order fulfillment snapshot mismatch")
    handler = registry.get(record["type"])
    claim = await repo.claim(record)
    if claim is None:
        current = await repo.collection.find_one(repo.query(_id=record["_id"]))
        if current["execution_status"] == "done":
            return current["status"]
        raise FulfillmentUnavailable("Fulfillment already claimed or requires reconciliation")
    await require_active_context(repo)
    logger.info("fulfillment routing tenant=%s order=%s fulfillment=%s type=%s", repo.tenant_id, order["_id"], claim["_id"], claim["type"])
    try:
        state = await handler.process(FulfillmentContext(repo.tenant_id, repo.database, order, saved_item, execute))
    except Exception as error:
        code = type(error).__name__
        state = "delivery_failed" if record["type"] == "digital_auto" else "failed"
        await repo.finish(claim, state, code)
        logger.warning("fulfillment failed tenant=%s order=%s fulfillment=%s exception=%s", repo.tenant_id, order["_id"], claim["_id"], code)
        raise FulfillmentUnavailable("Fulfillment delivery failed") from None
    await repo.finish(claim, state, "DELIVERY_FAILED" if state in {"failed", "delivery_failed"} else None)
    logger.info("fulfillment finished tenant=%s order=%s fulfillment=%s status=%s", repo.tenant_id, order["_id"], claim["_id"], state)
    return state


async def complete_service_records(order):
    repo = current_repository()
    await require_active_context(repo)
    for record in await repo.list_order(order["_id"]):
        if record["type"] == "service":
            await repo.transition(record["_id"], "completed")
