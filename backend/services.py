from datetime import datetime, timezone
from db import db, get_settings
from tgapi import send_message, send_photo_bytes
from html import escape
from i18n import t
from pricing import base_price
from inventory import available_count

CUR_FIELD = {"USD": "balance_usd", "IDR": "balance_idr"}


def fmt_amount(amount: float, currency: str) -> str:
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"Rp {amount:,.0f}".replace(",", ".")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


async def user_lang(tid) -> str:
    u = await db.bot_users.find_one({"telegram_id": tid}, {"lang": 1})
    return (u or {}).get("lang") or "id"


async def apply_pending_wallet_merge(customer_id: str) -> bool:
    """Apply an email account's captured wallet transfer to its Telegram wallet once."""
    customer = await db.store_customers.find_one({"_id": customer_id})
    if not customer or not customer.get("telegram_id"):
        return False
    transfer = customer.get("wallet_merge") or {}
    merge_id = transfer.get("id")
    if not merge_id or transfer.get("status") == "complete":
        return bool(merge_id and transfer.get("status") == "complete")

    telegram_id = customer["telegram_id"]
    await db.bot_users.update_one(
        {"telegram_id": telegram_id},
        {"$setOnInsert": {"telegram_id": telegram_id, "balance_idr": 0, "balance_usd": 0}},
        upsert=True,
    )
    result = await db.bot_users.update_one(
        {"telegram_id": telegram_id, "wallet_merge_ids": {"$ne": merge_id}},
        {
            "$inc": {
                "balance_idr": float(transfer.get("amount_idr") or 0),
                "balance_usd": float(transfer.get("amount_usd") or 0),
            },
            "$addToSet": {"wallet_merge_ids": merge_id},
        },
    )
    if result.modified_count != 1:
        bot_user = await db.bot_users.find_one(
            {"telegram_id": telegram_id, "wallet_merge_ids": merge_id}, {"_id": 1}
        )
        if not bot_user:
            return False

    await db.store_customers.update_one(
        {"_id": customer_id, "wallet_merge.id": merge_id, "wallet_merge.status": {"$ne": "complete"}},
        {"$set": {"wallet_merge.status": "complete", "wallet_merge.completed_at": now_iso()}},
    )
    return True


async def credit_deposit(deposit: dict, note: str = ""):
    amount = deposit.get("credited_amount") or deposit["amount"]
    field = CUR_FIELD[deposit["currency"]]
    deposit_id = deposit["_id"]

    customer_id = deposit.get("customer_id")
    if customer_id:
        customer = await db.store_customers.find_one({"_id": customer_id})
        if not customer:
            return False
        if customer.get("telegram_id"):
            await apply_pending_wallet_merge(customer_id)
            telegram_id = customer["telegram_id"]
            user_result = await db.bot_users.update_one(
                {"telegram_id": telegram_id, "deposit_credit_ids": {"$ne": deposit_id}},
                {"$inc": {field: amount}, "$addToSet": {"deposit_credit_ids": deposit_id}},
            )
            user = await db.bot_users.find_one({"telegram_id": telegram_id}, {"deposit_credit_ids": 1})
            if user_result.modified_count == 0 and (not user or deposit_id not in user.get("deposit_credit_ids", [])):
                return False
        else:
            user_result = await db.store_customers.update_one(
                {"_id": customer_id, "telegram_id": {"$exists": False}, "deposit_credit_ids": {"$ne": deposit_id}},
                {"$inc": {field: amount}, "$addToSet": {"deposit_credit_ids": deposit_id}},
            )
            if user_result.modified_count == 0:
                latest = await db.store_customers.find_one({"_id": customer_id})
                if latest and latest.get("telegram_id"):
                    await apply_pending_wallet_merge(customer_id)
                    telegram_id = latest["telegram_id"]
                    user_result = await db.bot_users.update_one(
                        {"telegram_id": telegram_id, "deposit_credit_ids": {"$ne": deposit_id}},
                        {"$inc": {field: amount}, "$addToSet": {"deposit_credit_ids": deposit_id}},
                    )
                    credited = await db.bot_users.find_one({"telegram_id": telegram_id}, {"deposit_credit_ids": 1})
                    if user_result.modified_count == 0 and (not credited or deposit_id not in credited.get("deposit_credit_ids", [])):
                        return False
                else:
                    credited = await db.store_customers.find_one({"_id": customer_id}, {"deposit_credit_ids": 1})
                    if not credited or deposit_id not in credited.get("deposit_credit_ids", []):
                        return False
    else:
        user_result = await db.bot_users.update_one(
            {"telegram_id": deposit["user_tid"], "deposit_credit_ids": {"$ne": deposit_id}},
            {"$inc": {field: amount}, "$addToSet": {"deposit_credit_ids": deposit_id}},
        )
        if user_result.modified_count == 0:
            user = await db.bot_users.find_one({"telegram_id": deposit["user_tid"]}, {"deposit_credit_ids": 1})
            if not user or deposit_id not in user.get("deposit_credit_ids", []):
                return False

    await db.deposits.update_one(
        {"_id": deposit_id, "status": "pending"},
        {"$set": {
            "status": "approved",
            "credited_amount": amount,
            "decided_at": now_iso(),
            "note": note,
        }},
    )

    if deposit.get("user_tid"):
        lang = await user_lang(deposit["user_tid"])
        await _send_deposit_notice(deposit, t(lang, "dep_approved", amount=fmt_amount(amount, deposit["currency"])))
    return True


async def _send_deposit_notice(deposit: dict, message: str):
    if not deposit.get("user_tid"):
        return
    bot_id = deposit.get("reseller_bot_id")
    if bot_id:
        try:
            bot = await db.reseller_bots.find_one({"_id": bot_id})
            if bot:
                from reseller_bot import send as send_reseller
                await send_reseller(bot, deposit["user_tid"], message)
        except Exception:
            pass  # Balance and deposit status must not depend on Telegram delivery.
    else:
        await send_message(deposit["user_tid"], message)


async def reject_deposit(deposit: dict, note: str = ""):
    await db.deposits.update_one({"_id": deposit["_id"]}, {"$set": {
        "status": "rejected", "decided_at": now_iso(), "note": note,
    }})
    if deposit.get("user_tid"):
        lang = await user_lang(deposit["user_tid"])
        reason = t(lang, "reason_label", r=note) if note else ""
        await _send_deposit_notice(deposit, t(lang, "dep_rejected", amount=fmt_amount(deposit["amount"], deposit["currency"]), reason=reason))


async def cancel_deposit(deposit: dict):
    amount = deposit.get("credited_amount") or deposit["amount"]
    field = CUR_FIELD[deposit["currency"]]
    deposit_id = deposit["_id"]

    if deposit.get("customer_id"):
        customer = await db.store_customers.find_one({"_id": deposit["customer_id"]})
        if not customer:
            raise ValueError("Akun pelanggan tidak ditemukan.")
        if customer.get("telegram_id"):
            await apply_pending_wallet_merge(deposit["customer_id"])
            wallet, query = db.bot_users, {"telegram_id": customer["telegram_id"]}
        else:
            wallet, query = db.store_customers, {"_id": deposit["customer_id"], "telegram_id": {"$exists": False}}
    else:
        wallet, query = db.bot_users, {"telegram_id": deposit["user_tid"]}
    result = await wallet.update_one(
        {**query, field: {"$gte": amount}, "deposit_debit_ids": {"$ne": deposit_id}},
        {"$inc": {field: -amount}, "$addToSet": {"deposit_debit_ids": deposit_id}},
    )
    if result.modified_count == 0:
        user = await wallet.find_one({**query, "deposit_debit_ids": deposit_id}, {"_id": 1})
        if not user:
            raise ValueError("Saldo pengguna tidak cukup atau deposit sudah dibatalkan.")

    await db.deposits.update_one(
        {"_id": deposit_id, "status": "approved"},
        {"$set": {"status": "cancelled", "decided_at": now_iso()}},
    )

    if deposit.get("user_tid"):
        lang = await user_lang(deposit["user_tid"])
        await _send_deposit_notice(deposit, t(lang, "dep_cancelled", amount=fmt_amount(amount, deposit["currency"])))
    return True


async def notify_admin(text: str, kb=None, photo_file_id=None):
    s = await get_settings()
    admin_id = s.get("admin_telegram_id")
    if not admin_id:
        return
    if photo_file_id:
        from tgapi import send_photo_by_id
        await send_photo_by_id(admin_id, photo_file_id, caption=text, kb=kb)
    else:
        await send_message(admin_id, text, kb=kb)


async def _broadcast_channel_id():
    import os
    settings = await get_settings()
    configured = str(settings.get("broadcast_channel_id") or os.environ.get("BROADCAST_CHANNEL_ID", "")).strip()
    if configured:
        return configured
    for channel in settings.get("required_channels") or []:
        if channel.get("enabled", True) and channel.get("channel_id"):
            return str(channel["channel_id"])
    return ""


async def notify_transaction_channel(order: dict):
    import re
    settings = await get_settings()
    if not settings.get("transaction_success_channel_enabled", False):
        return {"ok": True, "skipped": "disabled"}
    channels = list(dict.fromkeys(value.strip() for value in re.split(r"[,\n]+", settings.get("transaction_channel_ids") or await _broadcast_channel_id()) if value.strip()))
    if not channels:
        return {"ok": False, "error": "channel_not_configured"}

    names = []
    total_qty = 0
    for item in order.get("items") or []:
        qty = max(1, int(item.get("qty") or 1))
        total_qty += qty
        names.append(f"{item.get('name') or 'Product'} ×{qty}")

    from telegram_identity import purchase_identity, purchase_source, purchase_heading
    source = purchase_source(order)
    masked_id, masked_username = await purchase_identity(order)
    identity_lines = ""
    if source != "WEB" or masked_id != "-" or masked_username != "-":
        if masked_id != "-":
            identity_lines += f"Telegram ID: {masked_id}\n"
        if masked_username != "-":
            identity_lines += f"Username: {masked_username}\n"
    body = (f"{purchase_heading(source)}\n\n"
            f"Invoice: <code>{escape(str(order.get('invoice_id') or ''))}</code>\n"
            f"Sumber: {source}\n"
            f"{identity_lines}"
            f"Produk: {escape(', '.join(names))}\n"
            f"Total: <b>{escape(fmt_amount(order.get('total') or 0, order.get('currency') or 'IDR'))}</b>\n"
            f"Status: <b>{escape(order.get('status') or 'paid')}</b>")

    image = _transaction_image(order, total_qty) if settings.get("broadcast_auto_image_enabled") else None
    results = []
    for channel_id in channels:
        try:
            from broadcast_composer import send_composed
            result = await send_composed(channel_id, body, image)
            results.append({"chat_id": channel_id, "ok": bool(result.get("ok"))})
        except Exception:
            results.append({"chat_id": channel_id, "ok": False})
    return {"ok": all(row["ok"] for row in results), "results": results}


async def notify_transaction_channel_safely(order: dict):
    """A notification failure must never undo successful order fulfillment."""
    try:
        return await notify_transaction_channel(order)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Transaction notification failed for %s", order.get("_id"))
        return {"ok": False}


def _transaction_image(order: dict, total_qty: int):
    try:
        from broadcast_image import render_transaction_image
        return render_transaction_image(total_qty, order.get("total") or 0,
                                        order.get("currency") or "IDR")
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Generate transaction image failed")
        return None


async def notify_transaction_admin(order: dict, buyer: str):
    from telegram_identity import purchase_source, purchase_heading
    source = purchase_source(order)
    settings = await get_settings()
    admin_id = settings.get("admin_telegram_id")
    if not admin_id:
        return {"ok": False, "error": "admin_not_configured"}
    items = order.get("items") or []
    names = ", ".join(f"{item.get('name') or 'Produk'} ×{item.get('qty') or 1}" for item in items)
    caption = (f"{purchase_heading(source)}\n\n"
               f"Invoice: <code>{escape(str(order.get('invoice_id') or ''))}</code>\n"
               f"Sumber: {source}\n"
               f"Pembeli: {escape(buyer)}\n"
               f"Produk: {escape(names)}\n"
               f"Total: <b>{fmt_amount(order.get('total') or 0, order.get('currency') or 'IDR')}</b>\n"
               f"Status: <b>{escape(order.get('status') or 'paid')}</b>")
    image = _transaction_image(order, sum(max(1, int(item.get("qty") or 1)) for item in items))
    if image:
        return await send_photo_bytes(admin_id, image, "transaction-success.jpg", caption=caption)
    return await send_message(admin_id, caption)


async def _product_channel_notification(product: dict, title: str, heading: str, stock: int | None = None):
    settings = await get_settings()
    channel_id = await _broadcast_channel_id()
    if not channel_id:
        return {"ok": False, "error": "channel_not_configured"}

    name = escape(str(product.get("name") or "Product"))
    description = escape(str(product.get("description") or "").strip())
    price = fmt_amount(await base_price(product, "IDR"), "IDR")
    body = (
        f"{heading} <b>{escape(title)}</b>\n\n"
        f"Produk: <b>{name}</b>\n"
        f"Harga: <b>{price}</b>"
        + (f"\nStock: <b>{int(stock)}</b>" if stock is not None else "")
        + (f"\n\n{description}" if description else "")
        + "\n\n🛒 Order: @Idse_MarketBot"
    )

    image = None
    if settings.get("broadcast_auto_image_enabled", False):
        try:
            from broadcast_image import render_product_image
            image = render_product_image(
                product.get("name") or "Product",
                price,
                stock,
                product.get("description") or "",
                title=title.upper(),
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Generate product notification image gagal")

    if image:
        return await send_photo_bytes(channel_id, image, "product-update.jpg", caption=body)
    return await send_message(channel_id, body)


async def notify_product_created(product: dict):
    settings = await get_settings()
    if not settings.get("auto_broadcast_new_product", False):
        return {"ok": False, "disabled": True}
    return await _product_channel_notification(product, "PRODUCT BARU", "🆕")


async def notify_product_stock_updated(product: dict, stock: int | None = None):
    settings = await get_settings()
    if not settings.get("auto_broadcast_new_product", False):
        return {"ok": False, "disabled": True}
    if stock is None:
        stock = await available_count(product["_id"])
    return await _product_channel_notification(product, "STOCK UPDATE", "📦", stock)
