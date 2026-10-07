export const catalogKey = (name) => String(name || "Produk Lainnya").trim().toLocaleLowerCase("id-ID");
export const catalogHref = (name) => `/store/products?catalog=${encodeURIComponent(catalogKey(name))}`;

export function variantLabel(product) {
  const name = String(product?.name || "Produk");
  const duration = name.match(/\b\d+\s*(?:bulan|months?|bln|tahun|years?|hari|days?|minggu|weeks?)\b/i)?.[0];
  const plan = name.replace(/\b(?:bukan|non|not|tanpa)[\s-]+trial\b/gi, "").match(/\b(trial|pro|plus|premium|max)\b/i)?.[0];
  return duration ? `${plan ? `${plan.toUpperCase()} · ` : ""}${duration}` : name;
}

export function variantsFor(products, product) {
  return products.filter((candidate) => catalogKey(candidate.catalog_name) === catalogKey(product?.catalog_name))
    .sort((a, b) => a.name.localeCompare(b.name, "id", { numeric: true }));
}

export function groupCatalogs(products) {
  const groups = new Map();
  for (const product of products) {
    const name = product.catalog_name || "Produk Lainnya";
    const key = catalogKey(name);
    if (!groups.has(key)) groups.set(key, { key, name, products: [] });
    groups.get(key).products.push(product);
  }
  return [...groups.values()];
}
