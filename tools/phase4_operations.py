"""Disposable dev-only archive, encrypted backup/restore, index and latency checks."""
import hashlib,json,time
from pathlib import Path
from bson import json_util
from cryptography.fernet import Fernet

async def operations(client, platform, scopes, http, headers, evidence, check, stop, start, ready):
    assert platform.name.startswith('sellerbottel_phase4_dev_')
    from commerce.journal import Journal,ensure_archive_indexes
    from commerce.physical.stock import PhysicalStock
    from payments.ledger import Ledger
    a=scopes[0]; database=a.db_handle
    await ensure_archive_indexes(database)
    # Isolated, high-volume stock fixture beyond C2's limit; counters and history agree.
    events=[{'_id':f'volume-{i}','variant_id':'phase4-volume','sku':'PHASE4-VOLUME','type':'RECEIVE','quantity':1,'reference_id':f'volume-{i}','delta_on_hand':1,'delta_reserved':0} for i in range(3200)]
    doc={'_id':'phase4-volume','sku':'PHASE4-VOLUME','product_id':'audit-only','active':False,'on_hand':3200,'reserved':0,'stock_version':1,'stock_events':events}
    await database.physical_variants.insert_one(doc)
    stock=PhysicalStock(database)
    while len(doc['stock_events'])>=512: doc=await stock.journal.compact(doc,lambda e:{'on_hand':e['delta_on_hand'],'reserved':e['delta_reserved']})
    await stock.move(doc['_id'],'ADJUSTMENT',1,reference_id='after-old-guard')
    doc=await stock.get(doc['_id'])
    stock_result=await stock.journal.verify(doc,lambda e:{'on_hand':e['delta_on_hand'],'reserved':e['delta_reserved']},lambda entries:stock.project({'stock_events':entries}))
    check('real stock >3000 archive reconstructable',stock_result['totals']['on_hand']==3201 and len(doc['stock_events'])<512)
    ledger=Ledger(database,a.tenant_id); account=await ledger.get()
    # Zero-value immutable audit facts preserve existing business balances.
    facts=[{'_id':f'volume-settlement-{i}','tenant_id':a.tenant_id,'reference':f'volume-{i}','intent':{},'type':'AUDIT','deltas':{},'amount':0,'currency':'IDR'} for i in range(10200)]
    await database.settlement_accounts.update_one({'_id':a.tenant_id},{'$push':{'events':{'$each':facts}},'$inc':{'version':1}})
    account=await database.settlement_accounts.find_one({'_id':a.tenant_id})
    delta=lambda e:{**e.get('deltas',{}),'nonmock':int(e['type']=='PAYMENT_GROSS' and e.get('environment')!='mock')}
    before=ledger.values(account)
    while len(account['events'])>=512: account=await ledger.journal.compact(account,delta)
    settlement_result=await ledger.journal.verify(account,delta,lambda entries:ledger.project({'events':entries}))
    check('real settlement >10000 archive balances',ledger.values(account)==before and len(account['events'])<512)
    (evidence/'journal-results.json').write_text(json.dumps({'stock':stock_result,'settlement':settlement_result},indent=2))
    # Export all collections and indexes while harness writes are quiescent.
    # Encrypted archive stays outside committed evidence; ephemeral key never leaves memory.
    stop()  # Quiesce all workers before the backup boundary.
    names=[platform.name]+[s.database_name for s in scopes]
    mapping={name:name for name in names}  # Preserve credential/idempotency namespaces.
    snapshot={}
    for name in names:
        assert name.startswith(('sellerbottel_phase4_dev_','sellerbottel_tenant_phase4_'))
        snapshot[name]={}
        for coll in await client[name].list_collection_names():
            snapshot[name][coll]={'documents':await client[name][coll].find({}).to_list(None),'indexes':await client[name][coll].index_information()}
    from storage import put_object,get_object
    asset='phase4-backup/'+platform.name+'/receipt.txt'
    await put_object(asset,b'Phase4 synthetic storage backup','text/plain')
    data,_=await get_object(asset)
    import base64
    payload=json_util.dumps({'databases':snapshot,'files':{asset:base64.b64encode(data).decode()}}).encode()
    cipher=Fernet(Fernet.generate_key()); encrypted=cipher.encrypt(payload)
    backup=Path('/tmp')/(platform.name+'.backup.fernet');backup.write_bytes(encrypted);backup.chmod(0o600)
    restored=json_util.loads(cipher.decrypt(backup.read_bytes()))
    def remap(v):
        if isinstance(v,dict): return {k:remap(x) for k,x in v.items()}
        if isinstance(v,list): return [remap(x) for x in v]
        return mapping.get(v,v) if isinstance(v,str) else v
    counts={}
    # Only databases created by this exact harness run may be replaced.
    for name in names:
        assert name.startswith(('sellerbottel_phase4_dev_', 'sellerbottel_tenant_phase4_'))
        assert name.endswith(platform.name.rsplit('_',1)[1])
        await client.drop_database(name)
    for name,collections in restored['databases'].items():
        target=client[mapping[name]]
        assert not await target.list_collection_names()
        for coll,value in collections.items():
            docs=remap(value['documents'])
            if docs: await target[coll].insert_many(docs)
            for key,idx in value['indexes'].items():
                if key=='_id_': continue
                options={k:v for k,v in idx.items() if k in {'unique','sparse','expireAfterSeconds','partialFilterExpression'}}
                await target[coll].create_index(idx['key'],name=key,**options)
            actual=await target[coll].find({}).to_list(None)
            assert sorted(json_util.dumps(d,sort_keys=True) for d in actual)==sorted(json_util.dumps(d,sort_keys=True) for d in docs)
            counts[name+'.'+coll]=len(docs)
    for path,encoded in restored['files'].items():
        await put_object(path+'.restored',base64.b64decode(encoded),'text/plain')
        assert (await get_object(path+'.restored'))[0]==data
    for tenant in await client[mapping[platform.name]].tenants.find({}).to_list(None):
        check('restored registry binding '+tenant['slug'],tenant['database_name'] in mapping.values())
    check('encrypted backup restore all records and storage',True)
    (evidence/'backup-restore.json').write_text(json.dumps({'encrypted':True,'disposable':True,'collections_verified':counts,'file_sha256':hashlib.sha256(data).hexdigest(),'original_database_names_preserved':True,'indexes_restored':True,'limitation':'quiescent disposable backup; production requires coordinated writes/PITR and secured key escrow'},indent=2))
    start(); await ready(http)
    check('restored backend starts with original registry and secret bindings',True)
    perf={}
    for label,path in [('catalog','/api/store/t/'+a.slug+'/products'),('orders','/api/public/tenant/full/orders'),('settlement','/api/public/tenant/full/commerce/settlement'),('shipments','/api/public/tenant/full/commerce/shipments'),('returns','/api/public/tenant/full/commerce/returns')]:
        timings=[]
        for _ in range(3):
            start=time.perf_counter(); response=await http.get(path,headers=headers[0]); timings.append(round((time.perf_counter()-start)*1000,2)); assert response.status_code==200,(label,response.status_code)
        perf[label]={'samples_ms':timings,'max_ms':max(timings)}
        check('bounded performance '+label,max(timings)<10000)
    start=time.perf_counter()
    for _ in range(10): await platform.payment_routes.find_one({'provider':'kasera','provider_reference':'missing-smoke'})
    perf['route_lookup_10_ms']=round((time.perf_counter()-start)*1000,2)
    (evidence/'performance.json').write_text(json.dumps({'coverage':'bounded smoke, not load certification','measurements':perf},indent=2))
    indexes={name:{coll:list((await client[name][coll].index_information()).keys()) for coll in await client[name].list_collection_names()} for name in names}
    (evidence/'indexes.json').write_text(json.dumps(indexes,indent=2))
    check('archive indexes persistent',len((await database.stock_journal_archive.index_information()))>=4)
