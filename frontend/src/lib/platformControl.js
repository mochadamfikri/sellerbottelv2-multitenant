export async function createAndProvisionTenant(client, { name, slug, plan }) {
  const tenant = (await client.post("/v2/platform/tenants", { name, slug })).data;
  await client.patch(`/v2/platform/tenants/${tenant.id}/plan`, { plan, quotas: {} });
  const provision = (await client.post(`/v2/platform/tenants/${tenant.id}/provision`)).data;

  return { ...tenant, ...provision };
}
