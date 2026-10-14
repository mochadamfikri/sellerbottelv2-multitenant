import React from "react";
import {createRoot} from "react-dom/client";
import {act} from "react";
import BrandingAdmin from "./BrandingAdmin";
import {TenantApiContext} from "../lib/tenantApi";
global.IS_REACT_ACT_ENVIRONMENT=true;
test("branding capability hides unavailable white label and sender edit",async()=>{
 const el=document.createElement("div");const root=createRoot(el);
 const api={get:jest.fn(()=>Promise.resolve({data:{branding:{mode:"co_branded",brand_name:"A",font:"system",social_links:{}},capabilities:{branding_mode_allowed:["platform","co_branded"],custom_email_branding_enabled:false}}}))};
 await act(async()=>root.render(<TenantApiContext.Provider value={api}><BrandingAdmin/></TenantApiContext.Provider>));
 expect(el.querySelector('select[aria-label="Mode branding"]').textContent).not.toContain("tenant_only");
 expect(el.querySelector('input[aria-label="email_sender_name"]').disabled).toBe(true);
 expect(el.textContent).toContain("Custom domain belum tersedia");
 await act(async()=>root.unmount());
});
