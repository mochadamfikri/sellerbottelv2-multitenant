export const cartKey = item => `${item.pid}:${item.variant_id || ""}`;
export const variantFor = (product, item) => product?.variants?.find(v => v._id === item.variant_id);
export const availableFor = (product, item) => product?.fulfillment_type === "physical" ? Number(variantFor(product,item)?.available || 0) : product?.stock == null ? 100 : Number(product.stock);
export const priceFor = (product, item) => variantFor(product,item)?.price_override ?? product?.price_idr_current ?? product?.price_idr ?? 0;
export const shippingAddressValid = address => ["recipient_name","phone","address_line_1","city","province","postal_code"].every(key => String(address[key] || "").trim()) && /^[A-Z]{2}$/.test(address.country || "ID") && /^[+0-9 ()-]{7,30}$/.test(address.phone || "") && ((address.country || "ID") !== "ID" || /^\d{5}$/.test(address.postal_code));
