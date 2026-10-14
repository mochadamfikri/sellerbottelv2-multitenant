import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {TenantApiContext} from '../lib/tenantApi';
import {TenantPhysicalOrder,CustomerShipping} from './PhysicalOrder';
import api from '../lib/api';
let container,root;
beforeEach(()=>{global.IS_REACT_ACT_ENVIRONMENT=true;container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();jest.restoreAllMocks();});
test('owner tracking action stays in tenant full API and uses supplied carrier',async()=>{
 const record={_id:'f',status:'ready_to_ship',item_refs:['line']};
 const tenantApi={get:jest.fn().mockResolvedValue({data:{shipping_fee:5000,shipping_address:{city:'Bandung'},items:[{line_id:'line',sku:'SKU',name:'Hoodie',qty:1}],fulfillments:[record]}}),post:jest.fn().mockResolvedValue({data:{}})};
 await act(async()=>root.render(<TenantApiContext.Provider value={tenantApi}><TenantPhysicalOrder orderId="order"/></TenantApiContext.Provider>));
 const fields=container.querySelectorAll('input');
 const setValue=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
 await act(async()=>{setValue.call(fields[0],'Manual Carrier');fields[0].dispatchEvent(new Event('input',{bubbles:true}));});
 await act(async()=>{setValue.call(fields[1],'TRACK-1');fields[1].dispatchEvent(new Event('input',{bubbles:true}));});
 await act(async()=>[...container.querySelectorAll('button')].find(button=>button.textContent==='Tandai dikirim').click());
 expect(tenantApi.post).toHaveBeenCalledWith('/public/tenant/full/physical/orders/order/fulfillments/f',{status:'shipped',carrier_name:'Manual Carrier',tracking_number:'TRACK-1'});
});
test('customer sees manual carrier and tracking through the tenant storefront API',async()=>{
 jest.spyOn(api,'get').mockResolvedValue({data:{shipping_fee:5000,shipments:[{fulfillment_id:'f',status:'shipped',carrier_name:'Manual Carrier',tracking_number:'TRACK-1'}]}});
 await act(async()=>root.render(<CustomerShipping orderId="order" apiPrefix="/store/t/shop"/>));
 expect(api.get).toHaveBeenCalledWith('/store/t/shop/orders/order/shipping');
 expect(container.textContent).toContain('TRACK-1');expect(container.textContent).toContain('Manual Carrier');
});
