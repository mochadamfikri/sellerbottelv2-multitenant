import { createAndProvisionTenant } from "./platformControl";

test("creates a tenant, records the selected plan, then provisions it", async () => {
  const calls = [];
  const client = {
    post: jest.fn(async (url, body) => {
      calls.push({ method: "post", url, body });
      if (url === "/v2/platform/tenants") return { data: { id: "tenant-1" } };
      return { data: { provisioned: true, database_name: "tenant_tenant_1" } };
    }),
    patch: jest.fn(async (url, body) => {
      calls.push({ method: "patch", url, body });
      return { data: { plan: body.plan } };
    }),
  };

  const result = await createAndProvisionTenant(client, {
    name: "Acme Store",
    slug: "acme-store",
    plan: "monthly",
  });

  expect(calls).toEqual([
    { method: "post", url: "/v2/platform/tenants", body: { name: "Acme Store", slug: "acme-store" } },
    { method: "patch", url: "/v2/platform/tenants/tenant-1/plan", body: { plan: "monthly", quotas: {} } },
    { method: "post", url: "/v2/platform/tenants/tenant-1/provision", body: undefined },
  ]);
  expect(result).toEqual({ id: "tenant-1", provisioned: true, database_name: "tenant_tenant_1" });
});
