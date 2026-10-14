"""Explicit accounts-only rehearsal projection. No application/runtime adapters."""
from copy import deepcopy
from bson import BSON, json_util
from .safety import PLATFORM, ARCHIVE, AUDIT, PROFILE, require
from .codec import doc_hash, identity, json_hash

ACTIVE = ('bot_users', 'store_customers')

def location(plan, collection):
    if collection in ACTIVE or collection == 'counters':
        return plan['ownership']['database_name'], collection
    return ARCHIVE, 'history__' + collection

def finalize_plan(snapshot, p):
    from .engine import unpack,pack
    require(PROFILE == 'offline-real', 'REAL_PROFILE_REQUIRED')
    require(not any(d.get('disposition')=='recovered' for d in snapshot.manifest['recovery_decisions'].values()),'REAL_RECOVERY_REQUIRES_SEPARATE_RELEASE')
    p['strategy']='accounts_active_history_archive'
    p['ownership_hash']=json_hash(snapshot.owner)
    for r in p['entries']:
        if r['source_key'].startswith('sellerbottel:') and r['rule'] not in ('archive_raw_bson','archive_metadata'):
            c=r['source_key'].split(':')[1]
            r['database'],r['collection']=location(p,c)
    def add(db,c,d,rule,source):
        p['entries'].append({'database':db,'collection':c,'id_hash':identity(d['_id']),'bson':pack(d),
                             'source_hash':doc_hash(d),'target_hash':doc_hash(d),'rule':rule,'reason':rule,'source_key':source})
    specs=[]
    for (db,c),docs in snapshot.collections.items():
        if db=='sellerbottel':
            target_db,target_col=location(p,c)
            if c=='counters':
                target_db,target_col=ARCHIVE,'history__counters'
                for d in docs:add(target_db,target_col,d,'unaltered_historical_counter',db+':'+c+':'+identity(d['_id']))
        else:
            target_db,target_col=ARCHIVE,'recovery__'+db.removeprefix('sellerbottel_')+'__'+c
            for d in docs:add(target_db,target_col,d,'separate_recovery_projection',db+':'+c+':'+identity(d['_id']))
        specs.append({'source_database':db,'source_collection':c,'database':target_db,'collection':target_col,'metadata':snapshot.metadata[(db,c)]})
    # Binding sidecars preserve raw account documents without injecting incompatible fields.
    for c in ACTIVE:
        for d in snapshot.collections['sellerbottel',c]:
            add(AUDIT,'account_tenant_bindings',{'_id':c+':'+identity(d['_id']), 'tenant_id':snapshot.owner['tenant_uuid'],
                'database_name':snapshot.owner['database_name'],'source_collection':c,'source_id_bson':BSON.encode({'_id':d['_id']}),
                'runtime_enabled':False},'exact_tenant_account_binding',c+':'+identity(d['_id']))
    # Future counter seed separate from the untouched historical counters in archive.
    specs.append({'source_database':'derived','source_collection':'counters','database':snapshot.owner['database_name'],
                  'collection':'counters','metadata':{'options':{},'indexes':[{'v':2,'key':{'_id':1},'name':'_id_'}]}})
    p['collection_specs']=specs
    keys=[(r['database'],r['collection'],r['id_hash']) for r in p['entries']]
    require(len(keys)==len(set(keys)),'DUPLICATE_PLAN_TARGET')


def normalize_indexes(indexes):
    return sorted([{**{k:v for k,v in d.items() if k not in ('ns','key')},'key':list(d['key'].items())} for d in indexes],key=lambda d:d['name'])


def install_indexes(target,p):
    from pymongo import IndexModel
    require(target.client.admin.command({'getParameter':1,'ttlMonitorEnabled':1})['ttlMonitorEnabled'] is False,'TTL_MUST_BE_DISABLED')
    for spec in p['collection_specs']:
        db,c=spec['database'],spec['collection'];require(db in target.allowed,'DATABASE_REJECTED')
        meta=json_util.loads(json_util.dumps(spec['metadata']))
        if c not in target.names(db):target.client[db].create_collection(c,**meta['options'])
        require(target.client[db][c].options()==meta['options'],'COLLECTION_OPTIONS_CONFLICT')
        models=[IndexModel(list(d['key'].items()),**{k:v for k,v in d.items() if k not in ('key','ns')}) for d in meta['indexes'] if d['name']!='_id_']
        if models:target.client[db][c].create_indexes(models)
        require(normalize_indexes(list(target.client[db][c].list_indexes()))==normalize_indexes(meta['indexes']),'INDEX_CONFLICT')


def verify_policy(snapshot,p,target):
    require(json_hash(snapshot.owner)==p['ownership_hash'],'OWNERSHIP_HASH_MISMATCH')
    require(set(target.names(snapshot.owner['database_name'])) <= set(ACTIVE)|{'counters','_migration_hold'},'COMMERCE_IN_ACTIVE_DATABASE')
    for spec in p['collection_specs']:
        coll=target.client[spec['database']][spec['collection']]
        require(spec['collection'] in target.names(spec['database']),'EMPTY_COLLECTION_MISSING')
        require(normalize_indexes(list(coll.list_indexes()))==normalize_indexes(spec['metadata']['indexes']),'INDEX_CONFLICT')
        require(coll.options()==spec['metadata']['options'],'COLLECTION_OPTIONS_CONFLICT')
    for c in ACTIVE:
        expected={identity(d['_id']):BSON.encode(d) for d in snapshot.collections['sellerbottel',c]}
        actual={identity(d['_id']):BSON.encode(d) for d in target.docs(*location(p,c))}
        require(actual==expected,'ACTIVE_ACCOUNT_TYPE_OR_VALUE_CHANGED')
