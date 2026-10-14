"""Lossless deterministic planner, compatibility-wallet verifier, resumable copier."""
import base64
import json
import re
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from bson import BSON, Binary, Decimal128
from .codec import digest, doc_hash, identity, json_hash
from .safety import require, MigrationError, PLATFORM, AUDIT, ARCHIVE, allowed_databases


def transform_hash():
    root=Path(__file__).parent
    parts=[p.name.encode()+b'\0'+p.read_bytes() for p in sorted(root.glob('*.py'))]
    parts.append((root.parent/'legacy_v3_migrate.py').read_bytes())
    return digest(b'\0'.join(parts))


def unpack(record):return BSON(base64.b64decode(record['bson'])).decode()
def pack(doc):return base64.b64encode(BSON.encode(doc)).decode()


def amount(value,currency):
    try:
        v=Decimal(str(value.to_decimal() if isinstance(value,Decimal128) else value))
        require(not isinstance(value,bool) and v.is_finite() and v>=0,'INVALID_WALLET_AMOUNT')
        require(currency!='IDR' or v==v.to_integral_value(),'FRACTIONAL_IDR')
        return v
    except (InvalidOperation,TypeError,ValueError):raise MigrationError('INVALID_WALLET_AMOUNT') from None


def wallets(docs):
    def telegram_key(value):
        require(isinstance(value,int) and not isinstance(value,bool) and value>0,'INVALID_TELEGRAM_ID')
        return str(int(value))
    bots={telegram_key(d['telegram_id']):d for d in docs['bot_users']}
    require(len(bots)==len(docs['bot_users']),'DUPLICATE_TELEGRAM_ID')
    rows=[];aliases=[]
    for coll in ('bot_users','store_customers'):
        for doc in docs[coll]:
            wid=coll+':'+identity(doc['_id'])
            merge=doc.get('wallet_merge') or {}
            require(not merge or merge.get('status')=='complete','PENDING_WALLET_MERGE')
            if coll=='store_customers' and doc.get('telegram_id') is not None:
                bot=bots.get(telegram_key(doc['telegram_id']))
                require(bot is not None,'WALLET_LINK_ORPHAN')
                require(all(amount(doc.get('balance_'+c.lower(),0),c)==0 for c in ('IDR','USD')),'LINKED_WALLET_NONZERO')
                aliases.append({'alias':wid,'wallet_id':'bot_users:'+identity(bot['_id'])});continue
            for currency in ('IDR','USD'):
                value=amount(doc.get('balance_'+currency.lower(),0),currency)
                rows.append({'wallet_id':wid,'currency':currency,'amount':str(value),
                             'source_collection':coll,'source_hash':doc_hash(doc)})
    return {'accounts':rows,'aliases':aliases,'totals':{c:str(sum((Decimal(r['amount']) for r in rows if r['currency']==c),Decimal(0))) for c in ('IDR','USD')}}


def classify(product):
    explicit=product.get('fulfillment_type')
    if explicit is not None:
        require(explicit in ('digital_auto','digital_manual','service','physical','subscription'),'AMBIGUOUS_PRODUCT_CLASSIFICATION');return explicit
    kind,delivery=product.get('product_kind'),product.get('delivery_type')
    if kind=='service' or delivery=='service':return 'service'
    if kind in ('physical','digital_manual','subscription'):return kind
    if kind in (None,'','digital') and delivery in (None,'','inventory','link','file','session','license','redeem_code','account'):return 'digital_auto'
    raise MigrationError('AMBIGUOUS_PRODUCT_CLASSIFICATION')


def plan(snapshot):
    snapshot.check();snapshot.validate_schema()
    main={c:deepcopy(d) for (db,c),d in snapshot.collections.items() if db=='sellerbottel'}
    for docs in snapshot.collections.values():require(len({identity(d['_id']) for d in docs})==len(docs),'DUPLICATE_SOURCE_ID')
    w=wallets(main);o=snapshot.owner;tenant=o['database_name']
    entries=[];exceptions=[];recovered=[]
    def add(db,c,doc,source_hash,rule,source_key):
        entries.append({'database':db,'collection':c,'id_hash':identity(doc['_id']), 'bson':pack(doc),
                        'source_hash':source_hash,'target_hash':doc_hash(doc),'rule':rule,'reason':rule,'source_key':source_key})
    # Raw BSON archives preserve every byte, including all recovery documents.
    for (db,c),docs in snapshot.collections.items():
        for raw,d in zip(snapshot.raw[(db,c)],docs):
            sid=db+':'+c+':'+identity(d['_id'])
            add(ARCHIVE,'raw_documents',{'_id':sid,'snapshot_id':snapshot.manifest['snapshot_id'],'raw':Binary(raw)},digest(raw),'archive_raw_bson',sid)
        add(ARCHIVE,'collection_metadata',{'_id':db+':'+c,'metadata_json':json.dumps(snapshot.metadata[(db,c)],sort_keys=True),'count':len(docs)},json_hash(snapshot.metadata[(db,c)]),'archive_metadata',db+':'+c)
    for rel,h in snapshot.manifest['files'].items():
        # Archive assets/runtime metadata too, not just collection data.
        if not any(rel==x[k] for x in snapshot.manifest['collections'] for k in ('bson','metadata')):
            add(ARCHIVE,'assets',{'_id':digest(rel.encode()),'path':rel,'sha256':h,'raw':Binary(snapshot.file(rel).read_bytes())},h,'archive_asset',rel)
    add(ARCHIVE,'snapshot_manifests',{'_id':snapshot.hash,'manifest_json':json.dumps(snapshot.manifest,sort_keys=True)},snapshot.hash,'archive_manifest',snapshot.hash)
    products={identity(d['_id']):d for d in main['products']}
    requested={identity(d.get('product_id')) for d in main['inventory_items'] if identity(d.get('product_id')) not in products}
    for order in main['purchases']:
        requested.update(identity(i.get('product_id',i.get('pid'))) for i in order.get('items',[]) if identity(i.get('product_id',i.get('pid'))) not in products)
    decisions=snapshot.manifest['recovery_decisions']
    for missing in sorted(requested):
        dec=decisions.get(missing,{'disposition':'unresolved'})
        require(dec.get('disposition') in ('recovered','historical_tombstone','quarantined','unresolved'),'INVALID_RECOVERY_DISPOSITION')
        if dec['disposition']=='recovered':
            db=dec.get('source_database');require(db in ('sellerbottel_catalog_recovery','sellerbottel_final_probe','sellerbottel_recovery_probe'),'UNAPPROVED_RECOVERY_SOURCE')
            candidate=next((d for d in snapshot.collections.get((db,'products'),[]) if identity(d['_id'])==missing),None)
            require(candidate is not None and dec.get('approved') is True and doc_hash(candidate)==dec.get('source_hash'),'RECOVERY_PROVENANCE_REQUIRED')
            candidate=deepcopy(candidate);candidate['active']=False
            products[missing]=candidate;recovered.append((db,candidate,dec['source_hash']))
        exceptions.append({'kind':'product_reference','id_hash':missing,'disposition':dec['disposition'],'execution_hold':True})
    for d in main['inventory_items']:
        if identity(d.get('product_id')) in requested:
            exceptions.append({'kind':'inventory_orphan','id_hash':identity(d['_id']),'disposition':decisions.get(identity(d.get('product_id')),{}).get('disposition','unresolved'),'execution_hold':True})
    for order in main['purchases']:
        for n,item in enumerate(order.get('items',[])):
            if identity(item.get('product_id',item.get('pid'))) in requested:
                exceptions.append({'kind':'purchase_line_orphan','id_hash':identity({'order':order['_id'],'position':n}),'disposition':'historical_tombstone','execution_hold':True})
    orders={identity(d['_id']) for d in main['purchases']};invoices=Counter(d.get('invoice_id') for d in main['purchases'] if d.get('invoice_id'))
    for d in main['reseller_commissions']:
        if identity(d.get('order_id')) not in orders and (not d.get('invoice_id') or invoices[d['invoice_id']]!=1):
            exceptions.append({'kind':'reseller_commission_orphan','id_hash':identity(d['_id']),'disposition':'unresolved','execution_hold':True})
        if d.get('status')!='paid':
            exceptions.append({'kind':'reseller_financial_hold','id_hash':identity(d['_id']),'disposition':'quarantined','execution_hold':True})
    # Target baseline counters are explicit approved records, not arbitrary existing data.
    baseline=snapshot.manifest.get('approved_target_counters',[])
    counters={d['_id']:deepcopy(d) for d in main['counters']}
    for d in baseline:
        require(re.fullmatch(r'invoice:\d{8}',d.get('_id','')) is not None and isinstance(d.get('seq'),int) and d['seq']>=0,'INVALID_BASELINE_COUNTER')
        if d['_id'] not in counters:counters[d['_id']]=deepcopy(d)
        else:counters[d['_id']]['seq']=max(counters[d['_id']].get('seq',0),d['seq'])
    for order in main['purchases']:
        match=re.fullmatch(r'INV-(\d{8})-(\d+)',str(order.get('invoice_id','')))
        if match:
            key='invoice:'+match[1];counter=counters.setdefault(key,{'_id':key,'seq':0})
            require(isinstance(counter.get('seq'),int) and counter['seq']>=0,'INVALID_INVOICE_COUNTER')
            counter['seq']=max(counter['seq'],int(match[2]))
    for c,docs in main.items():
        for d in docs:
            source=doc_hash(d);rule='lossless_copy'
            if c=='products':
                try:d.setdefault('fulfillment_type',classify(d));rule='additive_fulfillment_type'
                except MigrationError:raise MigrationError('UNKNOWN_CRITICAL_PRODUCT_CLASSIFICATION') from None
            if c=='counters':d=counters.pop(d['_id']);rule='invoice_high_water_or_copy'
            db=PLATFORM if c in ('admins','login_attempts') else tenant
            add(db,c,d,source,rule,'sellerbottel:'+c+':'+identity(d['_id']))
    for d in counters.values():add(tenant,'counters',d,doc_hash(d),'invoice_high_water','derived_counter:'+identity(d['_id']))
    for db,d,h in recovered:
        d.setdefault('fulfillment_type',classify(d));add(tenant,'products',d,h,'recover_inactive_product',db+':products:'+identity(d['_id']))
    # Registry is deliberately inert: no token, no network registration, no app startup.
    add(PLATFORM,'tenants',{'_id':o['tenant_uuid'],'slug':o['tenant_slug'],'database_name':tenant,'status':'migration_hold','migration_only':True},snapshot.hash,'inert_ownership_registry','ownership')
    holds={'_id':'execution','workers_enabled':False,'outbound_enabled':False,'financial_activation':False,'runtime_release_allowed':False}
    add(tenant,'_migration_hold',holds,snapshot.hash,'hold_all_runtime','execution_hold')
    for i,exception in enumerate(exceptions):add(AUDIT,'migration_exceptions',{'_id':snapshot.hash+':'+str(i),**exception},snapshot.hash,'exception_hold','exception:'+str(i))
    for row in w['accounts']:
        add(AUDIT,'migration_wallet_openings',{'_id':snapshot.hash+':'+row['wallet_id']+':'+row['currency'],'snapshot_id':snapshot.manifest['snapshot_id'],'tenant_id':o['tenant_uuid'],'kind':'OPENING_ASSERTION_ONLY',**row},row['source_hash'],'opening_assertion_no_credit',row['wallet_id'])
    for row in w['aliases']:add(AUDIT,'migration_id_map',{'_id':snapshot.hash+':'+row['alias'],**row},snapshot.hash,'wallet_alias',row['alias'])
    for c in ('processed_updates','processed_updates_bot2','reseller_updates'):
        for d in main[c]:
            namespace=str(d.get('bot_id',o['bot_numeric_id'])) if c=='reseller_updates' else (str(o['bot_numeric_id']) if c=='processed_updates' else 'bot2-disabled')
            add(AUDIT,'migration_id_map',{'_id':snapshot.hash+':'+c+':'+identity(d['_id']), 'source_collection':c,'source_id_bson':Binary(BSON.encode({'_id':d['_id']})), 'future_key':o['tenant_slug']+':'+namespace+':'+str(d.get('update_id'))},doc_hash(d),'future_update_namespace_no_replay',c+':'+identity(d['_id']))
    for key,decision in decisions.items():
        add(AUDIT,'migration_recovery_decisions',{'_id':snapshot.hash+':'+key,**decision},snapshot.hash,'approved_recovery_decision',key)
    for rel,h in snapshot.manifest['files'].items():
        add(AUDIT,'migration_asset_map',{'_id':snapshot.hash+':'+digest(rel.encode()),'source_path':rel,'sha256':h},h,'source_file_preserved',rel)
    payload={'version':1,'snapshot_hash':snapshot.hash,'transform_hash':transform_hash(),'ownership':o,'entries':entries,'wallets':w,
             'exceptions':dict(Counter(x['kind'] for x in exceptions)),'baseline_counters':baseline,
             'coverage':{c:len(d) for c,d in main.items()},'source_type':snapshot.manifest['source_type']}
    if snapshot.manifest.get('strategy') == 'accounts_active_history_archive':
        from .real_policy import finalize_plan
        finalize_plan(snapshot, payload)
    payload['plan_hash']=json_hash(payload);return payload


def validate(snapshot,p):
    require(p.get('transform_hash')==transform_hash(),'TRANSFORM_HASH_MISMATCH')
    require(p.get('snapshot_hash')==snapshot.hash,'SOURCE_SNAPSHOT_DRIFT')
    require(plan(snapshot)==p,'PLAN_MISMATCH')
    return p['plan_hash']


def run_id(p):return p['plan_hash']


def preflight(target,p,run):
    tenant=p['ownership']['database_name']
    expected={(r['database'],r['collection'],r['id_hash']):r['target_hash'] for r in p['entries']}
    expected_collections={(d,c) for d,c,_ in expected} | {(r['database'],r['collection']) for r in p.get('collection_specs',[])}
    baseline={(tenant,'counters',identity(d['_id'])):doc_hash(d) for d in p['baseline_counters']}
    for db in target.allowed:
        for c in target.names(db):
            if db==AUDIT and c in ('migration_instance','migration_runs','migration_documents'):continue
            if not run:
                require(db==tenant and c=='counters' and bool(p['baseline_counters']),'TARGET_NOT_EMPTY_OR_CONFLICT')
            else:
                require((db,c) in expected_collections,'TARGET_NOT_EMPTY_OR_CONFLICT')
            for doc in target.docs(db,c):
                key=(db,c,identity(doc['_id']));h=doc_hash(doc)
                require((run and expected.get(key)==h) or baseline.get(key)==h,'TARGET_NOT_EMPTY_OR_CONFLICT')


def apply(snapshot,p,target,keys,crash_after=None,fault=None):
    validate(snapshot,p);require(target.allowed==allowed_databases(p['ownership']),'TARGET_OWNERSHIP_MISMATCH')
    crypto=keys.verify(snapshot.collections)
    rid=run_id(p);run=target.get(AUDIT,'migration_runs',rid)
    # Any other unfinished run on this instance makes changed-plan resume impossible.
    other=[r for r in target.docs(AUDIT,'migration_runs') if r['_id']!=rid and r['state']!='rolled_back']
    require(not other,'CHANGED_PLAN_CANNOT_RESUME')
    if run:require(run['instance']==target.instance and run['state']!='rolled_back','RUN_STATE_CONFLICT')
    preflight(target,p,run)
    if not run:
        run={'_id':rid,'state':'applying','instance':target.instance,'snapshot_hash':snapshot.hash,'transform_hash':p['transform_hash']}
        target.put(AUDIT,'migration_runs',run)
    written=0
    for i,r in enumerate(p['entries']):
        if fault:fault('before_write',i,r)
        d=unpack(r);old=target.get(r['database'],r['collection'],d['_id'])
        base=next((b for b in p['baseline_counters'] if r['database']==p['ownership']['database_name'] and r['collection']=='counters' and identity(b['_id'])==r['id_hash']),None)
        if base is not None and old==base and doc_hash(old)!=r['target_hash']:
            target.replace(r['database'],r['collection'],old,d);written+=1
        else:written+=int(target.put(r['database'],r['collection'],d))
        require(doc_hash(target.get(r['database'],r['collection'],d['_id']))==r['target_hash'],'WRITE_REREAD_MISMATCH')
        if crash_after is not None and i+1==crash_after:raise MigrationError('INJECTED_CRASH_AFTER_WRITE_BEFORE_CHECKPOINT')
        if fault:fault('after_write_before_checkpoint',i,r)
        receipt={'_id':rid+':'+str(i),'run_id':rid,'snapshot_id':snapshot.manifest['snapshot_id'],'source_hash':r['source_hash'],'target_hash':r['target_hash'],'transform_rule':r['rule'],'reason':r['reason'],'source_key_hash':digest(r['source_key'].encode())}
        target.put(AUDIT,'migration_documents',receipt)
        if fault:fault('after_checkpoint',i,r)
    if p.get('collection_specs'):
        from .real_policy import install_indexes
        install_indexes(target,p)
    if fault:fault('before_verification',len(p['entries']),None)
    result=verify(snapshot,p,target,keys)
    latest=target.get(AUDIT,'migration_runs',rid)
    if latest['state']!='verified':target.replace(AUDIT,'migration_runs',latest,{**latest,'state':'verified'})
    return {**result,'new_writes':written,'decrypt':crypto}


def verify(snapshot,p,target,keys):
    validate(snapshot,p)
    require(target.get(AUDIT,'migration_runs',run_id(p)) is not None,'RUN_REQUIRED')
    preflight(target,p,True)
    for r in p['entries']:
        actual=target.get(r['database'],r['collection'],unpack(r)['_id'])
        require(actual is not None and doc_hash(actual)==r['target_hash'],'TARGET_HASH_MISMATCH')
    tenant=p['ownership']['database_name']
    require(wallets({c:target.docs(tenant,c) for c in ('bot_users','store_customers')})==p['wallets'],'WALLET_RECONCILIATION_FAILED')
    if p.get('strategy') == 'accounts_active_history_archive':
        from .real_policy import verify_policy, location
        verify_policy(snapshot,p,target)
        decrypt=keys.verify({('sellerbottel',c):target.docs(*location(p,c)) for c in ('inventory_items','reseller_bots','tg_accounts')})
    else:
        decrypt=keys.verify({('sellerbottel',c):target.docs(tenant,c) for c in ('inventory_items','reseller_bots','tg_accounts')})
    target_hash=json_hash([r['target_hash'] for r in p['entries']])
    return {'status':'PASS','source_type':p['source_type'],'snapshot_hash':snapshot.hash,'plan_hash':p['plan_hash'],'transform_hash':p['transform_hash'],
            'target_instance':target.instance,'coverage':p['coverage'],'wallet_totals':p['wallets']['totals'],'wallet_aliases':len(p['wallets']['aliases']),
            'decrypt':decrypt,'orphan_dispositions':p['exceptions'],'target_hash':target_hash,'runtime_release_allowed':False}


def rollback(snapshot,p,target):
    validate(snapshot,p);rid=run_id(p);run=target.get(AUDIT,'migration_runs',rid)
    require(run and run['instance']==target.instance,'RUN_REQUIRED')
    if run['state']=='rolled_back':return {'status':'PASS','already_rolled_back':True}
    preflight(target,p,True)
    # Validate everything before deleting anything, including changed target documents.
    for r in p['entries']:
        doc=target.get(r['database'],r['collection'],unpack(r)['_id'])
        if doc is not None:require(doc_hash(doc)==r['target_hash'] or doc in p['baseline_counters'],'ROLLBACK_CONFLICT')
    for r in reversed(p['entries']):
        doc=target.get(r['database'],r['collection'],unpack(r)['_id'])
        if doc is None:continue
        base=next((b for b in p['baseline_counters'] if r['database']==p['ownership']['database_name'] and r['collection']=='counters' and identity(b['_id'])==r['id_hash']),None)
        if base is not None:
            if doc!=base:target.replace(r['database'],r['collection'],doc,base)
        else:target.delete(r['database'],r['collection'],doc);target.drop_empty(r['database'],r['collection'])
    for spec in p.get('collection_specs',[]):target.drop_empty(spec['database'],spec['collection'])
    latest=target.get(AUDIT,'migration_runs',rid);target.replace(AUDIT,'migration_runs',latest,{**latest,'state':'rolled_back'})
    return {'status':'PASS','business_baseline_restored':True,'audit_receipts_retained':True}
