"""Sandbox-readiness adapter; not registered for customer checkout or live use.

Rates may incur API fees even with test keys, and require separate explicit opt-in.
See https://biteship.com/en/docs/api and its Testing Mode Fee Policy.
"""
import os
from urllib.parse import quote
import httpx
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from .providers import ShippingProvider

class BiteshipSandbox(ShippingProvider):
    name='biteship'
    def __init__(self,fields):
        if os.getenv('PHASE4_SANDBOX_ENABLED')!='true' or not fields.get('api_key','').startswith('biteship_test.'):
            raise FulfillmentUnavailable('Approved Biteship test key required')
        self.fields=fields
    async def request(self,method,path,**kwargs):
        async with httpx.AsyncClient(timeout=25,follow_redirects=False) as http:
            r=await http.request(method,'https://api.biteship.com/v1'+path,headers={'Authorization':self.fields['api_key']},**kwargs)
        if r.status_code not in {200,201}: raise FulfillmentUnavailable(f'Biteship sandbox rejected (HTTP {r.status_code})')
        body=r.json()
        if not isinstance(body,dict) or body.get('success') is not True: raise CommerceError('Invalid Biteship sandbox response')
        return body
    async def connect(self):
        result=await self.request('GET','/couriers')
        return {'provider':self.name,'environment':'sandbox','coverage':'SANDBOX','services':result.get('couriers',[]),'tracking':'authenticated order polling','customer_checkout_enabled':False}
    async def get_rates(self,origin,address,parcels):
        if os.getenv('PHASE4_BITESHIP_RATE_FEES_APPROVED')!='true': raise FulfillmentUnavailable('Biteship rate API fee approval required')
        result=await self.request('POST','/rates/couriers',json={'origin_postal_code':int(origin['postal_code']),'destination_postal_code':int(address['postal_code']),'couriers':'jne','items':parcels})
        return result.get('pricing',[])
    async def create_shipment(self,intent):
        result=await self.request('POST','/orders',json=intent)
        if not result.get('id'): raise CommerceError('Biteship missing order ID; reconcile before retry')
        return result
    async def track_shipment(self,shipment):
        key=quote(shipment['id'],safe='')
        result=await self.request('GET','/orders/'+key)
        if result.get('id')!=shipment['id']: raise CommerceError('Biteship order binding mismatch')
        return result
    async def cancel_shipment(self,shipment):
        return await self.request('POST','/orders/'+quote(shipment['id'],safe='')+'/cancel',json={'cancellation_reason_code':'others','cancellation_reason':'Sandbox integration validation completed'})
