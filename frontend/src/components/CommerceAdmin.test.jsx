import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react";
import CommerceAdmin from "./CommerceAdmin";
import { TenantApiContext } from "../lib/tenantApi";

global.IS_REACT_ACT_ENVIRONMENT = true;
let container, root;
beforeEach(() => { container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

test("self gateway renders provider-specific secret fields without saved values", async () => {
  const api = { get: jest.fn(path => Promise.resolve({ data: path.endsWith("payment-settings") ? { payment_mode: "self_gateway", provider: "midtrans", environment: "mock", credential_schemas: { midtrans: ["server_key", "client_key", "merchant_id"] }, masked_fields: { server_key: "••••", client_key: "••••" } } : path.endsWith("transactions") || path.endsWith("refunds") ? [] : {} })) };
  await act(async () => root.render(<TenantApiContext.Provider value={api}><CommerceAdmin /></TenantApiContext.Provider>));
  expect(container.textContent).toContain("Gateway Saya Sendiri");
  expect(container.querySelectorAll('input[type="password"]').length).toBe(3);
  expect(Array.from(container.querySelectorAll('input[type="password"]')).every(i => i.value === "")).toBe(true);
  expect(container.textContent).toContain("Test Connection");
  expect(container.textContent).not.toContain("Jumlah payout");
});

test("mock shipping clearly distinguishes simulation and origin fields", async () => {
  const api = { get: jest.fn(path => Promise.resolve({ data: path.endsWith("shipping-settings") ? { mode: "integrated_shipping", provider: "mock_courier", origin: {} } : [] })) };
  await act(async () => root.render(<TenantApiContext.Provider value={api}><CommerceAdmin section="shipping" /></TenantApiContext.Provider>));
  expect(container.textContent).toContain("MOCKED");
  expect(container.textContent).toContain("Kota / Kabupaten origin");
  expect(container.querySelectorAll('input[type="password"]').length).toBe(2);
});
