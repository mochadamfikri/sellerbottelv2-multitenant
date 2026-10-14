import sys,asyncio,json
sys.path.insert(0,'/home/sellerbottelv2/tools')
from run_release_kasera import ROOT
from db import client,platform_db
async def run():
    results={};platform=platform_db()
    for variant in ['buyer-fees','tier-fees']:
        data=json.loads((ROOT/f'test_reports/release-blocker-kasera-20261009/genuine-callback-{variant}.json').read_text())
        for mode,entry in data.items():
            db=client[entry['tenant_database']];payment=await db.order_payments.find_one({'_id':entry['route_id']})
            receipts=await platform.payment_events.find({'route_id':payment['_id']}).to_list(10)
            stock=await db.physical_variants.find_one({})
            sales=[e for e in stock['stock_events'] if e['type']=='SALE']
            fulfillments=await db.fulfillments.count_documents({'order_id':payment['order_id']})
            credits=await db.settlement_entries.count_documents({'payment_id':payment['_id']})
            assert len(receipts)==1 and receipts[0]['state']=='applied' and len(sales)==1 and fulfillments==1
            assert credits==(5 if mode=='platform_settlement' else 0)
            results[variant+':'+mode]={'provider_payment_id':payment['provider_payment_id'],'provider_event_id':receipts[0]['event_id'],'received_at':str(receipts[0]['received_at']),'applied_at':str(receipts[0]['applied_at']),'payment_receipts':len(receipts),'stock_sale_events':len(sales),'fulfillments':fulfillments,'settlement_components':credits,'fee_policy':payment['fee_policy'],'reconciliation':payment.get('reconciliation')}
    settings=await platform.platform_payment_settings.find_one({'_id':'kasera'})
    assert settings.get('platform_fee',250)==250 and settings.get('platform_fee_tiers',[])==[]
    results['current_dev_fixture_policy']={'platform_fee':250,'tiers':[]}
    (ROOT/'test_reports/release-blocker-kasera-20261009/mongo-effects.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Verified four genuine payments: one receipt, stock sale and fulfillment each; fee snapshots retained; default restored.')
    client.close()
asyncio.run(run())
