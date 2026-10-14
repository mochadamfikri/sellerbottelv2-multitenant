import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { AdminRoute } from "../App";
import api from "../lib/api";

jest.mock("./TenantAdmin", () => () => <div>Tenant management</div>);
jest.mock("./Overview", () => () => <div>Owner management</div>);
jest.mock("../context/AuthContext", () => ({ useAuth: () => ({ user: { role: "admin" }, logout: jest.fn() }), AuthProvider: ({ children }) => children }));

let container, root;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  jest.restoreAllMocks();
});

test("registered custom host resolves to tenant admin through backend config", async () => {
  jest.spyOn(api, "get").mockResolvedValue({ data: { tenant_slug: "custom-shop" } });
  await act(async () => root.render(<MemoryRouter><AdminRoute /></MemoryRouter>));
  expect(api.get).toHaveBeenCalledWith("/public/host-config", { params: { host: window.location.hostname } });
  expect(container.textContent).toContain("Tenant management");
  expect(container.textContent).not.toContain("Owner management");
});

test("host resolution failure does not render owner management", async () => {
  jest.spyOn(api, "get").mockRejectedValue(new Error("offline"));
  await act(async () => root.render(<MemoryRouter><AdminRoute /></MemoryRouter>));
  expect(container.textContent).toContain("Konfigurasi host gagal dimuat");
  expect(container.textContent).not.toContain("Owner management");
});
