import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import TenantAdmin from "./TenantAdmin";
import platformApi from "../lib/api";

jest.mock("./TenantProducts", () => { const { Link } = require("react-router-dom"); return () => <Link to="/admin?tab=catalogs">Go catalogs</Link>; });
jest.mock("./TenantCatalogs", () => { const { Link } = require("react-router-dom"); return () => <Link to="/admin?tab=products">Go products</Link>; });
jest.mock("./TenantInventory", () => () => <div>Inventory</div>);
jest.mock("./TenantOrders", () => () => <div>Orders</div>);
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock("../lib/tenantApi", () => {
  const actual = jest.requireActual("../lib/tenantApi");
  return { ...actual, createTenantApi: jest.fn() };
});

let container, root;
const clients = [];
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const { createTenantApi } = require("../lib/tenantApi");
  clients.length = 0;
  createTenantApi.mockImplementation((token) => {
    const client = {
      defaults: { headers: { Authorization: token ? `Bearer ${token}` : undefined, common: {} } },
      post: jest.fn().mockResolvedValue({ data: { token: "session-token", tenant_slug: "shop", store_name: "Shop", email: "shop@gmail.com" } }),
      get: jest.fn().mockResolvedValue({ data: { products: 2, catalogs: 1, orders: 3, users: 4 } }),
    };
    clients.push(client);
    return client;
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});
function Location() {
  return <output>{useLocation().pathname}{useLocation().search}</output>;
}
async function click(text) {
  const button = [...container.querySelectorAll("button,a")].find((node) => node.textContent.includes(text));
  expect(button).toBeTruthy();
  await act(async () => button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
}

test("login creates a tenant session, tab links stay in admin, logout clears credentials", async () => {
  await act(async () => root.render(<MemoryRouter initialEntries={["/admin"]}><TenantAdmin /><Location /></MemoryRouter>));
  await act(async () => container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(container.textContent).toContain("Shop");
  const session = clients[clients.length - 1];
  expect(session.get).toHaveBeenCalledWith("/public/tenant/full/stats");
  expect(platformApi.defaults.headers.common.Authorization).toBeUndefined();
  await click("Produk");
  await click("Go catalogs");
  expect(container.querySelector("output").textContent).toBe("/admin?tab=catalogs");
  await click("Go products");
  expect(container.querySelector("output").textContent).toBe("/admin?tab=products");
  await click("Keluar");
  expect(session.defaults.headers.Authorization).toBeUndefined();
  expect(container.textContent).toContain("Masuk");
  expect(container.textContent).not.toContain("Shop");
  expect(container.querySelector('input[type="password"]').value).toBe("");
});
