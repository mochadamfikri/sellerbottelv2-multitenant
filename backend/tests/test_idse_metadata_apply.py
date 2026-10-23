import asyncio
import pytest
from mongomock_motor import AsyncMongoMockClient
from idse_import_plan import compare_products
from idse_metadata_apply import apply_metadata, StalePreview


def test_create_retry_update_and_stale_preview():
    async def run():
        db=AsyncMongoMockClient()['apply']
        proposal={'sku':'A','name':'Name','kind':'Product','source_kind':'Product','price_idr':100,
                  'description':'Complete','content':{'features':'Actual'}}
        plan=await compare_products(db,'t',[proposal])
        await apply_metadata(db,'t','job1',[proposal],plan)
        await apply_metadata(db,'t','job1',[proposal],plan)
        assert await db.products.count_documents({})==1
        p=await db.products.find_one({'sku':'A'})
        assert p['active'] is False and 'content' not in p
        assert p['catalog_details']['features']=='Actual'
        proposal['price_idr']=200
        plan=await compare_products(db,'t',[proposal])
        await db.products.update_one({'_id':p['_id']},{'$set':{'price_idr':300}})
        with pytest.raises(StalePreview):await apply_metadata(db,'t','job2',[proposal],plan)
        assert (await db.products.find_one({'_id':p['_id']}))['price_idr']==300
    asyncio.run(run())


def test_partial_batch_can_resume_without_recreating_products():
    async def run():
        db=AsyncMongoMockClient()['partial']
        proposals=[{'sku':sku,'name':sku,'kind':'Product','price_idr':10} for sku in ['A','B']]
        plan=await compare_products(db,'t',proposals)
        await apply_metadata(db,'t','job',proposals[:1],plan[:1])
        # Simulate process interruption after first durable row commit.
        result=await apply_metadata(db,'t','job',proposals,plan)
        assert result[0]['action']=='ALREADY_APPLIED'
        assert await db.products.count_documents({})==2
        assert await db.excel_import_receipts.count_documents({'status':'APPLIED'})==2
    asyncio.run(run())
