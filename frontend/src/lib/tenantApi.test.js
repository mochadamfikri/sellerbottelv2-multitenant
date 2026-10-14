import platformApi from "./api";
import { createTenantApi, clearTenantApi } from "./tenantApi";

test("tenant credentials are isolated from platform and public requests", async () => {
  const tenantA = createTenantApi("token-a");
  const tenantB = createTenantApi("token-b");
  const seen = [];
  const adapter = async (config) => {
    seen.push({ url: config.url, auth: config.headers.Authorization });
    return { data: {}, status: 200, statusText: "OK", headers: {}, config };
  };
  await tenantA.get("/public/tenant/full/products", { adapter });
  await tenantB.get("/public/tenant/full/orders", { adapter });
  await platformApi.get("/auth/me", { adapter });
  await platformApi.get("/public/promo-config", { adapter });
  expect(seen.map((request) => request.auth)).toEqual(["Bearer token-a", "Bearer token-b", undefined, undefined]);
  clearTenantApi(tenantA);
  await tenantA.get("/public/tenant/me", { adapter });
  expect(seen[4].auth).toBeUndefined();
  expect(tenantB.defaults.headers.Authorization).toBe("Bearer token-b");
});
