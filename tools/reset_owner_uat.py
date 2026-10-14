"""Explicit demo-only reset. Stop UAT backend/dispatcher before --execute."""
import argparse,asyncio,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SLUGS={'fashion-demo','digital-demo'}
CONFIRM='RESET SELLERBOTTEL UAT DEMOS'

def validate_targets(config,manifest):
    if config.get('ENVIRONMENT')!='development' or config.get('SELLERBOTTEL_UAT')!='true' or config.get('PLATFORM_DB_NAME')!='sellerbottel_uat_platform' or not config.get('MONGO_URL','').startswith('mongodb://127.0.0.1:27020/'):
        raise ValueError('Unsafe UAT environment')
    if len(manifest)!=2 or {row['slug'] for row in manifest}!=SLUGS:
        raise ValueError('Only the two fixed demo tenants may be reset')
    from uuid import UUID
    for row in manifest:
        UUID(row['tenant_id'])
        if row['database_name']!='sellerbottel_tenant_'+row['slug'].replace('-','_'):
            raise ValueError('Unexpected demo namespace')
    return manifest

async def main(args):
    from uat_runtime import configure,PRIVATE
    config=configure();manifest=validate_targets(config,json.loads((PRIVATE/'demo-manifest.json').read_text()))
    from db import client,platform_db
    platform=platform_db()
    for row in manifest:
        tenant=await platform.tenants.find_one({'_id':row['tenant_id'],'slug':row['slug'],'database_name':row['database_name']})
        if not tenant:raise ValueError('Demo identity changed; refusing reset')
    if not args.execute:
        print(json.dumps({'mode':'DRY RUN','targets':manifest}));client.close();return
    if args.confirm!=CONFIRM:raise ValueError('Explicit confirmation required')
    for service in ['sellerbottel-uat-backend','sellerbottel-uat-dispatcher']:
        state=subprocess.run(['systemctl','is-active',service],capture_output=True,text=True).stdout.strip()
        if state not in {'inactive','failed'}:raise ValueError('Stop UAT services first')
    # Platform identities, credentials, fresh tenants and other databases survive.
    for row in manifest:
        routes=await platform.payment_routes.find({'tenant_id':row['tenant_id'],'tenant_database':row['database_name']},{'_id':1}).to_list(None)
        await platform.payment_events.delete_many({'route_id':{'$in':[r['_id'] for r in routes]}})
        for collection in ['payment_routes','refund_operations','cancel_operations']:
            await platform[collection].delete_many({'tenant_id':row['tenant_id'],'tenant_database':row['database_name']})
        await client.drop_database(row['database_name'])
    from seed_owner_uat import main as seed
    await seed()
    print('Demo reset complete. Restart UAT backend and dispatcher.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');parser.add_argument('--confirm',default='');args=parser.parse_args()
    try:asyncio.run(main(args))
    except Exception as error:print(type(error).__name__+': reset stopped');raise SystemExit(1)
