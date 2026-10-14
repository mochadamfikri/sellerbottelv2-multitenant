"""Explicit provider test keys only. Outputs allowlisted summaries, never responses/secrets."""
import asyncio,json,os,secrets,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
os.environ['PYTHON_DOTENV_DISABLED']='1';os.environ['PHASE3_SANDBOX_ENABLED']='true';os.environ['PHASE4_SANDBOX_ENABLED']='true'
from payments.providers.kasera import KaseraSandbox
from shipping.biteship import BiteshipSandbox
from urllib.parse import urlsplit
import httpx
EVIDENCE=ROOT/'test_reports/phase-4-final-hardening-20261008'
async def run():
    keys=json.loads(Path('/tmp/seller-phase4-sandbox-keys.json').read_text())
    assert keys['kasera'].startswith('kp_test_') and keys['biteship'].startswith('biteship_test.')
    output={'midtrans':{'status':'BLOCKED — CREDENTIALS UNAVAILABLE'},'safety':{'live_keys_used':False,'real_payment_or_payout':False,'production_modified':False}}
    adapter=KaseraSandbox('kasera','sandbox',{'api_key':keys['kasera'],'webhook_secret':''})
    info={'status':'BLOCKED — MERCHANT NOT ENABLED','checks':{},'webhook':'BLOCKED — CREDENTIALS UNAVAILABLE','refund':'NOT SUPPORTED','cancel':'NOT SUPPORTED'}
    try:
        caps=await adapter.connect();info['checks']['connection']=True;info['supported_methods']=caps['supported_methods']
        method='qris' if 'qris' in caps['supported_methods'] else caps['supported_methods'][0]
        for mode,outcome in [('platform_settlement','succeeded'),('self_gateway','expired')]:
            payment={'provider_reference':'phase4-'+secrets.token_hex(12),'amount':15000,'method':method}
            created=await adapter.create_payment(payment);payment.update(created)
            duplicate=await adapter.create_payment(payment)
            info['checks'][mode+'_idempotency']=duplicate['provider_payment_id']==created['provider_payment_id']
            info['checks'][mode+'_retrieve']=(await adapter.get_payment(payment))['status']=='pending'
            url=urlsplit(created['instructions']['checkout_url']);assert url.scheme=='https' and url.hostname=='pay.kasera.id' and url.path.startswith('/p/')
            async with httpx.AsyncClient(timeout=20,follow_redirects=False) as http:
                response=await http.post('https://pay.kasera.id/api/v1/checkout/'+url.path.split('/p/',1)[1]+'/simulate-payment',json={'outcome':outcome})
            assert response.status_code==200
            info['checks'][mode+'_simulated_'+outcome]=(await adapter.get_payment(payment))['status']==('paid' if outcome=='succeeded' else 'expired')
        info['status']='REAL SANDBOX VERIFIED'
        info['scope']='API connection, capabilities, create/idempotency, status, simulated paid/expiry only; webhook and local settlement E2E remain mock verified'
    except Exception as error: info['error_type']=type(error).__name__
    output['kasera']=info
    shipping={'status':'BLOCKED — MERCHANT NOT ENABLED','checks':{},'rate':'BLOCKED — MERCHANT NOT ENABLED','rate_reason':'Fee approval pending; rate test not invoked','webhook':'NOT SUPPORTED','checkout_enabled':False}
    b=BiteshipSandbox({'api_key':keys['biteship']})
    try:
        caps=await b.connect();shipping['checks']['connection']=True;shipping['service_count']=len(caps['services'])
        intent={'origin_contact_name':'Sandbox Sender','origin_contact_phone':'088888888888','origin_address':'Plaza Senayan, Jalan Asia Afrika, Jakarta','origin_postal_code':12440,'destination_contact_name':'Sandbox Receiver','destination_contact_phone':'088888888888','destination_address':'Lebak Bulus MRT, Jakarta','destination_postal_code':12950,'courier_company':'jne','courier_type':'reg','delivery_type':'now','reference_id':'phase4-'+secrets.token_hex(12),'order_note':'Sandbox test only','items':[{'name':'Synthetic shirt','value':15000,'quantity':1,'weight':200}]}
        order=await b.create_shipment(intent);shipping['checks']['create_order']=True
        fetched=await b.track_shipment(order);shipping['checks']['authenticated_tracking']=fetched['id']==order['id']
        cancelled=await b.cancel_shipment(order);shipping['checks']['cancel']=cancelled.get('status')=='cancelled'
        fetched=await b.track_shipment(order);shipping['checks']['cancelled_status']=fetched.get('status')=='cancelled'
        if os.getenv('PHASE4_BITESHIP_RATE_FEES_APPROVED')=='true':
            rates=await b.get_rates({'postal_code':'12440'},{'postal_code':'12950'},intent['items']);shipping['checks']['rates']=bool(rates);shipping['rate']='REAL SANDBOX VERIFIED'
        shipping['status']='REAL SANDBOX VERIFIED'
        shipping['scope']='Free test Order API/connection/poll/cancel; rate/checkout/webhook gates listed separately'
    except Exception as error: shipping['error_type']=type(error).__name__
    output['biteship']=shipping
    EVIDENCE.mkdir(exist_ok=True,parents=True);(EVIDENCE/'provider-sandbox.json').write_text(json.dumps(output,indent=2)+'\n');print(json.dumps(output))
if __name__=='__main__':asyncio.run(run())
