#!/usr/bin/env python3
"""Synthetic-only integration drill. Invoke in unshare --net; no live data input."""
import sys,json,socket,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from legacy_migration.safety import PRIVATE,require,guard_environment,block_network,isolated_namespace,MigrationError
from legacy_migration.snapshot import Snapshot
from legacy_migration.crypto import OfflineKeys
from legacy_migration.target import MongoTarget
from legacy_migration import engine
from legacy_migration.codec import safe_json

def main():
    guard_environment();require(isolated_namespace(),'ISOLATION_REQUIRED');block_network()
    s=Snapshot(PRIVATE/'synthetic-snapshot');require(s.manifest['source_type']=='synthetic','SYNTHETIC_ONLY')
    p=engine.plan(s);keys=OfflineKeys(PRIVATE/'offline-keys.json')
    instance=json.loads((PRIVATE/'instance.json').read_text())['instance_id'];t=MongoTarget(s.owner,instance)
    # Each scenario uses the exact frozen plan; verify then rollback independently.
    result={};safe_json(PRIVATE/'plan.json',p);safe_json(PRIVATE/'inventory.json',s.inventory())
    try:
        engine.apply(s,p,t,keys,crash_after=300)
        raise AssertionError('Crash injection did not fire')
    except MigrationError as exc:
        require(str(exc)=='INJECTED_CRASH_AFTER_WRITE_BEFORE_CHECKPOINT','UNEXPECTED_CRASH');result['injected_crash']='PASS'
    result['resume']=engine.apply(s,p,t,keys)
    result['rerun']=engine.apply(s,p,t,keys)
    require(result['rerun']['new_writes']==0,'RERUN_WRITES')
    result['verify']=engine.verify(s,p,t,keys)
    result['rollback']=engine.rollback(s,p,t)
    require(not t.names(s.owner['database_name']) and not t.names(s.owner['platform_database']),'BASELINE_NOT_EMPTY')
    result['source_unchanged']=Snapshot(s.root).hash==s.hash
    result['network_namespace']={'interfaces':[name for _,name in socket.if_nameindex()],'different_from_host':isolated_namespace()}
    denied=[]
    for host,port in [('149.154.167.220',443),('1.1.1.1',443),('127.0.0.1',25),('127.0.0.1',27020),('127.0.0.1',27017)]:
        with socket.socket() as sock:
            try:sock.connect((host,port))
            except MigrationError as exc:
                require(str(exc)=='EXTERNAL_IO_BLOCKED','UNEXPECTED_NETWORK_ERROR');denied.append(port)
            else:raise AssertionError('External network reachable')
    result['external_io']={'status':'ZERO','blocked_attempts':len(denied),'application_adapters_imported':any(n in sys.modules for n in ['server','tgapi','gopay_provider','smtplib','payments.providers.kasera'])}
    require(not result['external_io']['application_adapters_imported'],'APP_ADAPTER_IMPORTED')
    evidence=Path(__file__).resolve().parents[1]/'test_reports/legacy-v1-v3-migration-rehearsal-20261009'
    evidence.mkdir(parents=True,exist_ok=True)
    # Only synthetic census/metadata and aggregate results. Never write plan payloads or keys here.
    inventory=s.inventory()
    for name,data in [('reconciliation.json',result),('synthetic-manifest.json',{'source_type':'synthetic','snapshot_hash':s.hash,'plan_hash':p['plan_hash'],'transform_hash':p['transform_hash'],'counts':p['coverage']}),('field-type-census.json',inventory['field_type_census']),('index-options.json',inventory['index_options'])]:
        safe_json(evidence/name,data);(evidence/name).chmod(0o644)
    print(json.dumps({'synthetic_rehearsal':'PASS','main_documents':sum(p['coverage'].values()),'inventory_decrypted':result['verify']['decrypt']['inventory'],'idempotency':'PASS','crash_resume':'PASS','rollback':'PASS','external_io':'ZERO'}))

if __name__=='__main__':
    try:main()
    except MigrationError as exc:print(json.dumps({'status':'FAIL','code':str(exc)}));sys.exit(2)
    except Exception:print(json.dumps({'status':'FAIL','code':'UNEXPECTED_FAILURE_REDACTED'}));sys.exit(3)
