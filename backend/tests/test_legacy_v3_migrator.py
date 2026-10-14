"""No application startup, providers or real secrets; injected migration target only."""
import sys,json,socket
from pathlib import Path
from copy import deepcopy
import pytest
from bson import BSON,Int64,ObjectId
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from legacy_migration.fixture import create_fixture
from legacy_migration.snapshot import Snapshot,COLLECTIONS
from legacy_migration.target import MemoryTarget
from legacy_migration.crypto import OfflineKeys
from legacy_migration import engine
from legacy_migration.codec import doc_hash,digest,identity,safe_json
from legacy_migration.safety import MigrationError,allowed_databases,guard_environment,block_network

@pytest.fixture
def rehearsal(tmp_path):
    snap=create_fixture(tmp_path/'source',tmp_path/'keys.json',small=True)
    return snap,engine.plan(snap),MemoryTarget(snap.owner),OfflineKeys(tmp_path/'keys.json')

def rewrite_manifest(snap,fn):
    m=json.loads((snap.root/'manifest.json').read_text());fn(m);safe_json(snap.root/'manifest.json',m)
    return Snapshot(snap.root)


def test_47_coverage_and_empty_collections(rehearsal):
    s,p,t,k=rehearsal
    assert set(p['coverage'])==set(COLLECTIONS) and len(COLLECTIONS)==47
    assert p['coverage']['coupons']==0
    assert len(s.metadata)==53


def test_unknown_collection_fails(rehearsal):
    s,*_=rehearsal
    with pytest.raises(MigrationError,match='UNKNOWN_COLLECTION'):
        rewrite_manifest(s,lambda m:m['collections'][0].update(collection='surprise'))


def test_unknown_critical_field_fails(rehearsal):
    s,*_=rehearsal
    s=rewrite_manifest(s,lambda m:m['schema_decisions']['sellerbottel.settings'].pop('mixed.long'))
    with pytest.raises(MigrationError,match='UNKNOWN_CRITICAL'):engine.plan(s)


def test_raw_bson_types_null_missing_and_unknown_fields(rehearsal):
    s,p,t,k=rehearsal;engine.apply(s,p,t,k)
    db=s.owner['database_name'];d=t.docs(db,'settings')[0];source=s.collections[('sellerbottel','settings')][0]
    assert BSON.encode(d)==BSON.encode(source)
    assert isinstance(d['mixed']['long'],Int64) and type(d['mixed']['int']) is int
    assert isinstance(d['mixed']['oid'],ObjectId) and isinstance(d['mixed']['string_id'],str)
    assert d['unknown_legacy_field']['nested'] is None and 'missing' not in d
    raw=t.get('sellerbottel_migration_archive','raw_documents','sellerbottel:settings:'+identity('main'))['raw']
    assert bytes(raw)==s.raw[('sellerbottel','settings')][0]


def test_wallet_alias_and_unrelated_accounts(rehearsal):
    s,p,t,k=rehearsal;engine.apply(s,p,t,k)
    assert p['wallets']['totals']['IDR']=='70623450'
    assert len(p['wallets']['aliases'])==1
    ids={r['wallet_id'] for r in p['wallets']['accounts']};assert len(ids)==3
    assert not t.docs(s.owner['database_name'],'wallet_ledger')

@pytest.mark.parametrize('collection',['deposits','purchases','balance_adjustments','reseller_payouts','promo_coupon_usage','processed_updates','processed_updates_bot2','reseller_updates'])
def test_historical_copy_no_replay_or_reset(rehearsal,collection):
    s,p,t,k=rehearsal;first=engine.apply(s,p,t,k);second=engine.apply(s,p,t,k)
    assert second['new_writes']==0 and first['target_hash']==second['target_hash']
    assert t.docs(s.owner['database_name'],collection)==s.collections[('sellerbottel',collection)]
    assert engine.wallets({c:t.docs(s.owner['database_name'],c) for c in ('bot_users','store_customers')})==p['wallets']


def test_ciphertext_decrypt_sold_and_orphan_preservation(rehearsal):
    s,p,t,k=rehearsal;engine.apply(s,p,t,k);db=s.owner['database_name']
    assert t.docs(db,'inventory_items')==s.collections[('sellerbottel','inventory_items')]
    assert k.verify(s.collections)['inventory']==2
    product=t.get(db,'products','missing-0');assert product['active'] is False
    assert t.get(db,'products','missing-1') is None
    assert t.get(db,'_migration_hold','execution')['runtime_release_allowed'] is False
    assert p['exceptions']['inventory_orphan']==2
    assert p['exceptions']['reseller_commission_orphan']==2


def test_wrong_crypto_key_is_fail_closed(rehearsal,tmp_path):
    from cryptography.fernet import Fernet
    s,p,t,k=rehearsal;safe_json(tmp_path/'wrong.json',{'INVENTORY_ENCRYPTION_KEY':Fernet.generate_key().decode()})
    with pytest.raises(MigrationError,match='DECRYPT_FAILED'):engine.apply(s,p,t,OfflineKeys(tmp_path/'wrong.json'))
    assert not t.data


def test_recovery_requires_provenance(rehearsal):
    s,*_=rehearsal;s=rewrite_manifest(s,lambda m:next(iter(m['recovery_decisions'].values())).update(source_hash='wrong'))
    with pytest.raises(MigrationError,match='RECOVERY_PROVENANCE'):engine.plan(s)


def test_counter_source_invoice_and_target_highwater(rehearsal):
    s,p,t,k=rehearsal
    s=rewrite_manifest(s,lambda m:m.update(approved_target_counters=[{'_id':'invoice:20261009','seq':150}]))
    p=engine.plan(s);t=MemoryTarget(s.owner);t.put(s.owner['database_name'],'counters',{'_id':'invoice:20261009','seq':150})
    engine.apply(s,p,t,k);assert t.get(s.owner['database_name'],'counters','invoice:20261009')['seq']==150
    engine.rollback(s,p,t);assert t.get(s.owner['database_name'],'counters','invoice:20261009')['seq']==150

@pytest.mark.parametrize('boundary',[1,10,100])
def test_crash_resume_after_unacknowledged_write(rehearsal,boundary):
    s,p,t,k=rehearsal
    with pytest.raises(MigrationError,match='INJECTED_CRASH'):engine.apply(s,p,t,k,crash_after=boundary)
    engine.apply(s,p,t,k);assert engine.verify(s,p,t,k)['status']=='PASS'
    assert engine.apply(s,p,t,k)['new_writes']==0


def test_changed_plan_or_transform_rejected(rehearsal):
    s,p,t,k=rehearsal;p=deepcopy(p);p['transform_hash']='wrong'
    with pytest.raises(MigrationError,match='TRANSFORM_HASH'):engine.apply(s,p,t,k)


def test_changed_source_same_id_and_target_conflict(rehearsal):
    s,p,t,k=rehearsal;engine.apply(s,p,t,k)
    d=t.get(s.owner['database_name'],'inventory_items','inventory-0');t.replace(s.owner['database_name'],'inventory_items',d,{**d,'status':'sold'})
    with pytest.raises(MigrationError,match='CONFLICT'):engine.apply(s,p,t,k)
    path=s.root/'sellerbottel/settings.bson';path.write_bytes(path.read_bytes()+b'x')
    with pytest.raises(MigrationError,match='DRIFT'):s.check()


def test_cross_tenant_and_rollback_target_only(rehearsal):
    s,p,t,k=rehearsal
    with pytest.raises(MigrationError,match='DATABASE_REJECTED'):t.docs('sellerbottel_tenant_other','bot_users')
    engine.apply(s,p,t,k);engine.rollback(s,p,t)
    assert not t.names(s.owner['database_name']) and not t.names('sellerbottel_migration_platform')
    assert t.docs('sellerbottel_migration_audit','migration_runs')[0]['state']=='rolled_back'
    assert Snapshot(s.root).hash==s.hash

@pytest.mark.parametrize('name',['sellerbottel','sellerbottel_uat_platform','sellerbottel_tenant_digital_demo'])
def test_production_uat_targets_rejected(rehearsal,name):
    s,*_=rehearsal;o=deepcopy(s.owner);o['database_name']=name
    with pytest.raises(MigrationError):allowed_databases(o)


def test_no_live_env_or_credentials(rehearsal,monkeypatch,tmp_path):
    monkeypatch.setenv('TELEGRAM_TOKEN','SYNTHETIC-FORBIDDEN')
    with pytest.raises(MigrationError,match='ENV_REJECTED'):guard_environment()
    safe_json(tmp_path/'keys.json',{'TELEGRAM_TOKEN':'SYNTHETIC-FORBIDDEN'})
    with pytest.raises(MigrationError,match='LIVE_KEY'):OfflineKeys(tmp_path/'keys.json')


def test_no_external_adapter_network_or_plaintext_logs(rehearsal,monkeypatch,capsys):
    s,p,t,k=rehearsal
    # Exercise defense-in-depth guard in an automatically restored patch scope.
    with monkeypatch.context() as m:
        m.setattr(socket.socket,'connect',socket.socket.connect);m.setattr(socket.socket,'connect_ex',socket.socket.connect_ex)
        m.setattr(socket,'create_connection',socket.create_connection);m.setattr(socket,'getaddrinfo',socket.getaddrinfo)
        block_network()
        for port in (443,25,587,27017,27020):
            with socket.socket() as sock:
                with pytest.raises(MigrationError,match='EXTERNAL_IO_BLOCKED'):sock.connect(('127.0.0.1',port))
        engine.apply(s,p,t,k)
    text=capsys.readouterr();assert not text.out and not text.err


def test_rollback_refuses_business_changes(rehearsal):
    s,p,t,k=rehearsal;engine.apply(s,p,t,k)
    d=t.get(s.owner['database_name'],'bot_users','bot-0');t.replace(s.owner['database_name'],'bot_users',d,{**d,'balance_idr':1})
    with pytest.raises(MigrationError,match='CONFLICT'):engine.rollback(s,p,t)
    assert t.get(s.owner['database_name'],'bot_users','bot-0')['balance_idr']==1


def test_pending_payout_and_sold_state_remain_held(rehearsal):
    s,p,t,k=rehearsal;engine.apply(s,p,t,k);db=s.owner['database_name']
    assert t.docs(db,'inventory_items')[-1]['status']=='sold'
    assert t.docs(db,'reseller_commissions')[-1]['status']=='pending_payout'
    assert p['exceptions']['reseller_financial_hold']==1


def test_replanned_source_cannot_resume_prior_run(rehearsal):
    s,p,t,k=rehearsal
    with pytest.raises(MigrationError):engine.apply(s,p,t,k,crash_after=1)
    s2=rewrite_manifest(s,lambda m:m.update(fence_marker='changed-fence'))
    p2=engine.plan(s2)
    with pytest.raises(MigrationError,match='CHANGED_PLAN'):engine.apply(s2,p2,t,k)


def test_source_document_same_id_changed_hash_conflicts(rehearsal):
    s,p,t,k=rehearsal;engine.apply(s,p,t,k)
    path=s.root/'sellerbottel/settings.bson';doc=BSON(path.read_bytes()).decode();doc['gopay_qr_timeout_minutes']=16;path.write_bytes(BSON.encode(doc))
    s2=rewrite_manifest(s,lambda m:m['files'].update({'sellerbottel/settings.bson':digest(path.read_bytes())}))
    with pytest.raises(MigrationError,match='CHANGED_PLAN'):engine.apply(s2,engine.plan(s2),t,k)


def test_linked_wallet_nonzero_blocks_before_writes(rehearsal):
    s,p,t,k=rehearsal
    docs=deepcopy({c:s.collections[('sellerbottel',c)] for c in ('bot_users','store_customers')});docs['store_customers'][0]['balance_idr']=1
    with pytest.raises(MigrationError,match='LINKED_WALLET_NONZERO'):engine.wallets(docs)


def test_offline_keys_permission_required(rehearsal,tmp_path):
    path=tmp_path/'bad.json';path.write_text('{}');path.chmod(0o644)
    with pytest.raises(MigrationError,match='0600'):OfflineKeys(path)


def test_synthetic_tenant_b_cannot_read_or_apply_tenant_a(rehearsal):
    s,p,a,k=rehearsal;engine.apply(s,p,a,k)
    owner=deepcopy(s.owner);owner.update(tenant_slug='synthetic-b',database_name='sellerbottel_migration_legacy_synthetic_b',tenant_uuid='00000000-0000-4000-8000-000000000002')
    b=MemoryTarget(owner);b.data=a.data
    assert b.docs(owner['database_name'],'bot_users')==[]
    with pytest.raises(MigrationError,match='DATABASE_REJECTED'):b.docs(s.owner['database_name'],'inventory_items')
    with pytest.raises(MigrationError,match='TARGET_OWNERSHIP_MISMATCH'):engine.apply(s,p,b,k)


def test_unapproved_nonempty_target_denied(rehearsal):
    s,p,t,k=rehearsal;t.put(s.owner['database_name'],'products',{'_id':'foreign-product'})
    with pytest.raises(MigrationError,match='TARGET_NOT_EMPTY'):engine.apply(s,p,t,k)


def test_preexisting_empty_unapproved_collection_rejected(rehearsal):
    s,p,t,k=rehearsal;t.data[(s.owner['database_name'],'unknown_empty')]={}
    with pytest.raises(MigrationError,match='TARGET_NOT_EMPTY'):engine.apply(s,p,t,k)


def test_invoice_suffix_can_raise_low_source_counter(rehearsal):
    s,p,t,k=rehearsal
    from legacy_migration.codec import bson_records
    path=s.root/'sellerbottel/counters.bson';docs=[d for _,d in bson_records(path.read_bytes())];docs[0]['seq']=0
    path.write_bytes(b''.join(BSON.encode(d) for d in docs))
    s=rewrite_manifest(s,lambda m:m['files'].update({'sellerbottel/counters.bson':digest(path.read_bytes())}))
    p=engine.plan(s);engine.apply(s,p,t,k)
    assert t.get(s.owner['database_name'],'counters','invoice:20261009')['seq']==2
