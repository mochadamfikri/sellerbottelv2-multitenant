"""Real sandbox payment; only external webhook ingress may apply payment effects."""
import asyncio,json,sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from run_release_kasera import ROOT, config
from db import client,platform_db
from dependencies import get_tenant_registry
from bot_tenant_scope import BotTenantScope,use_bot_tenant
from payments import credentials
from payments.orchestrator import checkout
from payments.ledger import Ledger
from commerce.physical.models import VariantBody,create_variant
from commerce.physical.stock import PhysicalStock
from storefront_routes import CheckoutBody
import httpx
TIER_TEST='--tier-fees' in sys.argv
BASE_AMOUNT=25001 if TIER_TEST else 15001
SUFFIX='-tier-fees' if TIER_TEST else '-buyer-fees'
REPORT=ROOT/('test_reports/release-blocker-kasera-20261009/genuine-callback'+SUFFIX+'.json')

async def run():
    platform=platform_db()
    fields={'api_key':config['api_key'],'webhook_secret':(ROOT/'backend/.secretkaserapay').read_text().strip()}
    assert fields['api_key'].startswith('kp_test_')
    registry=get_tenant_registry()
    results={}
    for mode in ['platform_settlement','self_gateway']:
        slug=('release-tier-' if TIER_TEST else 'release-buyer-')+mode.replace('_','-')
        tenant=await platform.tenants.find_one({'slug':slug})
        if not tenant:
            tenant=await registry.create_tenant(slug,'Kasera release sandbox','demo')
            await registry.update_status(slug,'active')
        database=client[tenant['database_name']]
        async with use_bot_tenant(BotTenantScope(tenant_id=tenant['_id'],slug=slug,database_name=database.name,db_handle=database)):
            target,owner=(platform,'platform-idse') if mode=='platform_settlement' else (database,tenant['_id'])
            existing=await target.gateway_credentials.find_one({'tenant_id':owner,'provider':'kasera','revoked':{'$ne':True}})
            version=existing['_id'] if existing else await credentials.save(target,owner,'kasera','sandbox',fields)
            adapter=await credentials.load(target,owner,version);caps=await adapter.connect()
            if mode=='platform_settlement':
                await platform.platform_payment_settings.replace_one({'_id':'kasera'},{'_id':'kasera','credential_id':version,'capabilities':caps, 'platform_fee':250, 'platform_fee_tiers':[{'min_amount':10000,'max_amount':20000,'fee':250},{'min_amount':20001,'max_amount':50000,'fee':500}] if TIER_TEST else []},upsert=True)
            await database.payment_settings.update_one({'_id':'main'},{'$set':{'payment_mode':mode,'credential_id':version,'provider':'kasera','environment':'sandbox','capabilities':caps}},upsert=True)
            await database.settings.update_one({'_id':'main'},{'$set':{'manual_shipping_fee':0,'manual_rate':16000,'rate_mode':'manual'}},upsert=True)
            await database.products.update_one({'_id':'physical'},{'$setOnInsert':{'name':'Sandbox shirt','active':True,'fulfillment_type':'physical','price_idr':BASE_AMOUNT}},upsert=True)
            variant=await database.physical_variants.find_one({'sku':'RELEASE-SANDBOX'})
            if not variant: variant=await create_variant(database,'physical',VariantBody(sku='RELEASE-SANDBOX',weight=200))
            stock=PhysicalStock(database);await stock.move(variant['_id'],'RECEIVE',3,reference_id='opening')
            from payments.launch import payment_snapshot,buyer_quote
            fee_quote=buyer_quote(BASE_AMOUNT,await payment_snapshot(platform,'kasera','qris',next(m for m in caps['method_details'] if m['code']=='qris'),payment_mode=mode,base_amount=BASE_AMOUNT))
            body=CheckoutBody(expected_gateway_total=fee_quote['total'],items=[{'pid':'physical','variant_id':variant['_id'],'qty':1}],payment_method='gateway:qris',idempotency_key='genuine-release-checkout',shipping_address={'recipient_name':'Sandbox','phone':'088888888888','address_line_1':'Synthetic dev address','city':'Jakarta','province':'DKI Jakarta','postal_code':'12440'})
            with patch('stock_monitor.schedule_stock_scan',lambda *a:None):
                order=await checkout(database,platform,{'_id':'synthetic'},body)
            payment=await database.order_payments.find_one({'order_id':order['_id']})
            url=urlsplit(payment['instructions']['checkout_url']);assert url.hostname=='pay.kasera.id' and url.scheme=='https'
            if payment['status']=='pending':
                async with httpx.AsyncClient(timeout=30,follow_redirects=False) as http:
                    response=await http.post('https://pay.kasera.id/api/v1/checkout/'+url.path.split('/p/',1)[1]+'/simulate-payment',json={'outcome':'succeeded'})
                    assert response.status_code==200
            for _ in range(90):
                payment=await database.order_payments.find_one({'_id':payment['_id']})
                if payment['status']=='paid' and not payment.get('reconciliation'):break
                await asyncio.sleep(1)
            receipt=await platform.payment_events.find_one({'route_id':payment['_id'],'state':'applied'})
            variants=await stock.get(variant['_id']);ledger=Ledger(database,tenant['_id']);account=await ledger.get()
            entries=await database.settlement_entries.find({'payment_id':payment['_id']}).to_list(20)
            result={'provider':'kasera','environment':'sandbox','mode':mode,'genuine_callback':bool(receipt),'payment_status':payment['status'],'reconciliation':payment.get('reconciliation'),'receipt_state':receipt.get('state') if receipt else None,'gross':payment['amount'],'gateway_fee':payment.get('gateway_fee'),'platform_fee':payment.get('platform_fee'),'fee_quote':payment.get('fee_quote'),'settlement':ledger.values(account),'entries':[{'type':e['type'],'amount':e['amount']} for e in entries],'stock':{'on_hand':variants['on_hand'],'reserved':variants['reserved']},'route_id':payment['_id'],'tenant_database':database.name}
            results[mode]=result;REPORT.write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(result),flush=True)
            assert receipt and payment['status']=='paid' and payment.get('reconciliation') is None
            assert variants['on_hand']==2 and variants['reserved']==0
            assert len(entries)==(5 if mode=='platform_settlement' else 0)
            assert payment['platform_fee']==((500 if TIER_TEST else 250) if mode=='platform_settlement' else 0)
            assert payment['amount']==fee_quote['total']
            assert payment['gateway_fee']==fee_quote['gateway_fee']
            assert order['payment_fee']==fee_quote['gateway_fee']
            if mode=='platform_settlement':assert ledger.values(account)['pending']==BASE_AMOUNT-(500 if TIER_TEST else 250)
    if TIER_TEST:
        # The example tiers belong to this test only. Keep default configuration
        # flat Rp250; existing payments retain their captured Rp500 policy.
        await platform.platform_payment_settings.update_one({'_id':'kasera'},{'$set':{'platform_fee':250,'platform_fee_tiers':[]}})
    # An early test exceeded Mongo's database-name limit before creating data.
    invalid=await platform.tenants.find_one({'slug':'release-kasera-platform-settlement-after-restart'})
    if invalid and len(invalid['database_name'])>63:
        assert await platform.payment_routes.count_documents({'tenant_id':invalid['_id']})==0
        await platform.tenants.delete_one({'_id':invalid['_id']})
    client.close()
if __name__=='__main__':
    try: asyncio.run(run())
    except Exception as e:
        print(json.dumps({'failed':True,'error_type':type(e).__name__}),flush=True);sys.exit(1)
