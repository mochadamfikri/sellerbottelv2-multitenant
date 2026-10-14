"""Idempotent, isolated demo seed. No arbitrary database or live credential input."""
import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4
from uat_runtime import configure, ROOT, PRIVATE
configure()
from db import client, platform_db
from dependencies import get_tenant_registry
from auth import seed_admin, hash_password
from tenant_provisioning import provision_tenant_database
from domain_registry import register_domain
from bot_tenant_scope import BotTenantScope, use_bot_tenant
from commerce.physical.models import VariantBody, create_variant
from commerce.physical.stock import PhysicalStock
from inventory import add_records
from payments import credentials

async def main():
    platform=platform_db(); registry=get_tenant_registry()
    await registry.ensure_indexes(); await seed_admin()
    accounts=json.loads((PRIVATE/'credentials.json').read_text())
    await platform.platform_config.update_one({'_id':'promo_config'},{'$set':{'promo_domain':'idseconnect.my.id','site_name':'IDSEConnect UAT'}},upsert=True)
    release=json.loads((ROOT/'backend/.release-kasera-private.json').read_text())
    fields={'api_key':release['api_key'],'webhook_secret':(ROOT/'backend/.secretkaserapay').read_text().strip()}
    assert fields['api_key'].startswith('kp_test_')
    credential=await platform.gateway_credentials.find_one({'tenant_id':'platform-idse','provider':'kasera','revoked':False})
    version=credential['_id'] if credential else await credentials.save(platform,'platform-idse','kasera','sandbox',fields)
    adapter=await credentials.load(platform,'platform-idse',version); caps=await adapter.connect()
    await platform.platform_payment_settings.update_one({'_id':'kasera'},{'$set':{'credential_id':version,'capabilities':caps},'$setOnInsert':{'platform_fee':250,'platform_fee_tiers':[]}},upsert=True)
    manifest=[]
    for label,slug,name in [('a','fashion-demo','IDSE Fashion Demo'),('b','digital-demo','IDSE Digital Demo')]:
        tenant=await registry.get_tenant(slug)
        if not tenant: tenant=await registry.create_tenant(slug,name,'demo')
        await provision_tenant_database(slug,client)
        database=client[tenant['database_name']]
        await registry.update_status(slug,'active')
        await platform.tenants.update_one({'_id':tenant['_id']},{'$set':{'metadata.capabilities.can_white_label':True,'metadata.capabilities.custom_email_branding_enabled':True}})
        for base,purpose in [('idseconnect.my.id','storefront'),('idsestock.my.id','stock_panel')]:
            await register_domain(client,domain=f'{slug}.{base}',tenant_id=tenant['_id'],purpose=purpose,origin='owner_subdomain',created_by='uat-seed')
        owner=accounts['tenant_'+label];customer=accounts['customer_'+label]
        now=datetime.now(timezone.utc)
        await platform.tenant_owners.update_one({'email':owner['email']},{'$setOnInsert':{'tenant_id':tenant['_id'],'tenant_slug':slug,'store_name':name,'password_hash':hash_password(owner['password']),'created_at':now.isoformat()}},upsert=True)
        await database.store_customers.update_one({'email':customer['email']},{'$setOnInsert':{'_id':str(uuid4()),'password_hash':hash_password(customer['password']),'balance_idr':0,'balance_usd':0,'verified_at':now,'created_at':now,'session_version':0}},upsert=True)
        await database.payment_settings.update_one({'_id':'main'},{'$set':{'payment_mode':'platform_settlement','provider':'kasera','environment':'sandbox','credential_id':version,'capabilities':caps}},upsert=True)
        await database.settings.update_one({'_id':'main'},{'$set':{'store_name':name,'manual_shipping_fee':10000,'manual_rate':16000,'rate_mode':'manual','join_gate_enabled':False,'bank_enabled':False,'qris_enabled':False,'store_qris_enabled':False}},upsert=True)
        async with use_bot_tenant(BotTenantScope(tenant_id=tenant['_id'],slug=slug,database_name=database.name,db_handle=database)):
            for pid,pname,kind,price in [('hoodie-demo','Hoodie Demo','physical',150000),('gemini-demo','Gemini AI Demo','digital_auto',15000),('vps-demo','VPS Setup Demo','service',25000)]:
                await database.products.update_one({'_id':pid},{'$setOnInsert':{'name':pname,'description':'Synthetic UAT demo — not a real product or account.','active':True,'fulfillment_type':kind,'delivery_type':'inventory' if kind=='digital_auto' else kind,'price_idr':price,'price_usd':price/16000,'inventory_schema':['email','password'],'created_at':now.isoformat()}},upsert=True)
            from promo_service import create_coupon
            if not await database.promo_coupons.find_one({'code':'UAT10'}):
                await create_coupon({'code':'UAT10','type':'percent','value':10,'currency':'IDR','quota_total':100,'per_user_limit':10,'min_purchase':0,'max_discount':10000,'product_ids':[],'active':True})
            await add_records('gemini-demo',[{'email':f'{slug}-{i}@example.test','password':f'SYNTHETIC-UAT-{i}'} for i in range(1,21)],['email','password'])
            for color,code in [('Black','BLK'),('White','WHT')]:
                for size in ['M','L']:
                    sku=f'FASH-{code}-{size}' if label=='a' else f'DIG-{code}-{size}'
                    if not await database.physical_variants.find_one({'sku':sku}):
                        variant=await create_variant(database,'hoodie-demo',VariantBody(sku=sku,option_values={'Color':color,'Size':size},weight=500))
                        await PhysicalStock(database).move(variant['_id'],'RECEIVE',20,reference_id='uat-opening')
        manifest.append({'slug':slug,'tenant_id':tenant['_id'],'database_name':database.name})
    (PRIVATE/'demo-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(PRIVATE/'demo-manifest.json').chmod(0o600)
    print(json.dumps({'result':'PASS','tenants':manifest,'roles':5,'kasera':'sandbox'}));client.close()

if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as error:
        print(json.dumps({'result':'FAIL','error_type':type(error).__name__}));raise SystemExit(1)
