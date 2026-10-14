"""Phase 4 security and immutable journal regression."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError
from branding import Branding, context, receipt_html
from commerce.journal import Journal
from commerce.physical.stock import PhysicalStock
from commerce.physical.models import VariantBody, create_variant
from payments.ledger import Ledger
from tests.test_public_tenant_management import management
from tests.test_phase3_payments import phase3, setup

@pytest.mark.parametrize('field,value', [('brand_name','<script>x</script>'),('email_sender_name','Name\r\nBcc: x@y.z'),('logo','javascript:alert(1)'),('favicon','data:image/svg+xml,x'),('invoice_logo','https://user:pass@example.com/x'),('primary_color','red;display:none'),('font','url(https://evil)'),('domain','shop.example.com'),('social_links',{'x':'javascript:1'}),('telegram_bot','bad/name'),('whatsapp','javascript:1'),('receipt_footer','<iframe>')])
def test_branding_rejects_injection(field,value):
    with pytest.raises(ValidationError): Branding(**{field:value})

@pytest.mark.parametrize('mode',['platform','co_branded','tenant_only'])
def test_brand_modes_and_revocation(mode):
    async def run():
        db=AsyncMongoMockClient()['brand']
        tenant={'name':'Tenant A','metadata':{'capabilities':{'can_white_label':True,'custom_email_branding_enabled':True}}}
        await db.branding.insert_one({'_id':'main',**Branding(mode=mode,brand_name='Acme',receipt_footer='Thank you',email_sender_name='Acme Mail').model_dump()})
        b,caps=await context(db,tenant)
        assert b['brand_name']==('SellerBottel' if mode=='platform' else 'Acme')
        assert bool(b['attribution'])==(mode=='co_branded')
        assert '<script>' not in receipt_html(b,{'_id':'x','items':[{'name':'<script>','qty':1}],'status':'paid'})
        tenant['metadata']['capabilities']={}
        b,_=await context(db,tenant)
        assert b['mode']!='tenant_only' and b['sender_name']=='SellerBottel'
    asyncio.run(run())

def test_branding_owner_boundary_and_tenant_isolation(phase3):
    async def run():
        import branding
        phase3[1].include_router(branding.router)
        ta,ha,a,_=await setup(phase3,'brand-a'); tb,hb,b,_=await setup(phase3,'brand-b')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]),base_url='http://test') as h:
            root='/api/public/tenant/full/branding'
            assert (await h.put(root,json={'brand_name':'bad'})).status_code==401
            assert (await h.put(root,headers=ha,json={'mode':'tenant_only'})).status_code==403
            assert (await h.put(root,headers=ha,json={'brand_name':'Tenant A Brand','can_white_label':True})).status_code==422
            assert (await h.put(root,headers=ha,json={'brand_name':'Tenant A Brand'})).status_code==200
            assert (await h.get(root,headers=hb)).json()['branding']['brand_name']!='Tenant A Brand'
            assert (await h.get('/api/store/t/brand-a/config')).json()['branding']['brand_name']=='Tenant A Brand'
            assert (await h.get('/api/store/t/brand-b/config')).json()['branding']['brand_name']!='Tenant A Brand'
            assert await b.branding.count_documents({})==0
    asyncio.run(run())

@pytest.mark.parametrize('count',[3100,10500])
def test_stock_journal_crosses_old_guard_and_reconstructs(count):
    async def run():
        db=AsyncMongoMockClient()['archive']; stock=PhysicalStock(db)
        await db.products.insert_one({'_id':'product','fulfillment_type':'physical'})
        v=await create_variant(db,'product',VariantBody(sku='A'))
        events=[{'_id':f'e{i}','variant_id':v['_id'],'sku':'A','type':'RECEIVE','quantity':1,'delta_on_hand':1,'delta_reserved':0,'reference_id':f'old{i}','created_at':datetime.now(timezone.utc)} for i in range(count)]
        await db.physical_variants.update_one({'_id':v['_id']},{'$set':{'stock_events':events,'on_hand':count,'stock_version':count}})
        doc=await stock.get(v['_id'])
        while len(doc['stock_events'])>=512: doc=await stock.journal.compact(doc,lambda e:{'on_hand':e['delta_on_hand'],'reserved':e['delta_reserved']})
        await stock.move(v['_id'],'RESERVATION',1,reference_id='order-line')
        for i in range(3):
            extra=[{**events[0],'_id':f'pad{i}-{j}','reference_id':f'pad{i}-{j}'} for j in range(256)]
            await db.physical_variants.update_one({'_id':v['_id']},{'$push':{'stock_events':{'$each':extra}},'$inc':{'on_hand':256,'stock_version':1}})
            await stock.move(v['_id'],'ADJUSTMENT',1,reference_id=f'adj{i}')
        await stock.move(v['_id'],'SALE',1,reference_id='order-line')
        await stock.return_quantity(v['_id'],1,sale_reference='order-line',reference='return',damaged=True)
        doc=await stock.get(v['_id']); n=doc['on_hand']
        await stock.move(v['_id'],'SALE',1,reference_id='order-line')
        assert (await stock.get(v['_id']))['on_hand']==n
        result=await stock.journal.verify(doc,lambda e:{'on_hand':e['delta_on_hand'],'reserved':e['delta_reserved']},lambda events:stock.project({'stock_events':events}))
        assert result['totals']=={'on_hand':n,'reserved':0}
        assert len(doc['stock_events'])<768 and result['events']>count
        assert await db.stock_movements.count_documents({})==result['events']
    asyncio.run(run())

def test_settlement_archive_preserves_refund_payout_and_idempotency():
    async def run():
        db=AsyncMongoMockClient()['money']; ledger=Ledger(db,'tenant')
        payment={'_id':'payment','order_id':'order','amount':10000,'environment':'mock','payment_mode':'platform_settlement','clearing_at':datetime.now(timezone.utc),'available_at':datetime.now(timezone.utc)}
        await ledger.credit(payment); await ledger.advance(payment,'clearing'); await ledger.advance(payment,'available')
        await ledger.request_payout('key',3000,{'_id':'bank','verification_status':'mock_verified'})
        base=(await ledger.get())['events'][0]
        filler=[{**base,'_id':f'f{i}','reference':f'f{i}','type':'AUDIT','deltas':{},'amount':0} for i in range(10500)]
        await db.settlement_accounts.update_one({'_id':'tenant'},{'$push':{'events':{'$each':filler}},'$inc':{'version':1}})
        doc=await ledger.get()
        delta=lambda e:{**e.get('deltas',{}),'nonmock':int(e['type']=='PAYMENT_GROSS' and e.get('environment')!='mock')}
        while len(doc['events'])>=512: doc=await ledger.journal.compact(doc,delta)
        await ledger.credit(payment)
        for state in ['reviewing','processing','paid']: await ledger.payout_transition('key',state)
        await ledger.reverse(payment,{'_id':'refund','amount':8000})
        doc=await ledger.get(); values=ledger.values(doc)
        assert values['paid_out']==3000 and values['liability']==1000 and values['available']==0
        await db.settlement_entries.delete_many({})
        verified=await ledger.journal.verify(doc,delta,lambda events:ledger.project({'events':events}))
        assert verified['totals']['liability']==1000
        assert await db.settlement_entries.count_documents({})==verified['events']
    asyncio.run(run())

def test_archive_failure_before_cas_and_tamper_detection(monkeypatch):
    async def run():
        db=AsyncMongoMockClient()['crash']; j=Journal(db,'owners','events','version','archive')
        doc={'_id':'a','version':0,'events':[{'_id':str(i),'delta':1} for i in range(512)]}
        await db.owners.insert_one(doc)
        original=j.owners.update_one
        monkeypatch.setattr(j.owners,'update_one',AsyncMock(side_effect=RuntimeError('local interruption')))
        with pytest.raises(RuntimeError): await j.compact(doc,lambda e:{'value':e['delta']})
        assert (await db.owners.find_one({'_id':'a'}))['events']==doc['events']
        monkeypatch.setattr(j.owners,'update_one',original)
        doc=await j.compact(doc,lambda e:{'value':e['delta']})
        assert (await j.verify(doc,lambda e:{'value':e['delta']}))['totals']['value']==512
        await db.archive.update_one({'owner_id':'a'},{'$set':{'hash':'tampered'}})
        from commerce.fulfillment_types import CommerceError
        with pytest.raises(CommerceError): await j.verify(doc,lambda e:{'value':e['delta']})
    asyncio.run(run())

@pytest.mark.parametrize('status',['active','suspended','disabled','provisioning','failed'])
def test_phase4_lifecycle_branding_and_financial_visibility(phase3,status):
    async def run():
        import branding
        phase3[1].include_router(branding.router)
        tenant,headers,db,_=await setup(phase3,'lifecycle-final')
        await db.order_payments.insert_one({'_id':'pending-preserved','status':'pending','tenant_id':tenant['_id']})
        await phase3[0].update_status('lifecycle-final',status)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]),base_url='http://test') as h:
            expected=200 if status=='active' else 403
            for path in ['/api/public/tenant/full/branding','/api/public/tenant/full/commerce/transactions','/api/store/t/lifecycle-final/config']:
                assert (await h.get(path,headers=headers)).status_code==expected
            await phase3[0].update_status('lifecycle-final','active')
            assert (await h.get('/api/public/tenant/full/commerce/transactions',headers=headers)).status_code==200
            assert (await db.order_payments.find_one({'_id':'pending-preserved'}))['status']=='pending'
    asyncio.run(run())

@pytest.mark.parametrize('kind',['expired','invalid','customer'])
def test_phase4_owner_token_boundaries(phase3,kind):
    async def run():
        import branding,jwt
        from auth import get_jwt_secret,JWT_ALGORITHM
        phase3[1].include_router(branding.router)
        tenant,headers,db,_=await setup(phase3,'token-final')
        payload=jwt.decode(headers['Authorization'][7:],get_jwt_secret(),algorithms=[JWT_ALGORITHM])
        if kind=='expired': payload['exp']=1
        elif kind=='customer': payload['sub']='same-customer'
        token=jwt.encode(payload,get_jwt_secret() if kind!='invalid' else 'untrusted-test-signature-key-long-enough',algorithm=JWT_ALGORITHM)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]),base_url='http://test') as h:
            assert (await h.get('/api/public/tenant/full/branding',headers={'Authorization':'Bearer '+token})).status_code==401
    asyncio.run(run())

@pytest.mark.parametrize('collection,path',[
 ('products','/products'),('purchases','/orders'),('bot_users','/users'),('broadcasts','/broadcasts'),
 ('order_payments','/commerce/transactions'),('integrated_shipments','/commerce/shipments'),('return_requests','/commerce/returns'),('refund_requests','/commerce/refunds')])
def test_phase4_foreign_records_never_visible(phase3,collection,path):
    async def run():
        a,ha,da,_=await setup(phase3,'matrix-a');b,hb,db,_=await setup(phase3,'matrix-b')
        await db[collection].insert_one({'_id':'foreign-guessable','tenant_id':b['_id'],'name':'FOREIGN_SENTINEL','status':'pending','created_at':datetime.now(timezone.utc),'telegram_id':987,'total':1})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=phase3[1]),base_url='http://test') as h:
            response=await h.get('/api/public/tenant/full'+path,headers={**ha,'X-Tenant-ID':b['_id']})
            assert response.status_code==200,response.text
            assert 'FOREIGN_SENTINEL' not in response.text and 'foreign-guessable' not in response.text
            assert await db[collection].find_one({'_id':'foreign-guessable'})
    asyncio.run(run())

@pytest.mark.parametrize('payload,mime',[(b'<svg><script/></svg>','image/svg+xml'),(b'corrupt','image/png'),(b'x'*(5*1024*1024+1),'image/jpeg')])
def test_phase4_upload_rejects_unsafe_files(payload,mime):
    import io
    from starlette.datastructures import UploadFile,Headers
    from fastapi import HTTPException
    from admin_routes import _store_product_image
    async def run():
        with pytest.raises(HTTPException):
            await _store_product_image('safe-id',UploadFile(filename='../../evil.png',file=io.BytesIO(payload),headers=Headers({'content-type':mime})))
    asyncio.run(run())

@pytest.mark.parametrize('path',['../../etc/passwd','/etc/passwd','..\\..\\secret'])
def test_phase4_storage_traversal_denied(path):
    from storage import _resolve_path
    with pytest.raises(ValueError): _resolve_path(path)

@pytest.mark.parametrize('mode',['platform','co_branded','tenant_only'])
def test_phase4_email_and_bot_branding_modes(phase3,monkeypatch,mode):
    async def run():
        from bot_tenant_scope import BotTenantScope,use_bot_tenant
        from storefront_routes import _send_email_code
        from bot import _resolve_bot_display_name
        tenant,headers,db,_=await setup(phase3,'email-brand')
        await phase3[0].collection.update_one({'_id':tenant['_id']},{'$set':{'metadata.capabilities':{'can_white_label':True,'custom_email_branding_enabled':True}}})
        await db.branding.insert_one({'_id':'main',**Branding(mode=mode,brand_name='Email Brand').model_dump()})
        sent=[]
        class SMTP:
            def __init__(self,*a,**kw): pass
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def starttls(self): pass
            def login(self,*a): pass
            def send_message(self,msg): sent.append(msg)
        for k,v in {'SMTP_HOST':'smtp.invalid','SMTP_USER':'synthetic@phase4.invalid','SMTP_PASSWORD':'synthetic-fixture-only','SMTP_FROM':'synthetic@phase4.invalid'}.items(): monkeypatch.setenv(k,v)
        monkeypatch.setattr('storefront_routes.smtplib.SMTP',SMTP)
        async with use_bot_tenant(BotTenantScope(tenant_id=tenant['_id'],slug=tenant['slug'],database_name=db.name,db_handle=db)):
            await _send_email_code('synthetic-customer@phase4.invalid','000000','register')
            name='SellerBottel' if mode=='platform' else 'Email Brand'
            assert name in sent[0]['Subject'] and name in sent[0]['From']
            assert ('Powered by SellerBottel' in sent[0].get_content())==(mode=='co_branded')
            assert name in await _resolve_bot_display_name({})
            if mode=='tenant_only': assert 'SellerBottel' not in sent[0].as_string()
    asyncio.run(run())
