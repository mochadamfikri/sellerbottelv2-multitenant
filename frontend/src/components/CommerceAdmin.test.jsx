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

test("V1 shows Kasera and separate settlement fees", async () => {
  const types = ["PAYMENT_GROSS", "KASERA_PERCENT_FEE", "KASERA_FIXED_FEE", "SELLERBOTTEL_PLATFORM_FEE", "NET_SETTLEMENT"];
  const api = { get: jest.fn(path => Promise.resolve({ data: path.endsWith("payment-settings") ? { launch_profile: "v1_kasera", payment_mode: "platform_settlement", provider: "kasera", environment: "sandbox" } : path.endsWith("settlement") ? { balances: { pending: 14395 }, entries: types.map((type, i) => ({ _id: String(i), type, order_id: "order", amount: 250 })) } : path.endsWith("transactions") || path.endsWith("refunds") ? [] : {} })) };
  await act(async () => root.render(<TenantApiContext.Provider value={api}><CommerceAdmin /></TenantApiContext.Provider>));
  expect(container.textContent).toContain("Kasera 0,7%");
  expect(container.textContent).toContain("Kasera biaya tetap");
  expect(container.textContent).toContain("Biaya SellerBottel");
  expect(container.textContent).toContain("Settlement bersih");
  expect(container.textContent).not.toContain("Midtrans");
});

test("V1 shipping offers only manual shipping", async () => {
  const api = { get: jest.fn(path => Promise.resolve({ data: path.endsWith("shipping-settings") ? { launch_profile: "v1_kasera", mode: "manual_shipping" } : [] })) };
  await act(async () => root.render(<TenantApiContext.Provider value={api}><CommerceAdmin section="shipping" /></TenantApiContext.Provider>));
  expect(Array.from(container.querySelectorAll("option")).map(o => o.value)).toEqual(["manual_shipping"]);
});
