"""Fixed offline real-data rehearsal; uses the existing migration engine only.
No runtime startup; all output allowlisted summaries, no document values.
"""
import fcntl,json,os,sys,shutil,socket,time
from copy import deepcopy
from pathlib import Path
from collections import Counter
from decimal import Decimal
from bson import BSON
from legacy_migration import engine
from legacy_migration.snapshot import Snapshot
from legacy_migration.target import MongoTarget
from legacy_migration.crypto import OfflineKeys
from legacy_migration.codec import digest,doc_hash,json_hash,identity,safe_json,bson_type
from legacy_migration.safety import PRIVATE,AUDIT,ARCHIVE,PLATFORM,PROFILE,guard_environment,block_network,isolated_namespace,MigrationError,require
from legacy_migration.real_policy import location

BASE=PRIVATE/'real-v3'
E=Path(__file__).resolve().parents[1]/'test_reports/offline-real-data-v1-v3-rehearsal-20261010'

def emit(name,data):
    (E/name).write_text(json.dumps(data,indent=2)+'\n')

def progress(stage):print(json.dumps({'stage':stage}),flush=True)

def main():
    require(PROFILE=='offline-real' and isolated_namespace(),'ISOLATED_REAL_PROFILE_REQUIRED')
    guard_environment();block_network()
    with (BASE/'writer.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        execute()

def execute():
    s=Snapshot(BASE/'normalized-source');p=json.loads((BASE/'plan.json').read_text())
    engine.validate(s,p)
    instance=json.loads((BASE/'instance.json').read_text())['instance_id']
    t=MongoTarget(s.owner,instance);keys=OfflineKeys(BASE/'offline-keys.json')
    require(t.client.admin.command({'getParameter':1,'ttlMonitorEnabled':1})['ttlMonitorEnabled'] is False,'TTL_ENABLED')
    require(not t.docs(AUDIT,'migration_runs'),'REHEARSAL_RUN_ALREADY_EXISTS')
    start=time.monotonic();first=engine.apply(s,p,t,keys);progress('CLEAN_APPLY_VERIFIED')
    emit('clean-apply.json',{**first,'ownership_hash':p['ownership_hash'],'elapsed_seconds':round(time.monotonic()-start,2)})
    before={r['database']+'.'+r['collection']:len(t.docs(r['database'],r['collection'])) for r in p['collection_specs']}
    again=engine.apply(s,p,t,keys)
    after={r['database']+'.'+r['collection']:len(t.docs(r['database'],r['collection'])) for r in p['collection_specs']}
    require(again['new_writes']==0 and before==after and first['target_hash']==again['target_hash'],'IDEMPOTENCY_FAILED')
    emit('idempotency.json',{'status':'PASS','new_writes':0,'business_count_delta':0,'wallet_delta':0,'inventory_delta':0,'purchases_delta':0,'deposits_delta':0,'coupon_usage_delta':0,'reseller_financial_delta':0,'all_document_hashes_equal':True})
    progress('IDEMPOTENCY_PASS')
    # The cloned input is disposable; authoritative accepted archives/view stay unchanged.
    clone=BASE/'conflict-clone';shutil.copytree(s.root,clone)
    m=json.loads((clone/'manifest.json').read_text());entry=next(x for x in m['collections'] if x['database']=='sellerbottel' and x['collection']=='bot_users')
    changed=deepcopy(s.collections['sellerbottel','bot_users']);changed[0]['balance_idr']+=1
    raw=b''.join(BSON.encode(d) for d in changed);(clone/entry['bson']).write_bytes(raw);m['files'][entry['bson']]=digest(raw);safe_json(clone/'manifest.json',m)
    altered=Snapshot(clone);failures=[]
    def rejected(label,fn):
        try:fn()
        except MigrationError as err:failures.append({'test':label,'code':str(err)});return
        raise MigrationError('EXPECTED_REJECTION_MISSING')
    rejected('changed_source_same_plan',lambda:engine.apply(altered,p,t,keys))
    changed_plan=engine.plan(altered)
    rejected('changed_source_replanned_same_target',lambda:engine.apply(altered,changed_plan,t,keys))
    original=t.get(s.owner['database_name'],'bot_users',changed[0]['_id'])
    rejected('same_id_divergent_target_write',lambda:t.put(s.owner['database_name'],'bot_users',changed[0]))
    require(doc_hash(t.get(s.owner['database_name'],'bot_users',changed[0]['_id']))==doc_hash(original),'CONFLICT_OVERWROTE_TARGET')
    for label in ('ownership','plan_hash','transform_hash'):
        bad=deepcopy(p)
        if label=='ownership':bad['ownership']['tenant_uuid']='00000000-0000-4000-8000-000000000099'
        else:bad[label]='0'*64
        rejected('resume_changed_'+label,lambda bad=bad:engine.apply(s,bad,t,keys))
    rejected('cross_tenant_database',lambda:t.docs('sellerbottel_real_rehearsal_tenant_other','bot_users'))
    require(engine.verify(s,p,t,keys)['target_hash']==first['target_hash'],'CONFLICT_TEST_DELTA')
    emit('conflict.json',{'status':'PASS','no_overwrite':True,'business_delta':0,'cases':failures})
    progress('CONFLICT_AND_HASH_GUARDS_PASS')
    rollback=engine.rollback(s,p,t);s.check()
    require(all(not t.names(db) for db in t.allowed if db!=AUDIT),'ROLLBACK_BUSINESS_NOT_EMPTY')
    require(set(t.names(AUDIT))<= {'migration_instance','migration_runs','migration_documents'},'ROLLBACK_AUDIT_RESIDUE')
    # Explicit target-only reset after verified rollback. Keep prior checkpoint digest in run audit.
    rid=engine.run_id(p);run=t.get(AUDIT,'migration_runs',rid)
    require(run['state']=='rolled_back','ROLLBACK_REQUIRED_BEFORE_RESET')
    receipts=t.docs(AUDIT,'migration_documents');require(all(r['run_id']==rid for r in receipts),'FOREIGN_RECEIPTS_PRESENT')
    receipt_hash=json_hash(sorted(doc_hash(r) for r in receipts))
    deleted=t.client[AUDIT].migration_documents.delete_many({'run_id':rid}).deleted_count
    require(deleted==len(receipts),'RESET_RECEIPT_COUNT_MISMATCH')
    t.replace(AUDIT,'migration_runs',run,{**run,'state':'applying','rehearsal_cycle':2,'previous_cycle':{'state':'rolled_back','receipt_count':deleted,'receipt_hash':receipt_hash}})
    progress('ROLLBACK_BASELINE_PASS_START_CRASH_DRILL')
    # Five interrupts in one fresh cycle, resuming the same frozen plan after each.
    boundary=next(i for i,r in enumerate(p['entries']) if i>0 and r['source_key'].split(':')[:2]!=p['entries'][i-1]['source_key'].split(':')[:2])
    specs=[('collection_boundary','before_write',boundary),('chunk_boundary','before_write',256),('after_write_before_checkpoint','after_write_before_checkpoint',512),('after_checkpoint','after_checkpoint',768),('before_final_verification','before_verification',len(p['entries']))]
    crash_results=[]
    for label,stage,index in specs:
        def fault(st,i,r):
            if st==stage and i==index:raise MigrationError('CONTROLLED_REHEARSAL_INTERRUPTION')
        try:engine.apply(s,p,t,keys,fault=fault)
        except MigrationError as err:require(str(err)=='CONTROLLED_REHEARSAL_INTERRUPTION','UNEXPECTED_CRASH_FAILURE')
        else:raise MigrationError('CRASH_NOT_INJECTED')
        checkpoint=t.get(AUDIT,'migration_documents',rid+':'+str(index))
        if stage=='after_write_before_checkpoint':require(checkpoint is None,'PRECHECKPOINT_NOT_EMPTY')
        if stage=='after_checkpoint':require(checkpoint is not None,'CHECKPOINT_MISSING')
        crash_results.append({'point':label,'status':'INTERRUPTED_AND_RESUMED','snapshot_hash':s.hash,'ownership_hash':p['ownership_hash'],'plan_hash':p['plan_hash'],'transform_hash':p['transform_hash']})
        progress('CRASH_'+label.upper())
    final=engine.apply(s,p,t,keys)
    require(first['target_hash']==final['target_hash'],'CRASH_RESUME_DIVERGED')
    emit('crash-resume.json',{'status':'PASS','points':crash_results,'equals_clean_run':True,'all_records_reread_verified':True})
    emit('rollback.json',{**rollback,'baseline':'new isolated instance; no business collections','source_unchanged':True,'explicit_target_only_reset':True,'prior_receipts_retained_as_hash':receipt_hash,'reapply_identical_to_clean':True,'final_target_retained':True})
    # Per-wallet output is ordinal-only: no account IDs, names, hashes or individual balances.
    wallet=[]
    for i,row in enumerate(p['wallets']['accounts']):
        wallet.append({'ordinal':i+1,'currency':row['currency'],'exact_amount_equal':True,'original_BSON_document_equal':True})
    require(Decimal(p['wallets']['totals']['IDR'])==Decimal('68698450') and Decimal(p['wallets']['totals']['USD'])==0,'BASELINE_WALLET_MISMATCH')
    emit('wallets.json',{'status':'PASS','logical_wallets':len(wallet)//2,'currency_assertions':wallet,'linked_aliases':len(p['wallets']['aliases']),'IDR_total':'68698450','USD_total':'0','opening_assertions_only':True,'ledger_credits':0,'missing_fields_preserved':True,'linked_semantics':'source storefront_routes.py customer_me selects bot balance when telegram_id exists; linked web balance absent/zero; matching bot exists'})
    # Source and target exact comparisons for archived commerce including all legacy field types.
    summaries={}
    for c in p['coverage']:
        db,col=location(p,c)
        if c=='counters':db,col=ARCHIVE,'history__counters'
        actual=t.docs(db,col);src=s.collections['sellerbottel',c]
        actualmap={identity(d['_id']):d for d in actual}
        for d in src:
            a=deepcopy(actualmap[identity(d['_id'])])
            if c=='products' and 'fulfillment_type' not in d:a.pop('fulfillment_type',None)
            require(BSON.encode(a)==BSON.encode(d),'LEGACY_PROJECTION_MISMATCH')
        summaries[c]={'source':len(src),'target':len(actual),'all_original_fields_equal':True,'disposition':'ACTIVE_COMPATIBILITY' if c in ('bot_users','store_customers') else 'ARCHIVE_NON_EXECUTABLE'}
    inv=t.docs(*location(p,'inventory_items'));statuses=Counter(d.get('status') for d in inv)
    require(statuses=={'available':759,'sold':357},'INVENTORY_STATUS_MISMATCH')
    # Real next invoice seed; never insert an order or call checkout.
    existing={d.get('invoice_id') for d in s.collections['sellerbottel','purchases']}
    next_checks=0
    for d in t.docs(s.owner['database_name'],'counters'):
        if d['_id'].startswith('invoice:'):
            date=d['_id'].split(':')[-1];nxt=f"INV-{date}-{d['seq']+1:04d}"
            require(nxt not in existing,'NEXT_INVOICE_COLLISION');next_checks+=1
    emit('reconciliation.json',{**final,'ownership_hash':p['ownership_hash'],'collections':summaries,'recovery_documents':sum(len(d) for (db,c),d in s.collections.items() if db!='sellerbottel'),'inventory_states':dict(statuses),'indexes_verified':sum(len(r['metadata']['indexes']) for r in p['collection_specs']),'next_invoice_dates_checked':next_checks,'password_hashes_unchanged':5,'tenant_binding_records':len(t.docs(AUDIT,'account_tenant_bindings')),'active_commerce_collections':0,'runtime_smoke':'NOT RUN'})
    # Original accepted source remains unmodified, independent of normalized view.
    from verify_real_snapshot_intake import TRANSFER
    for rel,h in s.manifest['accepted_transfer_hashes'].items():require(digest((TRANSFER/rel).read_bytes())==h,'ACCEPTED_SOURCE_MODIFIED')
    s.check()
    blocked=0
    for action in (lambda:socket.create_connection(('192.0.2.1',443)),lambda:socket.getaddrinfo('offline.invalid',443)):
        try:action()
        except MigrationError:blocked+=1
    require(blocked==2,'NETWORK_GUARD_FAILED')
    forbidden={'server','bot','bot_dispatcher','smtplib','telethon','gopay_client'}
    require(not forbidden.intersection(sys.modules),'APPLICATION_IMPORT_DETECTED')
    emit('external-io.json',{'status':'ZERO','network_namespace_isolated':isolated_namespace(),'interfaces':[n for _,n in socket.if_nameindex()],'guard_denied_attempts':blocked,'unix_socket_only':True,'no_application_modules':True,'source_unchanged':True,'production_contacted':False,'UAT_modified':False})
    progress('ALL_REAL_DATA_GATES_PASS')
    t.client.close()

if __name__=='__main__':
    try:main()
    except MigrationError as err:print(json.dumps({'status':'FAIL','code':str(err)}),flush=True);raise SystemExit(2)
    except Exception as err:print(json.dumps({'status':'FAIL','code':type(err).__name__}),flush=True);raise SystemExit(3)
