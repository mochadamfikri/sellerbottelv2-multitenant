"""Dev-only streaming journal verification/rebuild. Never loads .env."""
import argparse,asyncio,json,os,sys
from pathlib import Path
os.environ['PYTHON_DOTENV_DISABLED']='1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from motor.motor_asyncio import AsyncIOMotorClient
from commerce.journal import Journal,project_events,ensure_archive_indexes
async def run(args):
    assert args.database.startswith(('sellerbottel_phase4_dev_','sellerbottel_tenant_phase4_'))
    client=AsyncIOMotorClient('mongodb://127.0.0.1:27019/?serverSelectionTimeoutMS=2000');db=client[args.database]
    if args.repair or args.compact: await ensure_archive_indexes(db)
    results=[]
    for collection,field,version,archive,projection,delta in [
      ('physical_variants','stock_events','stock_version','stock_journal_archive','stock_movements',lambda e:{'on_hand':e.get('delta_on_hand',0),'reserved':e.get('delta_reserved',0)}),
      ('settlement_accounts','events','version','settlement_journal_archive','settlement_entries',lambda e:{**e.get('deltas',{}),'nonmock':int(e['type']=='PAYMENT_GROSS' and e.get('environment')!='mock')})]:
        j=Journal(db,collection,field,version,archive)
        async for doc in db[collection].find({}):
            if args.compact:
                while len(doc.get(field,[]))>=512:
                    changed=await j.compact(doc,delta)
                    doc=changed if changed is not None else await db[collection].find_one({'_id':doc['_id']})
            callback=(lambda entries:project_events(db[projection],entries)) if args.repair else None
            result=await j.verify(doc,delta,callback)
            if collection=='physical_variants':
                assert result['totals'].get('on_hand',0)==doc.get('on_hand',0) and result['totals'].get('reserved',0)==doc.get('reserved',0)
            results.append({'collection':collection,'owner_id':str(doc['_id']),**result})
    print(json.dumps({'database':args.database,'projection_repair':args.repair,'results':results}));client.close()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('database');p.add_argument('--repair',action='store_true');p.add_argument('--compact',action='store_true');asyncio.run(run(p.parse_args()))
