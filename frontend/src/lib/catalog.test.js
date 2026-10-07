import { catalogHref, groupCatalogs, variantLabel, variantsFor } from "./catalog";

test("variant labels preserve trial and non-trial plans and sort durations naturally", () => {
  expect(variantLabel({name: "Claude Trial 1 bulan"})).toBe("TRIAL · 1 bulan");
  expect(variantLabel({name: "ChatGPT Plus 1 bulan (bukan Trial)"})).toBe("PLUS · 1 bulan");
  const products = [12, 3, 1].map((n) => ({_id: String(n), name: `Claude Pro ${n} bulan`, catalog_name: "Claude"}));
  expect(variantsFor([...products, {_id:"x", name:"Other", catalog_name:"Other"}], products[0]).map((p)=>p._id)).toEqual(["1", "3", "12"]);
});

test("groups duration variants together without changing product identities", () => {
  const products = [1, 3, 6].map((months) => ({ _id: String(months), name: `Claude Pro ${months} bulan`, catalog_name: "Claude Pro" }));
  products.push({ _id: "other", name: "Netflix", catalog_name: "Netflix" });
  const catalogs = groupCatalogs(products);
  expect(catalogs).toHaveLength(2);
  expect(catalogs[0].products.map((p) => p._id)).toEqual(["1", "3", "6"]);
});

test("case variants share a catalog and special characters survive links", () => {
  expect(groupCatalogs([{ catalog_name: "Claude Pro" }, { catalog_name: "claude pro" }])).toHaveLength(1);
  const link = catalogHref("AI / Design & Video");
  expect(new URLSearchParams(link.split("?")[1]).get("catalog")).toBe("ai / design & video");
});

test("more than 300 variants remain represented in the catalog", () => {
  const products = Array.from({ length: 350 }, (_, index) => ({ _id: String(index), catalog_name: "Claude Pro" }));
  expect(groupCatalogs(products)[0].products).toHaveLength(350);
});
