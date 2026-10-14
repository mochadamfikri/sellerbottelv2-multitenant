"""Build an immutable normalized input view from the accepted local archives.
No new production snapshot; no source changes; no network or app imports.
"""
import json,os,sys,uuid,hashlib,re
from pathlib import Path
from bson import BSON,json_util
from dotenv import dotenv_values
from verify_real_snapshot_intake import archive_documents,TRANSFER
from legacy_migration.codec import census,digest,json_hash,doc_hash,identity,safe_json
from legacy_migration.snapshot import Snapshot,COLLECTIONS
from legacy_migration.safety import PLATFORM,ARCHIVE,PRIVATE,guard_environment,block_network

BASE=PRIVATE/'real-v3'
VIEW=BASE/'normalized-source'
E=Path(__file__).resolve().parents[1]/'test_reports/offline-real-data-v1-v3-rehearsal-20261010'


def main():
    guard_environment();block_network();os.umask(0o077)
    assert not VIEW.exists(),'NORMALIZED_VIEW_ALREADY_FROZEN'
    accepted=json.loads((TRANSFER/'public-manifest/source-manifest.json').read_text())
    transfer_hashes={}
    for line in (TRANSFER/'checksums/SHA256SUMS').read_text().splitlines():
        h,rel=line.split(maxsplit=1);assert digest((TRANSFER/rel).read_bytes())==h;transfer_hashes[rel]=h
    docs={};raw={};meta={}
    for db in accepted['databases']:
        d,m=archive_documents(TRANSFER/'db'/f'{db}.archive.gz')
        for value in m.values():value.setdefault('options',{})
        raw.update(d);meta.update(m)
    for key,values in raw.items():
        assert key[1] in COLLECTIONS
        docs[key]=[BSON(v).decode() for v in values]
        assert len(values)==accepted['databases'][key[0]][key[1]]['count']
    assert sum(map(len,docs.values()))==9521 and len(docs)==111
    admin=docs['sellerbottel','admins'];assert len(admin)==1
    escrow=dotenv_values(TRANSFER/'escrow/private/backend/.env',interpolate=False)
    token=escrow.get('TELEGRAM_TOKEN') or escrow.get('BOT_TOKEN')
    assert token and token.split(':',1)[0].isdigit()
    tenant_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'offline-rehearsal:sellerbottel-cutover-20261010-062415:owner'))
    owner={'approved':True,'synthetic':False,'rehearsal_only':True,'runtime_enabled':False,'platform_database':PLATFORM,
           'tenant_uuid':tenant_id,'tenant_slug':'legacy-owner','database_name':'sellerbottel_real_rehearsal_tenant_legacy_owner',
           'legacy_admin_id':admin[0]['_id'],'platform_principal':str(uuid.uuid5(uuid.UUID(tenant_id),'platform-rehearsal-principal')),
           'tenant_owner_principal':str(uuid.uuid5(uuid.UUID(tenant_id),'tenant-rehearsal-principal')),
           'bot_numeric_id':int(token.split(':',1)[0]),'source_machine':'accepted-local-production-snapshot',
           'source_database':'sellerbottel','allowed_domains':[],
           'source_owner_provenance':{'collection':'admins','typed_id_hash':identity(admin[0]['_id']),'document_hash':doc_hash(admin[0]),
                                     'basis':'single preserved source admin; owner-authorized offline rehearsal only; no email/username inference'},
           'bot_source_provenance':'numeric token prefix in preserved escrow; no provider verification',
           'principal_policy':'deterministic offline placeholders; not provisioned as live login accounts'}
    assert not any(d.get('session_encrypted') for (db,c),rows in docs.items() if c=='tg_accounts' for d in rows), 'SESSION_CRYPTO_ADAPTER_REQUIRED'
    keys={'INVENTORY_ENCRYPTION_KEY':escrow['INVENTORY_ENCRYPTION_KEY']}
    safe_json(BASE/'offline-keys.json',keys);safe_json(BASE/'ownership.json',owner)
    manifest={'version':1,'snapshot_id':'accepted-sellerbottel-cutover-20261010-062415','source_type':'real_snapshot','timestamp':accepted['at_start'],
       'fence_marker':transfer_hashes['public-manifest/write-fence.json'],
       'runtime_bundle':{'commit':(TRANSFER/'code/git-head').read_text().strip(),'dirty_patch_hash':transfer_hashes['code/production-dirty-binary.patch'],'bundle_hash':transfer_hashes['code/production-working-tree.tar.gz']},
       'ownership':owner,'files':{},'collections':[],'schema_decisions':{},'recovery_decisions':{},'escrow_references':['offline-keys.json outside source view'],
       'strategy':'accounts_active_history_archive','accepted_transfer_hashes':transfer_hashes}
    VIEW.mkdir(mode=0o700)
    def write(rel,data):
        path=VIEW/rel;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.write_bytes(data);path.chmod(0o600);manifest['files'][rel]=digest(data)
    field_rows=[];coverage=[]
    # Explicit allowlist prevents an unfamiliar account field from receiving active status.
    bot_roots=set('_id telegram_id balance_idr balance_usd admin_balance_audit blocked bot2_last_message_id bot2_state bot2_state_data cart created_at currency deposit_credit_ids first_name frozen frozen_reason lang pending_coupon silent_block_reason silent_blocked silent_blocked_at state state_data username'.split())
    web_roots=set('_id admin_balance_audit balance_idr balance_usd cart created_at email password_hash password_updated_at session_version telegram_id telegram_link_code_hash telegram_link_expires_at telegram_linked_at verified_at wallet_merge'.split())
    audit_keys=set('_id admin_id amount balance_after balance_before created_at currency customer_id direction reason request request_id target_user_id type user_source user_tid wallet_collection'.split())
    for c,allowed in [('bot_users',bot_roots),('store_customers',web_roots)]:
        for d in docs['sellerbottel',c]:
            assert set(d)<=allowed,'UNKNOWN_CRITICAL_ACCOUNT_FIELD'
            for a in d.get('admin_balance_audit',[]):
                assert set(a)<=audit_keys,'UNKNOWN_CRITICAL_AUDIT_FIELD'
                assert set(a.get('request',{}))<=set('amount currency direction reason target'.split())
    for (db,c),values in sorted(docs.items()):
        rel=f'{db}/{c}.bson';mr=f'{db}/{c}.metadata.json'
        write(rel,b''.join(raw[db,c]));write(mr,json_util.dumps(meta[db,c],indent=2).encode())
        manifest['collections'].append({'database':db,'collection':c,'bson':rel,'metadata':mr,'count':len(values)})
        active=db=='sellerbottel' and c in ('bot_users','store_customers')
        target_db=owner['database_name'] if active else ARCHIVE
        target_col=c if active else ('history__'+c if db=='sellerbottel' else 'recovery__'+db.removeprefix('sellerbottel_')+'__'+c)
        schema=census(values);nulls={f['path']:f['occurrences'] for f in schema if f['type']=='null'}
        decisions={f['path']:'preserve_critical' if active else 'preserve' for f in schema};manifest['schema_decisions'][db+'.'+c]=decisions
        for f in schema:
            field=f['path'];root=field.split('.')[0].removesuffix('[]')
            reference={'telegram_id':'bot_users.telegram_id (numeric identity; linked web alias only)','product_id':'products._id','pid':'products._id','order_id':'purchases._id','customer_id':'store_customers._id','user_tid':'bot_users.telegram_id','invoice_id':'purchases.invoice_id','deposit_id':'deposits._id','bot_id':'reseller_bots._id','payout_id':'reseller_payouts._id'}.get(field.split('.')[-1],'none or preserved opaque historical value')
            field_rows.append({'database':db,'collection':c,'dotted_path':field,'BSON_type':f['type'],'present_count':f['documents_present'],
              'missing_count':f['documents_missing'],'type_occurrences':f['occurrences'],'null_count':nulls.get(field,0),'reference_target':reference,
              'target_path':target_db+'.'+target_col+'.'+field,'conversion':'none; exact BSON; raw archival copy also retained',
              'decision':'ACTIVE_COMPATIBILITY' if active else 'ARCHIVE_NON_EXECUTABLE',
              'consumer':('backend/storefront_routes.py + backend/services.py: direct wallet/account compatibility; runtime disabled' if active else 'offline archive reader only; no runtime consumer enabled'),
              'risk':('financial/identity: explicit roots reviewed, values/types preserved' if active else 'historical semantics retained, activation prohibited')})
        coverage.append({'database':db,'collection':c,'count':len(values),'target_database':target_db,'target_collection':target_col,'active':active,'index_count':len(meta[db,c]['indexes']),'options_preserved':True})
    productids={identity(d['_id']) for d in docs['sellerbottel','products']}
    missing={identity(d.get('product_id')) for d in docs['sellerbottel','inventory_items'] if identity(d.get('product_id')) not in productids}
    for key in missing:
        candidates=[]
        for db in accepted['databases']:
            if db=='sellerbottel':continue
            for d in docs.get((db,'products'),[]):
                if identity(d['_id'])==key:candidates.append({'source_database':db,'source_collection':'products','typed_source_id_hash':key,'source_hash':doc_hash(d)})
        manifest['recovery_decisions'][key]={'disposition':'quarantined','reason':'preserve original references; no recovery merge authorized in first rehearsal','target_id_hash':key,'candidates':candidates}
    safe_json(VIEW/'manifest.json',manifest)
    snap=Snapshot(VIEW);snap.validate_schema()
    E.mkdir(parents=True,exist_ok=True)
    for name,data in [('coverage.json',coverage),('field-census.json',field_rows),('ownership-map.json',{k:v for k,v in owner.items() if k not in ('legacy_admin_id','bot_numeric_id','source_owner_provenance')}),
                      ('source-identity.json',{'accepted_encrypted_sha256':'a38a510e23e1fd079d03fb955ece683d83c14145941ef42673af791d16abec1e','snapshot_hash':snap.hash,'ownership_hash':json_hash(owner),'source_timestamp':accepted['at_start'],'collections':111,'documents':9521,'normalized_view':'byte-preserving BSON extraction from accepted archive; no fresh production snapshot','field_rows':len(field_rows)})]:
        # Dynamic numeric/UUID keys are data, even inside a dotted path: redact public paths only.
        def redact(x):
            if isinstance(x,list):return [redact(v) for v in x]
            if isinstance(x,dict):return {k:redact(v) for k,v in x.items()}
            if isinstance(x,str) and ('.' in x or '[' in x):
                x=re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}','{dynamic-key}',x)
                x=re.sub(r'(?<=\.)\d{6,}(?=\.|$)','{dynamic-key}',x)
            return x
        (E/name).write_text(json.dumps(redact(data),indent=2)+'\n')
    safe_json(BASE/'full-field-census-private.json',field_rows)
    print(json.dumps({'status':'PASS','snapshot_hash':snap.hash,'ownership_hash':json_hash(owner),'field_rows':len(field_rows),'collections':len(docs)}))

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('PREPARE_FAILED:'+type(e).__name__+(':'+str(e) if isinstance(e,AssertionError) else ''));raise SystemExit(1)
