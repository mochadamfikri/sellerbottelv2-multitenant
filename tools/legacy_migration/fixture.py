"""Synthetic production-shaped counts, with fake keys and fake data only."""
import base64
import json
from datetime import datetime
from pathlib import Path
from bson import BSON, Int64, ObjectId, Decimal128, Binary
from cryptography.fernet import Fernet
from .snapshot import COLLECTIONS,RECOVERY,Snapshot
from .codec import digest,doc_hash,identity,census,safe_json

COUNTS=dict(zip(COLLECTIONS,[1,7,53,5,41,2,1116,80,15,21,1,15,0,0,4,4,4,13,6,0,385,0,9,64,88,1,48,8,46,29,607,4,0,0,0,0,1546,42,1,3,61,1,18,1,3,4,0]))

def create_fixture(root, key_path, small=False):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);root.chmod(0o700)
    key=Fernet.generate_key();cipher=Fernet(key)
    safe_json(key_path,{'INVENTORY_ENCRYPTION_KEY':key.decode(),'TG_SESSION_KEY':key.decode()})
    counts={c:(min(n,2) if small else n) for c,n in COUNTS.items()}
    data={c:[{'_id':c+'-'+str(i)} for i in range(n)] for c,n in counts.items()}
    data['bot_users']=[{'_id':'bot-'+str(i),'telegram_id':Int64(9000000000+i),'balance_idr':68212650 if i==0 else 0,'balance_usd':0,'currency':None,'deposit_credit_ids':['deposit-0'],'admin_balance_audit':[{'_id':'adjust-0','request_id':'synthetic'}]} for i in range(counts['bot_users'])]
    data['store_customers']=[{'_id':'web-linked','telegram_id':Int64(9000000000),'balance_idr':0,'balance_usd':0},*({'_id':'web-'+str(i),'balance_idr':2410800 if i==1 else 0,'balance_usd':0,'email':'synthetic'+str(i)+'@example.invalid'} for i in range(1,counts['store_customers']))]
    data['products']=[{'_id':'product-'+str(i),'product_kind':'service' if i>=39 else 'digital','delivery_type':'service' if i>=39 else 'inventory','inventory_schema':['credential'],'price_idr':10000,'price_usd':0.0,'active':i<33,'stock':None} for i in range(counts['products'])]
    payload=json.dumps({'credential':'SYNTHETIC-INVENTORY-NEVER-LOG','__file_name':'synthetic.txt','__file_data_b64':base64.b64encode(b'SYNTHETIC-FILE-ONLY').decode()}).encode()
    data['inventory_items']=[{'_id':'inventory-'+str(i),'product_id':'missing-'+str(i%2) if i<min(82,counts['inventory_items']) else 'product-0','secret':cipher.encrypt(payload).decode(),'fingerprint':digest(str(i).encode()),'status':'available' if (i<21 or 82<=i<822) else 'sold','order_id':'order-0' if not (i<21 or 82<=i<822) else None,'reservation_id':None,'marketing':{'event_id':None}} for i in range(counts['inventory_items'])]
    if small:data['inventory_items'][-1]['status']='sold'
    data['purchases']=[{'_id':'order-'+str(i),'invoice_id':f'INV-20261009-{i+1:04d}','items':[{'product_id':'missing-'+str(i%2) if i<14 else 'product-0','qty':1,'unit_price':10000,'subtotal':10000}],'total':10000,'currency':'IDR','status':'delivered' if i<72 else ('failed' if i<79 else 'expired'),'payment_method':'balance' if i<74 else 'qris'} for i in range(counts['purchases'])]
    data['deposits']=[{'_id':'deposit-'+str(i),'amount':10000,'currency':'IDR','status':'approved' if i<3 else ('rejected' if i<5 else 'expired'),'user_tid':Int64(9000000000)} for i in range(counts['deposits'])]
    data['gopay_payments']=[{'_id':'payment-'+str(i),'status':'confirmed' if i<5 else 'expired','deposit_id':'deposit-0','amount':10001,'tx_id':'synthetic-tx-'+str(i)} for i in range(counts['gopay_payments'])]
    data['settings']=[{'_id':'main','gopay_qr_timeout_minutes':15,'join_gate_enabled':True,'required_channels':[],'unknown_legacy_field':{'nested':None},'mixed':{'oid':ObjectId('000000000000000000000001'),'string_id':'000000000000000000000001','long':Int64(4),'int':4,'double':4.0,'decimal':Decimal128('4.00'),'date':datetime(2026,10,9),'binary':Binary(b'fixture'),'array':[None,Int64(7)]}}]
    data['counters'][0]={'_id':'invoice:20261009','seq':100}
    for c in ('processed_updates','processed_updates_bot2','reseller_updates'):
        data[c]=[{'_id':str(i),'update_id':Int64(i),**({'bot_id':'reseller-0'} if c=='reseller_updates' else {})} for i in range(counts[c])]
    data['reseller_bots']=[{'_id':'reseller-0','owner_tid':Int64(9000000000),'telegram_bot_id':Int64(8000000000),'token_encrypted':cipher.encrypt(b'SYNTHETIC-NOT-A-TELEGRAM-TOKEN').decode(),'status':'inactive_no_sales','markups':{'product-0':250}}]
    data['reseller_commissions']=[{'_id':'commission-'+str(i),'bot_id':'reseller-0','order_id':'missing-order-'+str(i),'status':'paid' if i<17 else 'pending_payout','amount':250} for i in range(counts['reseller_commissions'])]
    data['reseller_commissions'][-1]['status']='pending_payout'
    data['reseller_payouts']=[{'_id':'payout-0','status':'paid','amount':4250}]
    for d in data['promo_coupons']:d.update(code=d['_id'],used_count=1,quota_total=10)
    for d in data['promo_coupon_usage']:d.update(count=1,reservation_ids=['order-0'])
    for i,d in enumerate(data['tg_accounts']):d.update(status='revoked' if i<8 else 'otp_pending',session_encrypted=None)
    recovery={db:{'products':[{'_id':'missing-0','product_kind':'digital','delivery_type':'inventory','active':True,'name':'Recovered synthetic'}],'inventory_items':[]} for db in RECOVERY}
    owner={'approved':True,'synthetic':True,'platform_database':'sellerbottel_migration_platform','tenant_uuid':'00000000-0000-4000-8000-000000000001','tenant_slug':'synthetic-owner','database_name':'sellerbottel_migration_legacy_synthetic_owner','legacy_admin_id':'admins-0','platform_principal':'synthetic-platform','tenant_owner_principal':'synthetic-owner','bot_numeric_id':7000000000,'source_machine':'synthetic-fixture','source_database':'sellerbottel','allowed_domains':['shop.example.invalid']}
    m={'version':1,'snapshot_id':'synthetic-v1-20261009','source_type':'synthetic','timestamp':'2026-10-09T00:00:00Z','fence_marker':'synthetic-offline-fence','runtime_bundle':{'commit':'synthetic','dirty_patch_hash':digest(b'synthetic-patch'),'bundle_hash':digest(b'synthetic-runtime')},'ownership':owner,'files':{},'collections':[],'schema_decisions':{},'escrow_references':['private-offline-key-file'],'recovery_decisions':{identity('missing-0'):{'disposition':'recovered','approved':True,'source_database':RECOVERY[0],'source_hash':doc_hash(recovery[RECOVERY[0]]['products'][0])}}}
    for db,collections in {'sellerbottel':data,**recovery}.items():
        for c,docs in collections.items():
            rel=f'{db}/{c}.bson';p=root/rel;p.parent.mkdir(exist_ok=True);raw=b''.join(BSON.encode(d) for d in docs);p.write_bytes(raw);p.chmod(0o600);m['files'][rel]=digest(raw)
            metarel=f'{db}/{c}.metadata.json';metadata={'options':{},'indexes':[{'key':{'_id':1},'name':'_id_','unique':True}]}
            safe_json(root/metarel,metadata);m['files'][metarel]=digest((root/metarel).read_bytes())
            m['collections'].append({'database':db,'collection':c,'bson':rel,'metadata':metarel,'count':len(docs)})
            m['schema_decisions'][db+'.'+c]={f['path']:'preserve_critical' for f in census(docs)}
    safe_json(root/'manifest.json',m)
    return Snapshot(root)
