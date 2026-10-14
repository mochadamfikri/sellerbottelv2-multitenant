"""Real-Mongo digital/service/physical mixed final acceptance, no notifications."""
import asyncio,time
from unittest.mock import patch,AsyncMock
async def commerce(scope,check):
    from bot_tenant_scope import use_bot_tenant
    from commerce.physical.models import create_variant,VariantBody
    from commerce.physical.stock import PhysicalStock
    from commerce.physical.workflow import transition,refresh_order
    from commerce.fulfillment.router import complete_service_records,current_repository
    from storefront_routes import _finalize_store_balance_order
    from order_fulfillment import fulfillment
    from checkout import execute_checkout
    from shipping.service import save_config
    d=scope.db_handle
    address={'recipient_name':'Synthetic buyer','phone':'088888888888','address_line_1':'Jalan Uji 12','city':'Bandung','province':'Jawa Barat','postal_code':'40111'}
    async with use_bot_tenant(scope):
        await save_config(d,scope.tenant_id,{'mode':'manual_shipping','manual_shipping_fee':0})
        await d.products.insert_many([{'_id':'final-digital','name':'Final digital','active':True,'price_idr':1000,'delivery_type':'link','content':'Synthetic delivery only'}, {'_id':'final-service','name':'Final service','active':True,'price_idr':2000,'delivery_type':'service','product_kind':'service'}, {'_id':'final-physical','name':'Final physical','active':True,'price_idr':3000,'fulfillment_type':'physical'}])
        variant=await create_variant(d,'final-physical',VariantBody(sku='FINAL-MIXED',weight=200));stock=PhysicalStock(d)
        await stock.move(variant['_id'],'RECEIVE',1,reference_id='final-opening')
        start=time.perf_counter();attempts=await asyncio.gather(*(stock.move(variant['_id'],'RESERVATION',1,reference_id=f'final-race-{i}') for i in range(20)),return_exceptions=True)
        check('final real stock race 20 contenders one winner',sum(isinstance(a,dict) for a in attempts)==1)
        race_ms=round((time.perf_counter()-start)*1000,2)
        winner=next(a for a in attempts if isinstance(a,dict));await stock.move(variant['_id'],'RELEASE',1,reference_id=winner['reference_id'])
        await d.store_customers.insert_one({'_id':'final-mixed-buyer','email':'mixed@phase4.invalid','balance_idr':10000,'currency':'IDR'})
        user=await d.store_customers.find_one({'_id':'final-mixed-buyer'})
        with patch('services.notify_transaction_channel_safely',AsyncMock()),patch('services.notify_admin',AsyncMock()),patch('stock_monitor.schedule_stock_scan',lambda *a:None):
            start=time.perf_counter();r=await execute_checkout({**user,'customer_id':user['_id']},[{'pid':'final-digital','qty':1},{'pid':'final-service','qty':1},{'pid':'final-physical','variant_id':variant['_id'],'qty':1}],purchase_source='WEB',shipping_address=address)
            checkout_ms=round((time.perf_counter()-start)*1000,2)
            check('final real mixed one order one wallet debit',r['ok'] and r['order']['total']==6000 and (await d.store_customers.find_one({'_id':user['_id']}))['balance_idr']==4000)
            oid=r['order']['_id'];await _finalize_store_balance_order(oid)
            saved=await d.purchases.find_one({'_id':oid});records=await d.fulfillments.find({'order_id':oid}).to_list(None)
            check('final real digital service physical separate fulfillment',len(records)==3 and {x['status'] for x in records}=={'pending','queued','delivered'})
            detail=await fulfillment(saved);check('final real digital delivery history',len(detail['products'])==1)
            await complete_service_records(saved);await refresh_order(current_repository(),oid)
            check('final service completion waits for physical',(await d.purchases.find_one({'_id':oid}))['status']!='delivered')
            physical=next(x for x in records if x['type']=='physical')
            for state in ['packing','ready_to_ship','shipped','delivered']:
                await transition(oid,physical['_id'],state,**({'carrier_name':'Manual','tracking_number':'PHASE4-FINAL'} if state=='shipped' else {}))
            check('final real mixed aggregate delivered',(await d.purchases.find_one({'_id':oid}))['status']=='delivered')
        return {'checkout_ms':checkout_ms,'stock_race_20_ms':race_ms,'coverage':'bounded synthetic development sample'}
