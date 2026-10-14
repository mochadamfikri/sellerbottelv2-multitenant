import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react";
import api from "../lib/api";
import { GatewayMethods } from "./CustomerPostPurchase";
jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn() }, fmtIDR: n => String(n), formatApiErrorDetail: String }));
global.IS_REACT_ACT_ENVIRONMENT = true;

test("buyer quote becomes unusable while the cart price changes", async () => {
  const container=document.createElement("div");document.body.appendChild(container);
  const root=createRoot(container), onQuote=jest.fn(), onChange=jest.fn();
  const quote={base_amount:100000,total:100957,gateway_fee:957};
  api.get.mockResolvedValueOnce({data:{launch_profile:"v1_kasera",methods:[{code:"gateway:qris",label:"QRIS",fee_quote:quote}]}});
  await act(async()=>root.render(<GatewayMethods apiPrefix="/store/t/shop" method="gateway:qris" amount={100000} onQuote={onQuote} onChange={onChange}/>));
  expect(onQuote.mock.calls.at(-1)[0]).toMatchObject({ready:true,fee_quote:quote});
  let resolve;
  api.get.mockReturnValueOnce(new Promise(r=>{resolve=r;}));
  await act(async()=>root.render(<GatewayMethods apiPrefix="/store/t/shop" method="gateway:qris" amount={15001} onQuote={onQuote} onChange={onChange}/>));
  expect(onQuote.mock.calls.at(-1)[0]).toMatchObject({ready:false,fee_quote:null});
  await act(async()=>resolve({data:{launch_profile:"v1_kasera",methods:[{code:"gateway:qris",label:"QRIS",fee_quote:{base_amount:15001,total:15359,gateway_fee:358}}]}}));
  expect(onQuote.mock.calls.at(-1)[0]).toMatchObject({ready:true,fee_quote:{total:15359,gateway_fee:358}});
  await act(async()=>root.unmount());container.remove();
});
