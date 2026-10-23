"""Tenant-scoped no-write comparison with stable SKU identity and stale guard."""
import hashlib
import json


def record_version(record):
    return hashlib.sha256(json.dumps(record,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()


async def compare_products(database, tenant_id, proposals):
    """Never infer existing identity from name. Return safe fields, not records."""
    result=[]
    for proposed in proposals:
        sku=proposed['sku']
        # Query both possible identity fields to detect ambiguous legacy mapping.
        matches=await database.products.find({'$or':[{'sku':sku},{'import_sku':sku}]}).to_list(3)
        if len(matches)>1:
            result.append({'sku':sku,'action':'ERROR','code':'AMBIGUOUS_EXISTING_SKU'});continue
        existing=matches[0] if matches else None
        if existing and existing.get('tenant_id') not in (None,tenant_id):
            result.append({'sku':sku,'action':'ERROR','code':'TENANT_MISMATCH'});continue
        fields={k:v for k,v in proposed.items() if k in ('name','catalog_name','price_idr','description','warranty','source_kind')}
        changed=[k for k,v in fields.items() if not existing or existing.get(k)!=v]
        count=await database.inventory_items.count_documents({'product_id':existing['_id']}) if existing else 0
        result.append({'sku':sku,'product_id':str(existing['_id']) if existing else None,
            'action':'CREATE' if existing is None else 'UPDATE' if changed else 'SKIP',
            'changed_fields':changed,'stock_existing':count,
            'expected_version':record_version(existing) if existing else None})
    return result
