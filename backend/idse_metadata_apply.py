"""Recoverable metadata-only apply. No inventory writes, no automatic publication."""
from copy import deepcopy
from uuid import uuid5, NAMESPACE_URL
from idse_import_plan import record_version


class StalePreview(ValueError):
    pass


def product_patch(proposal):
    kind=proposal['kind']
    patch={k:deepcopy(proposal[k]) for k in ('name','catalog_name','description','price_idr','content') if k in proposal}
    # 'content' in legacy product models is a fulfillment payload. Store richer
    # marketing metadata separately instead, never overwrite delivery content.
    content=patch.pop('content',None)
    if content is not None:patch['catalog_details']=content
    patch['source_kind']=kind
    return patch


async def apply_metadata(database, tenant_id, job_id, proposals, diff, *, cipher=None):
    """Caller must validate approval/plan and hold durable per-job claim.

    Receipts precede writes. CAS guards whole previewed documents; retries can
    recognize writes by import marker. Existing active products aren't silently
    repriced: they require an explicit approved preview from the caller.
    """
    results=[]
    indexed={p['sku']:p for p in proposals}
    for row in diff:
        sku=row['sku'];proposal=indexed[sku]
        if row['action']=='ERROR':raise StalePreview('Resolve preview errors first')
        if row['action']=='SKIP':
            results.append({'sku':sku,'action':'SKIP'});continue
        pid=row.get('product_id') or str(uuid5(NAMESPACE_URL,tenant_id+':idse:'+sku))
        rid=str(uuid5(NAMESPACE_URL,tenant_id+':'+job_id+':'+sku))
        receipt=await database.excel_import_receipts.find_one({'_id':rid})
        current=await database.products.find_one({'_id':pid})
        if current and current.get('last_import_receipt')==rid:
            results.append({'sku':sku,'action':'ALREADY_APPLIED'});continue
        if row['action']=='CREATE':
            if current is not None:raise StalePreview('Product appeared after preview')
            if await database.products.count_documents({'$or':[{'sku':sku},{'import_sku':sku}]}):
                raise StalePreview('SKU appeared after preview')
        elif current is None or record_version(current)!=row['expected_version']:
            raise StalePreview('Product changed after preview')
        patch=product_patch(proposal)
        if current and current.get('source_kind') not in (None,proposal['kind']):
            raise StalePreview('Product type change requires reviewed migration')
        if receipt is None:
            before_encrypted = None
            if current is not None:
                if cipher is None:
                    raise ValueError('Encryption required for recoverable metadata updates')
                from bson import json_util
                before_encrypted = cipher.encrypt(json_util.dumps(current).encode()).decode()
            await database.excel_import_receipts.insert_one({'_id':rid,'tenant_id':tenant_id,
                'job_id':job_id,'sku':sku,'product_id':pid,'status':'PREPARED',
                'before_version':record_version(current),'before_encrypted':before_encrypted,'changed_fields':list(patch)})
        patch['last_import_receipt']=rid
        if current is None:
            kind=proposal['kind']
            doc={**patch,'_id':pid,'sku':sku,'import_sku':sku,'tenant_id':tenant_id,
                 'active':False,'publication_status':'review_required','price_usd':0,
                 'product_kind':'digital' if kind=='Product' else 'service',
                 'delivery_type':'inventory' if kind=='Product' else 'service',
                 'inventory_enabled':kind=='Product','inventory_schema':[],
                 'stock':None,'stock_mode':'auto' if kind=='Product' else 'unlimited'}
            await database.products.insert_one(doc)
        else:
            # Null fields in equality queries also match absent; $exists clauses
            # preserve exact CAS for keys explicitly present with null values.
            clauses=[{'_id':pid}]
            for key,value in current.items():
                if key=='_id':continue
                clauses.append({key:value})
                if value is None:clauses.append({key:{'$exists':True}})
            result=await database.products.update_one({'$and':clauses},{'$set':patch})
            if not result.matched_count:raise StalePreview('Concurrent product update')
        await database.excel_import_receipts.update_one({'_id':rid},{'$set':{'status':'APPLIED','after_version':record_version(await database.products.find_one({'_id':pid}))}})
        results.append({'sku':sku,'action':row['action']})
    return results
