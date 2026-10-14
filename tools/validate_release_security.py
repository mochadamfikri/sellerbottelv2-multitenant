"""Synthetic signed adversarial/replay checks, distinct from genuine Kasera evidence."""
import asyncio,copy,hashlib,hmac,json,time
from run_release_kasera import ROOT
from db import client,platform_db
from payments.credentials import load
from commerce.fulfillment_types import CommerceError
import httpx
PATH='/api/payments/webhooks/kasera'
async def run():
    platform=platform_db();evidence=json.loads((ROOT/'test_reports/release-blocker-kasera-20261009/genuine-callback-buyer-fees.json').read_text())
    secret=(ROOT/'backend/.secretkaserapay').read_text().strip().encode()
    entry=evidence['platform_settlement'];db=client[entry['tenant_database']]
    p=await db.order_payments.find_one({'_id':entry['route_id']});receipt=await platform.payment_events.find_one({'route_id':p['_id'],'state':'applied'})
    event={'id':receipt['event_id'],'type':'payment.paid','livemode':False,'data':{'external_id':p['provider_reference'],'payment_request_id':p['provider_payment_id'],'amount':p['amount'],'currency':'IDR','status':'succeeded'}}
    async def state():
        return {'payments':await db.order_payments.find({}).to_list(20),'orders':await db.purchases.find({}).to_list(20),'variants':await db.physical_variants.find({}).to_list(20),'fulfillments':await db.fulfillments.find({}).to_list(20),'settlement':await db.settlement_accounts.find({}).to_list(20),'routes':await platform.payment_routes.find({}).to_list(20),'receipts':await platform.payment_events.find({}).to_list(20)}
    before=await state();results={}
    other=evidence['self_gateway']
    foreign=await client[other['tenant_database']].order_payments.find_one({'_id':other['route_id']})
    async with httpx.AsyncClient(base_url='https://pay.idsepos.my.id',timeout=30) as http:
        async def send(value,offset=0,bad=False,missing=False):
            raw=json.dumps(value).encode();stamp=str(int(time.time())+offset)
            sig='t='+stamp+',v1='+hmac.new(secret,stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
            headers={} if missing else {'Kasera-Signature-V1':'invalid' if bad else sig}
            return await http.post(PATH,content=raw,headers=headers)
        for name,kwargs in [('missing_signature',{'missing':True}),('invalid_signature',{'bad':True}),('stale_timestamp',{'offset':-301}),('future_timestamp',{'offset':301})]:
            r=await send(event,**kwargs);assert r.status_code==422;results[name]=r.status_code
        for name,key,value in [('wrong_amount','amount',p['amount']+1),('wrong_currency','currency','USD'),('unknown_reference','external_id','unknown'),('query_operator','external_id',{'$ne':None}),('foreign_payment_id','payment_request_id',foreign['provider_payment_id']),('wrong_existing_reference','external_id',foreign['provider_reference'])]:
            changed=copy.deepcopy(event);changed['data'][key]=value;r=await send(changed);assert r.status_code==422;results[name]=r.status_code
        for name,url in [('admin_hidden','/api/admin'),('docs_hidden','/docs'),('root_hidden','/')]:
            r=await http.get(url);assert r.status_code==404;results[name]=404
        route=await platform.payment_routes.find_one({'_id':p['_id']})
        try:
            await platform.payment_routes.update_one({'_id':p['_id']},{'$set':{'tenant_database':evidence['self_gateway']['tenant_database']}})
            r=await send(event);assert r.status_code==422;results['wrong_tenant_route']=422
        finally: await platform.payment_routes.replace_one({'_id':p['_id']},route)
        version=p['credential_id']
        try:
            await platform.gateway_credentials.update_one({'_id':version},{'$set':{'revoked':True}})
            try: await load(platform,'platform-idse',version)
            except CommerceError:results['revoked_new_use']='rejected'
            else: raise AssertionError('revoked credential allowed')
            r=await send(event);assert r.status_code==200 and r.json()['duplicate'];results['historical_revoked_callback']='accepted_duplicate'
        finally: await platform.gateway_credentials.update_one({'_id':version},{'$set':{'revoked':False}})
        responses=await asyncio.gather(*(send(event) for _ in range(12)))
        assert all(r.status_code==200 and r.json()['duplicate'] for r in responses)
        results['concurrent_duplicates']=12
        assert await state()==before;results['financial_and_fulfillment_state_unchanged']=True
        results['route_unique_index_survived']=bool((await platform.payment_routes.index_information()).get('payment_route_reference',{}).get('unique'))
    destination=ROOT/'test_reports/release-blocker-kasera-20261009/security-restart.json'
    destination.write_text(json.dumps({'coverage':'Synthetic signed adversarial requests and duplicate replay after backend restart; genuine provider receipt tested separately','checks':results},indent=2)+'\n');print(json.dumps(results));client.close()
if __name__=='__main__':asyncio.run(run())
