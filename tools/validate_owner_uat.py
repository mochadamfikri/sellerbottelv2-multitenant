"""Public HTTPS UAT checks. Genuine Kasera TEST callback only; no local event injection."""
import asyncio,json,secrets
from urllib.parse import urlsplit
from uat_runtime import configure,ROOT,PRIVATE
configure()
import httpx
from db import client,platform_db
REPORT=ROOT/'test_reports/full-development-uat-20261009/public-flow.json'
checks=[]
def check(name,ok,**details):
 checks.append({'check':name,'result':'PASS' if ok else 'FAIL',**details});REPORT.write_text(json.dumps(checks,indent=2)+'\n')
 print(name+': '+('PASS' if ok else 'FAIL'),flush=True)
 if not ok:raise AssertionError(name)
async def main():
 accounts=json.loads((PRIVATE/'credentials.json').read_text());platform=platform_db()
 async with httpx.AsyncClient(base_url='https://idseconnect.my.id',timeout=45) as root:
  r=await root.post('/api/auth/login',json=accounts['platform_owner']);check('Platform owner HTTPS login',r.status_code==200,status=r.status_code)
  r=await root.get('/api/v2/platform/payments/kasera/fee');check('Platform fee control',r.status_code==200)
  for path in ['/docs','/openapi.json','/api/internal/tls-ask?domain=digital-demo.idsestock.my.id']:
   check('Private route blocked '+path,(await root.get(path)).status_code==404)
  owners=[]
  for label,slug in [('a','fashion-demo'),('b','digital-demo')]:
   r=await root.post('/api/public/tenant/login',json=accounts['tenant_'+label]);check('Tenant login '+slug,r.status_code==200)
   owners.append({'Authorization':'Bearer '+r.json()['token']})
   r=await root.get('/api/public/tenant/full/products',headers=owners[-1]);check('Owner catalog '+slug,r.status_code==200 and len(r.json())>=3)
   r=await root.get('/api/public/host-config',params={'host':slug+'.idsestock.my.id'});check('Panel host binding '+slug,r.json().get('tenant_slug')==slug)
  for state in ['suspended','disabled']:
   await platform.tenants.update_one({'slug':'fashion-demo'},{'$set':{'status':state}})
   try:
    check('A protected '+state,(await root.get('/api/public/tenant/full/products',headers=owners[0])).status_code==403)
    check('B independent '+state,(await root.get('/api/public/tenant/full/products',headers=owners[1])).status_code==200)
   finally:await platform.tenants.update_one({'slug':'fashion-demo'},{'$set':{'status':'active'}})
  check('A reactivated',(await root.get('/api/public/tenant/full/products',headers=owners[0])).status_code==200)
  for label,slug in [('a','fashion-demo'),('b','digital-demo')]:
   async with httpx.AsyncClient(base_url='https://'+slug+'.idseconnect.my.id',timeout=45) as customer:
    r=await customer.post('/api/store/login',json=accounts['customer_'+label]);check('Customer login '+slug,r.status_code==200,status=r.status_code)
    check('Cross-host path mismatch '+slug,(await customer.get('/api/store/t/'+('digital-demo' if label=='a' else 'fashion-demo')+'/products')).status_code==400)
    tenant=await platform.tenants.find_one({'slug':slug});database=client[tenant['database_name']]
    variant=await database.physical_variants.find_one({'sku':'FASH-BLK-M' if label=='a' else 'DIG-BLK-M'})
    items=[{'pid':'gemini-demo','qty':1},{'pid':'vps-demo','qty':1},{'pid':'hoodie-demo','qty':1,'variant_id':variant['_id']}]
    quote=await customer.post('/api/store/quote',json={'items':items,'currency':'IDR'});check('Mixed cart quote '+slug,quote.status_code==200,status=quote.status_code)
    methods=await customer.get('/api/store/gateway/methods',params={'amount':int(quote.json()['total'])})
    fee=methods.json()['methods'][0]['fee_quote']
    check('Buyer fee visible '+slug,fee['total']>quote.json()['total'])
    body={'items':items,'currency':'IDR','payment_method':'gateway:qris','expected_gateway_total':fee['total'],'idempotency_key':'owner-uat-'+label,'shipping_address':{'recipient_name':'UAT Synthetic','phone':'088888888888','address_line_1':'Alamat demo UAT, tidak dikirim','district':'Demo','city':'Jakarta','province':'DKI Jakarta','postal_code':'12440'}}
    r=await customer.post('/api/store/checkout',json=body);check('Kasera TEST mixed checkout '+slug,r.status_code==200,status=r.status_code)
    order=r.json();oid=order['_id'];payment=await database.order_payments.find_one({'order_id':oid})
    parsed=urlsplit(payment['instructions']['checkout_url']);assert parsed.hostname=='pay.kasera.id'
    if payment['status']=='pending':
     r=await customer.post('https://pay.kasera.id/api/v1/checkout/'+parsed.path.split('/p/',1)[1]+'/simulate-payment',json={'outcome':'succeeded'})
     check('Provider TEST simulation '+slug,r.status_code==200)
    for _ in range(90):
     payment=await database.order_payments.find_one({'_id':payment['_id']})
     if payment['status']=='paid' and not payment.get('reconciliation'):break
     await asyncio.sleep(1)
    receipt=await platform.payment_events.find_one({'route_id':payment['_id'],'state':'applied'})
    check('Genuine callback '+slug,bool(receipt) and payment['status']=='paid' and not payment.get('reconciliation'),order_id=oid,payment_id=payment['_id'])
    entries=await database.settlement_entries.find({'payment_id':payment['_id']}).to_list(20)
    check('Five settlement components '+slug,len(entries)==5,components=[{'type':e['type'],'amount':e['amount']} for e in entries])
    fulfilled=await database.fulfillments.find({'order_id':oid}).to_list(20)
    check('Three independent fulfillments '+slug,len(fulfilled)==3,states=[{'type':f['type'],'status':f['status']} for f in fulfilled])
    check('Digital delivery '+slug,any(f['type']=='digital_auto' and f['status']=='delivered' for f in fulfilled))
    own=owners[0 if label=='a' else 1];foreign=owners[1 if label=='a' else 0]
    check('Foreign order denied '+slug,(await root.get('/api/public/tenant/full/orders/'+oid,headers=foreign)).status_code==404)
    r=await root.post('/api/public/tenant/full/orders/'+oid+'/complete',headers=own);check('Service completion '+slug,r.status_code==200,status=r.status_code)
    f=next(f for f in fulfilled if f['type']=='physical')
    for state in ['packing','ready_to_ship','shipped','delivered']:
     r=await root.post('/api/public/tenant/full/physical/orders/'+oid+'/fulfillments/'+f['_id'],headers=own,json={'status':state,'carrier_name':'UAT manual','tracking_number':'UAT-DEMO-ONLY'})
     check('Physical '+state+' '+slug,r.status_code==200,status=r.status_code)
  client.close()
if __name__=='__main__':
 try:asyncio.run(main())
 except Exception as e:print(json.dumps({'failed':True,'error_type':type(e).__name__}),flush=True);raise SystemExit(1)
