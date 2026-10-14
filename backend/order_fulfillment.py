"""Customer-owned, order-bound delivery details; no credentials in order lists."""
import base64
from fastapi import HTTPException, Response
from inventory import decrypt_items
from db import db

PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}


async def owned_order(order_id, customer):
    owners = [{"customer_id": customer["_id"]}]
    if customer.get("telegram_id"):
        owners.append({"user_tid": customer["telegram_id"]})
    order = await db.purchases.find_one({"_id": order_id, "$or": owners})
    if not order:
        raise HTTPException(404, "Pesanan tidak ditemukan.", headers=PRIVATE_HEADERS)
    return order


async def fulfillment(order):
    result = {"order_id": order["_id"], "invoice_id": order.get("invoice_id"), "status": order.get("status"), "products": [], "ready": False}
    partial = order.get("requires_shipping") and order.get("status") in {"paid", "physical_pending", "service_waiting"}
    records = {}
    if partial:
        from commerce.fulfillment.router import current_repository, require_active_context
        repo = current_repository()
        await require_active_context(repo)
        records = {record["line_id"]: record for record in await repo.list_order(order["_id"])}
    if order.get("status") not in {"delivered", "completed"} and not partial:
        result["message"] = "Data akun tersedia setelah pesanan selesai dikirim."
        return result
    complete = True
    offsets = {}
    for item in order.get("items") or []:
        if item.get("fulfillment_type") == "physical":
            continue
        if partial and (records.get(item.get("line_id"), {}).get("status") not in {"delivered", "completed"} or records.get(item.get("line_id"), {}).get("execution_status") != "done"):
            complete = False
            continue
        pid = item.get("product_id") or item.get("pid")
        quantity = max(1, int(item.get("qty") or 1))
        stored = await db.inventory_items.find({"order_id": order["_id"], "product_id": pid, "status": "sold"}).sort("_id", 1).skip(offsets.get(pid, 0)).limit(quantity).to_list(quantity)
        offsets[pid] = offsets.get(pid, 0) + quantity
        product = await db.products.find_one({"_id": pid}) or {}
        if item.get("fulfillment_snapshot"):
            from commerce.order_items import product_for_line
            product = product_for_line(item, product)
        line = {"product_id": pid, "name": item.get("name") or product.get("name") or "Produk", "qty": quantity, "accounts": [], "files": []}
        for record in stored:
            secret = decrypt_items([record])[0]
            if "__file_name" in secret or "__file_data_b64" in secret:
                line["files"].append({"id": record["_id"], "name": secret.get("__file_name") or "inventory.session"})
            else:
                line["accounts"].append({key: value for key, value in secret.items() if not key.startswith("__")})
        if not stored and item.get("delivery_type") not in {"inventory", "service"} and product.get("content"):
            line["accounts"].append({"Informasi produk": product["content"]})
        elif item.get("delivery_type") == "inventory" or product.get("inventory_enabled"):
            if len(stored) != quantity:
                complete = False
                line["message"] = "Sebagian data pengiriman belum tersedia. Hubungi admin dengan nomor invoice ini."
        elif not stored:
            line["message"] = "Pesanan layanan selesai. Hubungi admin untuk informasi layanan."
        result["products"].append(line)
    result["ready"] = complete
    return result


def fulfillment_text(data):
    lines = ["IDSE Marketplace", f"Invoice: {data.get('invoice_id') or data['order_id']}", ""]
    for product in data["products"]:
        lines.append(f"{product['name']} × {product['qty']}")
        for index, account in enumerate(product["accounts"], 1):
            lines.append(f"Akun {index}")
            lines.extend(f"{key}: {value}" for key, value in account.items())
            lines.append("")
        for file in product["files"]:
            lines.append(f"File: {file['name']} (unduh dari detail pesanan)")
        if product.get("message"):
            lines.append(product["message"])
        lines.append("")
    return "\n".join(lines)


async def delivered_file(order, item_id):
    data = await fulfillment(order)
    if order.get("status") not in {"delivered", "completed"} and not data["products"]:
        raise HTTPException(409, "Pesanan belum selesai.", headers=PRIVATE_HEADERS)
    permitted_files = {file["id"] for product in data["products"] for file in product["files"]}
    if item_id not in permitted_files:
        raise HTTPException(404, "File tidak ditemukan.", headers=PRIVATE_HEADERS)
    pids = [product["product_id"] for product in data["products"]]
    record = await db.inventory_items.find_one({"_id": item_id, "order_id": order["_id"], "product_id": {"$in": pids}, "status": "sold"})
    if not record:
        raise HTTPException(404, "File tidak ditemukan.", headers=PRIVATE_HEADERS)
    secret = decrypt_items([record])[0]
    if "__file_name" not in secret and "__file_data_b64" not in secret:
        raise HTTPException(404, "Item ini bukan file.", headers=PRIVATE_HEADERS)
    return base64.b64decode(secret.get("__file_data_b64") or "", validate=True), secret.get("__file_name") or "inventory.session"
