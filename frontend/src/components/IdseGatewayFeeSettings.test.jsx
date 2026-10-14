import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react";
import api from "../lib/api";
import IdseGatewayFeeSettings from "./IdseGatewayFeeSettings";
jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn(), put: jest.fn() }, formatApiErrorDetail: String }));
global.IS_REACT_ACT_ENVIRONMENT = true;

test("owner can save tiered IDSE fees with default 250", async () => {
  api.get.mockResolvedValue({data:{platform_fee:250,tiers:[]}});
  api.put.mockImplementation((_,body)=>Promise.resolve({data:body}));
  const container=document.createElement("div");document.body.appendChild(container);
  const root=createRoot(container);
  await act(async()=>root.render(<IdseGatewayFeeSettings/>));
  expect(container.querySelector('input').value).toBe("250");
  const add=Array.from(container.querySelectorAll('button')).find(b=>b.textContent==='Tambah rentang');
  await act(async()=>add.click());await act(async()=>add.click());
  const set=async(label,value)=>act(async()=>{
    const input=container.querySelector(`[aria-label="${label}"]`);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
  await set('Mulai rentang 1','10000');await set('Akhir rentang 1','20000');
  await set('Mulai rentang 2','20001');await set('Akhir rentang 2','50000');await set('Fee rentang 2','500');
  await act(async()=>container.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  expect(api.put).toHaveBeenCalledWith('/v2/platform/payments/kasera/fee',{platform_fee:250,tiers:[{min_amount:10000,max_amount:20000,fee:250},{min_amount:20001,max_amount:50000,fee:500}]});
  expect(container.textContent).toContain('Berlaku untuk checkout baru');
  await act(async()=>root.unmount());container.remove();
});
