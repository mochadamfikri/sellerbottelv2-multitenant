"""Additive, tenant-injected product backfill; historical orders are read-only."""
from .fulfillment_types import CommerceError, resolve_fulfillment_type


async def backfill_products(database, *, tenant_id, tenant_slug=None, apply=False):
    if not tenant_id:
        raise CommerceError("Tenant migration context required")
    result = {"scanned": 0, "candidates": 0, "changed": 0, "ambiguous": 0, "dry_run": not apply}
    async for product in database.products.find({}):
        if product.get("tenant_id") not in (None, tenant_id, tenant_slug):
            raise CommerceError("Tenant migration context mismatch")
        result["scanned"] += 1
        try:
            kind = resolve_fulfillment_type(product)
        except CommerceError:
            result["ambiguous"] += 1
            continue
        if "fulfillment_type" in product:
            continue
        result["candidates"] += 1
        if apply:
            changed = await database.products.update_one({"_id": product["_id"], "fulfillment_type": {"$exists": False},
                "product_kind": product.get("product_kind"), "delivery_type": product.get("delivery_type")},
                {"$set": {"fulfillment_type": kind.value}})
            result["changed"] += changed.modified_count
    return result
