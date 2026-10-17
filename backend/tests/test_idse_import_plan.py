import asyncio
from mongomock_motor import AsyncMongoMockClient
from idse_import_plan import compare_products, record_version


def test_sku_only_diff_and_tenant_guard():
    async def run():
        db=AsyncMongoMockClient()['plan']
        await db.products.insert_many([
            {'_id':'a','sku':'A','tenant_id':'t','name':'Old','price_idr':10},
            {'_id':'b','sku':'B','tenant_id':'other','name':'Hidden'},
            {'_id':'same-name','name':'New','price_idr':20}])
        rows=await compare_products(db,'t',[{'sku':'A','name':'Old','price_idr':20},
            {'sku':'B','name':'X'},{'sku':'C','name':'New','price_idr':20}])
        assert rows[0]['action']=='UPDATE' and rows[0]['changed_fields']==['price_idr']
        assert rows[1]['action']=='ERROR'
        assert rows[2]['action']=='CREATE'  # never merge by name
        assert (await db.products.find_one({'_id':'a'}))['price_idr']==10
        assert 'Hidden' not in str(rows)
    asyncio.run(run())


def test_version_detects_metadata_change():
    assert record_version({'price':1}) != record_version({'price':2})
