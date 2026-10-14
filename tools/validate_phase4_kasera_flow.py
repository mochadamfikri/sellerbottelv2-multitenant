"""Real Kasera test API + disposable Mongo order effects. No webhook certification."""
import asyncio,json,os,secrets,sys
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from cryptography.fernet import Fernet
nonce=secrets.token_hex(4)
# Never load any .env or SMTP/Telegram credential.
path=os.environ['PATH'];os.environ.clear();os.environ.update(PATH=path,PYTHON_DOTENV_DISABLED='1',ENVIRONMENT='development',PHASE3_SANDBOX_ENABLED='true',MONGO_URL='mongodb://127.0.0.1:27019/?serverSelectionTimeoutMS=2000',DB_NAME='sellerbottel_phase4_sandbox_'+nonce,PLATFORM_DB_NAME='sellerbottel_phase4_sandbox_'+nonce,JWT_SECRET=secrets.token_urlsafe(48),INVENTORY_ENCRYPTION_KEY=Fernet.generate_key().decode())
from db import client,platform_db
from dependencies import get_tenant_registry
from bot_tenant_scope import BotTenantScope,use_bot_tenant
from payments import credentials
from payments.orchestrator import checkout,apply_event,repair_paid
from payments.ledger import Ledger
from commerce.physical.models import VariantBody,create_variant
from commerce.physical.stock import PhysicalStock
from storefront_routes import CheckoutBody
import httpx
async def run():
    key=json.loads(Path('/tmp/seller-phase4-sandbox-keys.json').read_text())['kasera'];assert key.startswith('kp_test_')
    platform=platform_db();results={}
    fields={'api_key':key,'webhook_secret':secrets.token_urlsafe(32)} # local storage-binding fixture ONLY; not a provider signing secret
    registry=get_tenant_registry()
    for mode in ['platform_settlement','self_gateway']:
        tenant=await registry.create_tenant('sandbox-'+mode.replace('_','-')+'-'+nonce,'Sandbox store','demo')
        await registry.update_status(tenant['slug'],'active');database=client[tenant['database_name']]
        scope=BotTenantScope(tenant_id=tenant['_id'],slug=tenant['slug'],database_name=database.name,db_handle=database)
        async with use_bot_tenant(scope):
            target,owner=(platform,'platform-idse') if mode=='platform_settlement' else (database,tenant['_id'])
            version=await credentials.save(target,owner,'kasera','sandbox',fields)
            adapter=await credentials.load(target,owner,version);caps=await adapter.connect()
            stored=await target.gateway_credentials.find_one({'_id':version});assert key not in json.dumps(stored,default=str)
            if mode=='platform_settlement': await platform.platform_payment_settings.insert_one({'_id':'kasera','credential_id':version,'capabilities':caps})
            await database.payment_settings.update_one({'_id':'main'},{'$set':{'payment_mode':mode,'capabilities':caps}},upsert=True)
            await database.settings.insert_one({'_id':'main','manual_shipping_fee':0,'manual_rate':16000,'rate_mode':'manual'})
            await database.products.insert_one({'_id':'physical','name':'Sandbox shirt','active':True,'fulfillment_type':'physical','price_idr':15000})
            variant=await create_variant(database,'physical',VariantBody(sku='SANDBOX',weight=200));stock=PhysicalStock(database)
            await stock.move(variant['_id'],'RECEIVE',3,reference_id='opening')
            body=CheckoutBody(items=[{'pid':'physical','variant_id':variant['_id'],'qty':1}],payment_method='gateway:qris',idempotency_key='real-sandbox-checkout',shipping_address={'recipient_name':'Sandbox','phone':'088888888888','address_line_1':'Synthetic dev address','city':'Jakarta','province':'DKI Jakarta','postal_code':'12440'})
            with patch('stock_monitor.schedule_stock_scan',lambda *a:None):
                result=await checkout(database,platform,{'_id':'synthetic'},body)
                payment=await database.order_payments.find_one({'order_id':result['_id']});assert payment.get('provider_payment_id')
                duplicate=await checkout(database,platform,{'_id':'synthetic'},body);assert duplicate['_id']==result['_id']
                url=urlsplit(payment['instructions']['checkout_url']);assert url.hostname=='pay.kasera.id' and url.scheme=='https'
                async with httpx.AsyncClient(timeout=20,follow_redirects=False) as http:
                    response=await http.post('https://pay.kasera.id/api/v1/checkout/'+url.path.split('/p/',1)[1]+'/simulate-payment',json={'outcome':'succeeded'})
                    assert response.status_code==200
                trusted=await adapter.get_payment(payment);assert trusted['status']=='paid'
                # Confirmed authenticated status is the source, not a synthetic webhook.
                event={**trusted,'event_id':'sandbox-status-'+payment['_id']}
                if mode=='platform_settlement':
                    from pymongo.errors import AutoReconnect
                    from unittest.mock import AsyncMock
                    with patch('payments.orchestrator.repair_paid',AsyncMock(side_effect=AutoReconnect('synthetic local outage'))):
                        try: await apply_event(database,platform,payment,event)
                        except AutoReconnect: pass
                    persisted=await database.order_payments.find_one({'_id':payment['_id']});assert persisted['status']=='paid' and persisted['reconciliation']=='paid_effects_pending'
                    await repair_paid(database,platform,persisted)
                else: await apply_event(database,platform,payment,event)
                await apply_event(database,platform,payment,event)
                values=Ledger(database,tenant['_id']).values(await Ledger(database,tenant['_id']).get())
                if mode=='self_gateway': assert not any(values.values()) and await database.settlement_entries.count_documents({})==0
                else: assert values['pending']==payment['amount']-payment['gateway_fee']
                v=await stock.get(variant['_id']);assert v['on_hand']==2 and v['reserved']==0
            results[mode]={'encrypted_storage':True,'checkout_replay':True,'real_sandbox_paid_status':True,'local_effects_once':True,'settlement_correct':True,'local_failure_repair':mode=='platform_settlement'}
    p=ROOT/'test_reports/phase-4-final-hardening-20261008/provider-sandbox.json';out=json.loads(p.read_text());out['kasera']['mongo_integration']=results;out['kasera']['webhook_note']='No provider signing secret or public sandbox callback URL supplied; authenticated status only. Local generated secret is storage-binding fixture, not webhook evidence.';p.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(results));client.close()
if __name__=='__main__':
    try: asyncio.run(run())
    except Exception as error:
        print(json.dumps({'failed':True,'error_type':type(error).__name__}));sys.exit(1)
