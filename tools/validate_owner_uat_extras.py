"""Approved SMTP registration and public owner UAT return/branding checks."""
import asyncio,json,secrets
from uat_runtime import configure,ROOT,PRIVATE
configure()
import httpx
from db import client,platform_db
REPORT=ROOT/'test_reports/full-development-uat-20261009/extras.json';results=[]
def check(name,ok,**details):
 results.append({'check':name,'result':'PASS' if ok else 'FAIL',**details});REPORT.write_text(json.dumps(results,indent=2)+'\n');print(name+': '+('PASS' if ok else 'FAIL'),flush=True)
 if not ok:raise AssertionError(name)
async def main():
 p=platform_db();accounts=json.loads((PRIVATE/'credentials.json').read_text())
 async with httpx.AsyncClient(base_url='https://idseconnect.my.id',timeout=45) as root:
  slug='owner-fresh-uat';email='idsegwork+uat-fresh@gmail.com'
  private=PRIVATE/'fresh-registration.json'
  if not private.exists():private.write_text(json.dumps({'email':email,'password':secrets.token_urlsafe(24)}));private.chmod(0o600)
  account=json.loads(private.read_text())
  if not await p.tenants.find_one({'slug':slug}):
   r=await root.post('/api/public/register/request-code',json={'email':email});check('Genuine SMTP OTP accepted',r.status_code==200,recipient=email,inbox_receipt='Owner manual check; OTP entry automated from isolated DB')
   otp=await p.public_reg_otp.find_one({'email':email})
   r=await root.post('/api/public/register/verify-code',json={'email':email,'code':otp['code']});check('OTP verification',r.status_code==200)
   r=await root.post('/api/public/register',json={**account,'username':slug,'store_name':'Fresh Registration UAT','whatsapp':'081234567890','verify_token':r.json()['verify_token']});check('Fresh registration provisioning',r.status_code==201,status=r.status_code)
  r=await root.post('/api/public/tenant/login',json=account);check('Fresh owner login',r.status_code==200)
  for base,purpose in [('idseconnect.my.id','storefront'),('idsestock.my.id','stock_panel')]:
   d=await p.domains.find_one({'domain':slug+'.'+base});check('Fresh '+purpose+' registry',d and d['purpose']==purpose)
  for label,slug,resolution in [('a','fashion-demo','restock'),('b','digital-demo','damaged')]:
   tenant=await p.tenants.find_one({'slug':slug});db=client[tenant['database_name']]
   await p.tenants.update_one({'_id':tenant['_id']},{'$set':{'metadata.capabilities.can_white_label':True,'metadata.capabilities.custom_email_branding_enabled':True}})
   r=await root.post('/api/public/tenant/login',json=accounts['tenant_'+label]);owner={'Authorization':'Bearer '+r.json()['token']}
   for mode in ['platform','tenant_only','co_branded']:
    r=await root.put('/api/public/tenant/full/branding',headers=owner,json={'mode':mode,'brand_name':tenant['name'],'receipt_footer':'UAT DEMO ONLY'});check('Branding '+mode+' '+slug,r.status_code==200)
   payment=await db.order_payments.find_one({'provider_reference':{'$regex':'^uat-'},'status':'paid'})
   oid=payment['order_id'];order=await db.purchases.find_one({'_id':oid});line=next(i for i in order['items'] if i['fulfillment_type']=='physical')
   async with httpx.AsyncClient(base_url='https://'+slug+'.idseconnect.my.id',timeout=45) as customer:
    await customer.post('/api/store/login',json=accounts['customer_'+label])
    r=await customer.post('/api/store/orders/'+oid+'/returns',json={'idempotency_key':'uat-return-'+label,'item_lines':[{'line_id':line['line_id'],'quantity':1}],'reason':'Synthetic UAT return'});check('Return request '+slug,r.status_code==200,status=r.status_code);rid=r.json()['_id']
   current=await db.return_requests.find_one({'_id':rid})
   stages=['reviewing','approved','received','inspected','resolved']
   remaining=stages[stages.index(current['status'])+1:] if current['status'] in stages else stages
   for state in remaining:
    r=await root.post('/api/public/tenant/full/commerce/returns/'+rid,headers=owner,json={'status':state,'resolution':resolution if state in ['inspected','resolved'] else None});check('Return '+state+' '+resolution,r.status_code==200)
   r=await root.post('/api/public/tenant/full/commerce/transactions/'+payment['_id']+'/refunds',headers=owner,json={'idempotency_key':'uat-refund-'+label,'amount':150000,'return_id':rid});check('Refund safely manual '+slug,r.status_code==200 and r.json()['status']=='manual_refund_required')
   for stage in ['clearing','available']:
    r=await root.post('/api/public/tenant/full/commerce/settlement/'+payment['_id']+'/advance',headers=owner,json={'stage':stage});check('Settlement '+stage+' '+slug,r.status_code==200)
 client.close()
if __name__=='__main__':
 try:asyncio.run(main())
 except Exception as e:print(json.dumps({'error_type':type(e).__name__}),flush=True);raise SystemExit(1)
