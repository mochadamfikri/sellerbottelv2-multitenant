"""Public fee controls, frozen checkout, product and stock operations in UAT."""
import asyncio,json,io
from uat_runtime import configure,ROOT,PRIVATE
configure()
import httpx
from PIL import Image
from db import client,platform_db
results=[]
def check(name,ok):
 results.append({'check':name,'result':'PASS' if ok else 'FAIL'});(ROOT/'test_reports/full-development-uat-20261009/operations.json').write_text(json.dumps(results,indent=2)+'\n');print(name+': '+('PASS' if ok else 'FAIL'),flush=True)
 if not ok:raise AssertionError(name)
async def main():
 accounts=json.loads((PRIVATE/'credentials.json').read_text());p=platform_db();db=client['sellerbottel_tenant_fashion_demo']
 async with httpx.AsyncClient(base_url='https://idseconnect.my.id',timeout=45) as root:
  await root.post('/api/auth/login',json=accounts['platform_owner']);path='/api/v2/platform/payments/kasera/fee'
  before=(await root.get(path)).json();policy={'platform_fee':250,'tiers':[{'min_amount':10000,'max_amount':20000,'fee':250},{'min_amount':20001,'max_amount':50000,'fee':500},{'min_amount':50001,'max_amount':None,'fee':750}]}
  check('Save configurable fee tiers',(await root.put(path,json=policy)).status_code==200)
  try:
   invalid={**policy,'tiers':[{'min_amount':10000,'max_amount':20000,'fee':250},{'min_amount':20000,'max_amount':50000,'fee':500}]}
   check('Reject overlapping ranges',(await root.put(path,json=invalid)).status_code==422)
   async with httpx.AsyncClient(base_url='https://fashion-demo.idseconnect.my.id',timeout=45) as customer:
    await customer.post('/api/store/login',json=accounts['customer_a'])
    for amount,fee in [(10000,250),(20000,250),(20001,500),(50000,500),(50001,750)]:
     r=await customer.get('/api/store/gateway/methods',params={'amount':amount});check('Inclusive fee boundary '+str(amount),r.json()['methods'][0]['fee_quote']['platform_fee']==fee)
    quote=(await customer.get('/api/store/gateway/methods',params={'amount':25000})).json()['methods'][0]['fee_quote']
    r=await customer.post('/api/store/checkout',json={'items':[{'pid':'vps-demo','qty':1}],'payment_method':'gateway:qris','expected_gateway_total':quote['total'],'idempotency_key':'owner-uat-tier-freeze'});check('New checkout uses tier',r.status_code==200)
    oid=r.json()['_id'];payment=await db.order_payments.find_one({'order_id':oid});check('Captured fee is Rp500',payment['fee_policy']['platform']==500)
  finally:
   restored=await root.put(path,json={'platform_fee':before['platform_fee'],'tiers':before.get('tiers',[])});check('Restore default fee policy',restored.status_code==200)
  check('Existing payment fee remains frozen',(await db.order_payments.find_one({'order_id':oid}))['fee_policy']['platform']==500)
  r=await root.post('/api/public/tenant/login',json=accounts['tenant_a']);owner={'Authorization':'Bearer '+r.json()['token']};base='/api/public/tenant/full/physical'
  r=await root.post(base+'/products',headers=owner,json={'name':'Owner UAT CRUD Demo','price_idr':12000,'has_variants':True});check('Create physical product',r.status_code==200);pid=r.json()['_id']
  r=await root.put(base+'/products/'+pid,headers=owner,json={'name':'Owner UAT CRUD Demo edited','price_idr':13000,'has_variants':True});check('Edit physical product',r.status_code==200)
  r=await root.post(base+'/products/'+pid+'/variants',headers=owner,json={'sku':'UAT-CRUD-'+pid[:8],'option_values':{'Size':'Demo'},'weight':100});check('Create variant SKU',r.status_code==200);vid=r.json()['_id']
  for op,qty in [('RECEIVE',5),('ADJUSTMENT',1),('DAMAGE',1)]:
   r=await root.post(base+'/variants/'+vid+'/stock',headers=owner,json={'type':op,'quantity':qty,'reference_id':'uat-'+op.lower()+'-'+pid[:8],'reason':'Synthetic UAT operation'});check('Stock '+op,r.status_code==200)
  check('Stock ledger visible',(await root.get(base+'/variants/'+vid+'/stock-movements',headers=owner)).status_code==200)
  data=io.BytesIO();Image.new('RGB',(80,80),(30,100,70)).save(data,format='PNG')
  r=await root.post(base+'/products/'+pid+'/image',headers=owner,files={'image':('uat.png',data.getvalue(),'image/png')});check('Product image upload',r.status_code==200)
 client.close()
if __name__=='__main__':
 try:asyncio.run(main())
 except Exception as e:print(json.dumps({'error_type':type(e).__name__}),flush=True);raise SystemExit(1)
