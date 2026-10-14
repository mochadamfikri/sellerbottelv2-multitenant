import asyncio
import hashlib
import hmac
import json
import time
import pytest
from mongomock_motor import AsyncMongoMockClient
from commerce.fulfillment_types import CommerceError
from payments.launch import snapshot, breakdown, require_provider, require_shipping
from payments.ledger import Ledger
from payments.providers.kasera import KaseraSandbox
from payments.webhook import reference_hint

@pytest.mark.parametrize('amount,percentage', [(15000,105),(15001,106),(100000,700),(100001,701)])
def test_fee_rounding_and_concurrent_credit(monkeypatch,amount,percentage):
    monkeypatch.setenv('COMMERCE_LAUNCH_PROFILE','v1_kasera')
    payment={'_id':'p','order_id':'o','payment_mode':'platform_settlement','environment':'sandbox','amount':amount,'gateway_fee':percentage+250,'platform_fee':250,**snapshot('kasera','qris',{'fee':{'percent_bps':70,'flat':250}})}
    async def run():
        db=AsyncMongoMockClient().tenant
        ledger=Ledger(db,'tenant')
        await asyncio.gather(*(ledger.credit(payment) for _ in range(12)))
        account=await ledger.get()
        assert len(account['events'])==5
        assert ledger.values(account)['pending']==amount-percentage-500
        assert [e['type'] for e in account['events']]==['PAYMENT_GROSS','KASERA_PERCENT_FEE','KASERA_FIXED_FEE','SELLERBOTTEL_PLATFORM_FEE','NET_SETTLEMENT']
        with pytest.raises(CommerceError): await ledger.credit({**payment,'gateway_fee':0})
    asyncio.run(run())

@pytest.mark.parametrize('provider,method,detail',[('midtrans','qris',{}),('kasera','va_bca',{}),('kasera','qris',{'fee':{'percent_bps':71,'flat':250}}),('kasera','qris',{})])
def test_unapproved_fee_policy_fails_closed(monkeypatch,provider,method,detail):
    monkeypatch.setenv('COMMERCE_LAUNCH_PROFILE','v1_kasera')
    with pytest.raises(CommerceError): snapshot(provider,method,detail)

def test_v1_blocks_deferred_provider_and_shipping(monkeypatch):
    monkeypatch.setenv('COMMERCE_LAUNCH_PROFILE','v1_kasera')
    require_provider('kasera');require_shipping('manual_shipping')
    with pytest.raises(CommerceError):require_provider('midtrans')
    with pytest.raises(CommerceError):require_shipping('integrated_shipping')

@pytest.mark.parametrize('value',[{}, {'$ne':None},[],None,4,''])
def test_untrusted_reference_is_not_query_operator(value):
    with pytest.raises(CommerceError):reference_hint(json.dumps({'data':{'external_id':value}}).encode())

@pytest.mark.parametrize('event_type,status,accepted',[('payment.paid','succeeded',True),('payment.expired','expired',True),('payment.failed','failed',True),('payment.paid','pending',False),('payment.failed','succeeded',False),('unknown','succeeded',False)])
def test_exact_signed_event_contract(monkeypatch,event_type,status,accepted):
    monkeypatch.setenv('PHASE3_SANDBOX_ENABLED','true')
    adapter=KaseraSandbox('kasera','sandbox',{'api_key':'kp_test_fixture','webhook_secret':'fixture'})
    body=json.dumps({'type':event_type,'id':'e','livemode':False,'data':{'external_id':'ref','payment_request_id':'pid','amount':15001,'currency':'IDR','status':status}}).encode()
    stamp=str(int(time.time()));sig='t='+stamp+', v1='+hmac.new(b'fixture',stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
    if accepted: assert adapter.verify_webhook(body,sig)['status'] in {'paid','expired','failed'}
    else:
        with pytest.raises(CommerceError):adapter.verify_webhook(body,sig)
    with pytest.raises(CommerceError):adapter.verify_webhook(body,'')
    with pytest.raises(CommerceError):adapter.verify_webhook(body,sig+'bad')

def test_self_gateway_has_no_sellerbottel_fee(monkeypatch):
    monkeypatch.setenv('COMMERCE_LAUNCH_PROFILE','v1_kasera')
    policy=snapshot('kasera','qris',{'fee':{'percent_bps':70,'flat':250}},payment_mode='self_gateway')
    assert policy['fee_policy']['platform']==0
    async def run():
        ledger=Ledger(AsyncMongoMockClient().tenant,'tenant')
        assert await ledger.credit({'payment_mode':'self_gateway',**policy})==[]
        assert not any(ledger.values(await ledger.get()).values())
    asyncio.run(run())

@pytest.mark.parametrize('base,total,fee',[(100000,100957,957),(15001,15359,358),(1000,1259,259),(999999,1007301,7302)])
@pytest.mark.parametrize('mode,platform_fee',[('platform_settlement',250),('self_gateway',0)])
def test_buyer_fee_preserves_provider_net(monkeypatch,base,total,fee,mode,platform_fee):
    from payments.launch import buyer_quote
    monkeypatch.setenv('COMMERCE_LAUNCH_PROFILE','v1_kasera')
    policy=snapshot('kasera','qris',{'fee':{'percent_bps':70,'flat':250}},payment_mode=mode)
    quote=buyer_quote(base,policy)
    assert quote['total']==total
    assert quote['gateway_fee']==fee
    assert total-fee==base
    assert quote['net_settlement']==base-platform_fee
    # One rupiah less cannot cover the requested merchant net.
    prior=total-1
    assert prior-((prior*70+9999)//10000)-250<base


def test_provider_cannot_silently_change_buyer_fee():
    adapter=KaseraSandbox('kasera','sandbox',{})
    payment={'fee_quote':{'gateway_fee':957,'base_amount':100000}}
    adapter.verify_fee_quote(payment,{'fee':957,'net':100000})
    for result in [{'fee':956,'net':100001},{'fee':957,'net':99999},{}]:
        with pytest.raises(CommerceError):adapter.verify_fee_quote(payment,result)

from tests.test_phase3_payments import phase3, setup, paid
from tests.test_public_tenant_management import management

@pytest.mark.parametrize('mode',['platform_settlement','self_gateway'])
def test_v1_quote_consent_checkout_and_exact_settlement(phase3,monkeypatch,mode):
    import httpx
    from db import platform_db
    from payments.providers.base import MockProvider
    from tests.test_physical_commerce import ADDRESS
    original=MockProvider.create_payment
    async def create_provider(self,payment):
        result=await original(self,payment)
        return {**result,'gateway_fee':payment['fee_quote']['gateway_fee']}
    monkeypatch.setattr(MockProvider,'create_payment',create_provider)
    async def run():
        tenant,headers,database,variant=await setup(phase3,mode=mode)
        platform=platform_db()
        target=platform.platform_payment_settings if mode=='platform_settlement' else database.payment_settings
        selector={'_id':'kasera' if mode=='platform_settlement' else 'main'}
        await target.update_one(selector,{'$set':{'capabilities.method_details':[{'code':'qris','min_amount':1000,'max_amount':10000000,'fee':{'percent_bps':70,'flat':250}}]}})
        monkeypatch.setenv('COMMERCE_LAUNCH_PROFILE','v1_kasera')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]),base_url='https://mock') as http:
            prefix=f"/api/store/t/{tenant['slug']}"
            await http.post(prefix+'/login',json={'email':'phase3@example.com','password':'safe-test-password'})
            response=await http.get(prefix+'/gateway/methods',params={'amount':25000})
            assert response.status_code==200
            data=response.json();assert data['launch_profile']=='v1_kasera'
            assert [m['code'] for m in data['methods']]==['gateway:qris']
            quote=data['methods'][0]['fee_quote']
            assert quote['base_amount']==25000 and quote['net_settlement']==(24750 if mode=='platform_settlement' else 25000)
            body={'items':[{'pid':'physical','variant_id':variant['_id'],'qty':2}],'shipping_address':ADDRESS,'payment_method':'gateway:qris','idempotency_key':'buyer-fee-consent-test'}
            for expected in [None,quote['total']-1]:
                assert (await http.post(prefix+'/checkout',json={**body,'expected_gateway_total':expected})).status_code==422
                assert await database.order_payments.count_documents({})==0
                stock=await database.physical_variants.find_one({'_id':variant['_id']});assert stock['on_hand']==10 and stock['reserved']==0
            # Tenant legacy owner-merchant checkout must not bypass V1.
            assert (await http.post(prefix+'/checkout',json={**body,'payment_method':'qris'})).status_code==422
            response=await http.post(prefix+'/checkout',json={**body,'expected_gateway_total':quote['total']})
            assert response.status_code==200,response.text
            order=response.json();assert order['total']==quote['total'] and order['payment_fee']==quote['gateway_fee']
            if mode=='platform_settlement':
                await platform.platform_payment_settings.update_one({'_id':'kasera'},{'$set':{'platform_fee':750}})
            responses=await asyncio.gather(*(paid(http,order) for _ in range(8)))
            assert all(r.status_code==200 for r in responses)
            payment=await database.order_payments.find_one({'order_id':order['_id']})
            assert payment['platform_fee']==(250 if mode=='platform_settlement' else 0)
            ledger=Ledger(database,tenant['_id']);account=await ledger.get()
            assert ledger.values(account)['pending']==(24750 if mode=='platform_settlement' else 0)
            assert len(account['events'])==(5 if mode=='platform_settlement' else 0)
            stock=await database.physical_variants.find_one({'_id':variant['_id']});assert stock['on_hand']==8 and stock['reserved']==0
            replay=await http.post(prefix+'/checkout',json={**body,'expected_gateway_total':quote['total']})
            assert replay.json()['_id']==order['_id']
            if mode=='platform_settlement':
                fresh=await http.post(prefix+'/checkout',json={**body,'idempotency_key':'buyer-fee-next-order','expected_gateway_total':quote['total']})
                assert fresh.status_code==200
                fresh_payment=await database.order_payments.find_one({'order_id':fresh.json()['_id']})
                assert fresh_payment['fee_policy']['platform']==750
                assert payment['fee_policy']['platform']==250
    asyncio.run(run())
