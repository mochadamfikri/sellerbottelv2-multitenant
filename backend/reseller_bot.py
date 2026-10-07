"""One Telegram storefront implementation shared by every reseller bot."""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from html import escape

import httpx
from pymongo.errors import DuplicateKeyError

from bot import deliver_inventory, deliver_product
from checkout import execute_checkout, stock_for
from db import db, get_settings
from gopay_provider import create_gopay_payment
from inventory import decrypt_items
from join_gate import build_gate_keyboard, check_user_membership, clear_cache_for_user
from pricing import base_price
from reseller_service import (decrypt_token, parse_price_template, price_template,
                              sellable_products, telegram_call, wholesale_price)
from reseller_payout import commission_balance, maybe_request_payout, remind_payout
from services import fmt_amount, now_iso, notify_admin
from storage import put_object

logger = logging.getLogger(__name__)
_purchase_locks = {}


def _purchase_lock(bot_id, tid):
    key = (bot_id, tid)
    if key not in _purchase_locks:
        _purchase_locks[key] = asyncio.Lock()
    return _purchase_locks[key]


async def send(bot, tid, text, keyboard=None, persistent=False):
    member = None if persistent else await db.reseller_bot_users.find_one(
        {"bot_id": bot["_id"], "telegram_id": tid}, {"last_ui_message_id": 1})
    previous_id = (member or {}).get("last_ui_message_id")
    if previous_id:
        edit_payload = {"chat_id": tid, "message_id": previous_id, "text": text,
                        "parse_mode": "HTML", "disable_web_page_preview": True}
        if keyboard:
            edit_payload["reply_markup"] = keyboard
        edited = await telegram_call(decrypt_token(bot), "editMessageText", **edit_payload)
        if edited.get("ok") or "message is not modified" in (edited.get("description") or "").lower():
            return edited
    payload = {"chat_id": tid, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = keyboard
    sent = await telegram_call(decrypt_token(bot), "sendMessage", **payload)
    if sent.get("ok") and not persistent:
        new_id = (sent.get("result") or {}).get("message_id")
        if new_id:
            await db.reseller_bot_users.update_one({"bot_id": bot["_id"], "telegram_id": tid},
                                                   {"$set": {"last_ui_message_id": new_id}})
        if previous_id:
            try:
                await telegram_call(decrypt_token(bot), "deleteMessage", chat_id=tid, message_id=previous_id)
            except Exception:
                pass
    return sent


async def send_document(bot, tid, data, filename, caption=None):
    token = decrypt_token(bot)
    form = {"chat_id": str(tid)}
    if caption:
        form["caption"] = caption
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(f"https://api.telegram.org/bot{token}/sendDocument",
                                     data=form, files={"document": (filename, data, "application/octet-stream")})
        return response.json()


async def send_photo(bot, tid, image, filename, caption):
    token = decrypt_token(bot)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                                     data={"chat_id": str(tid), "caption": caption, "parse_mode": "HTML"},
                                     files={"photo": (filename, image, "image/jpeg")})
        return response.json()


async def download_file(bot, file_id, max_bytes=10_000_000):
    token = decrypt_token(bot)
    info = await telegram_call(token, "getFile", file_id=file_id)
    if not info.get("ok"):
        raise ValueError("File Telegram tidak dapat dibaca.")
    size = int((info.get("result") or {}).get("file_size") or 0)
    if size > max_bytes:
        raise ValueError("File terlalu besar.")
    path = info["result"]["file_path"]
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"https://api.telegram.org/file/bot{token}/{path}")
        response.raise_for_status()
        if len(response.content) > max_bytes:
            raise ValueError("File terlalu besar.")
        return response.content


def menu(bot, tid):
    return {"inline_keyboard": [
        [{"text": "📦 Katalog Produk", "callback_data": "catalog:0"},
         {"text": "💰 Saldo", "callback_data": "balance"}],
        [{"text": "➕ Deposit", "callback_data": "deposit"},
         {"text": "🧾 Pesanan Saya", "callback_data": "orders"}],
        *([[{"text": "⚙️ Atur Harga", "callback_data": "prices"},
            {"text": "💸 Komisi", "callback_data": "commission"}]]
          if tid == int(bot.get("admin_tid") or 0) else []),
    ]}


async def ensure_user(bot, tg_user):
    tid = int(tg_user["id"])
    user = await db.bot_users.find_one({"telegram_id": tid})
    if not user:
        user = {"_id": str(uuid.uuid4()), "telegram_id": tid,
                "username": tg_user.get("username", ""), "first_name": tg_user.get("first_name", ""),
                "currency": "IDR", "lang": "id", "balance_idr": 0.0, "balance_usd": 0.0,
                "frozen": False, "cart": [], "state": None, "state_data": {}, "created_at": now_iso()}
        try:
            await db.bot_users.insert_one(user)
        except DuplicateKeyError:
            user = await db.bot_users.find_one({"telegram_id": tid})
    await db.reseller_bot_users.update_one({"bot_id": bot["_id"], "telegram_id": tid},
                                          {"$set": {"username": tg_user.get("username", ""),
                                                    "first_name": tg_user.get("first_name", ""),
                                                    "last_seen_at": now_iso()},
                                           "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
    return user


async def set_state(bot, tid, state=None, data=None):
    await db.reseller_bot_users.update_one({"bot_id": bot["_id"], "telegram_id": tid},
                                          {"$set": {"state": state, "state_data": data or {}}})


async def current_price(bot, product):
    settings = await get_settings()
    public = int(await base_price(product, "IDR"))
    floor = wholesale_price(public, int(settings.get("reseller_wholesale_reduction_idr") or 2000))
    markup = int((bot.get("markups") or {}).get(str(product["_id"]), bot.get("default_markup_idr") or 0))
    selling = max(floor, public + markup)
    return {"public": public, "wholesale": floor, "selling": selling, "commission": selling - floor}


async def show_home(bot, tid):
    await send(bot, tid, f"👋 Selamat datang di <b>{escape(bot.get('name') or 'Toko Reseller')}</b>!\n"
                    "Pilih produk, isi saldo, dan pesan langsung di sini.", menu(bot, tid))


async def ensure_reseller_join(bot, tid, force_refresh=False):
    joined, missing = await check_user_membership(tid, force_refresh=force_refresh)
    if joined:
        return True
    await send(bot, tid, "📢 <b>Join channel SellerBottel terlebih dahulu</b>\n"
               "Setelah bergabung, tekan Saya sudah join untuk membuka katalog.",
               build_gate_keyboard(missing))
    return False


async def show_catalog(bot, tid, page=0):
    products = await sellable_products()
    page = max(0, min(page, max(0, (len(products) - 1) // 8)))
    shown = products[page * 8:page * 8 + 8]
    rows = []
    for item in shown:
        product = await db.products.find_one({"_id": item["id"]})
        pricing = await current_price(bot, product)
        rows.append([{"text": f"{item['name'][:35]} · {fmt_amount(pricing['selling'], 'IDR')}",
                      "callback_data": f"product:{item['id']}"}])
    nav = []
    if page:
        nav.append({"text": "⬅️", "callback_data": f"catalog:{page - 1}"})
    if (page + 1) * 8 < len(products):
        nav.append({"text": "➡️", "callback_data": f"catalog:{page + 1}"})
    if nav:
        rows.append(nav)
    rows.append([{"text": "🏠 Menu", "callback_data": "home"}])
    await send(bot, tid, f"📦 <b>Katalog Produk</b>\n{len(products)} produk tersedia."
               if products else "📭 Belum ada produk dengan stok tersedia.", {"inline_keyboard": rows})


async def show_product(bot, tid, product_id):
    product = await db.products.find_one({"_id": product_id, "active": True})
    if not product or (await stock_for(product)) == 0:
        await send(bot, tid, "⚠️ Produk tidak tersedia atau stok habis.")
        return
    pricing = await current_price(bot, product)
    description = escape(str(product.get("description") or "")[:900])
    text = (f"📦 <b>{escape(product.get('name') or 'Produk')}</b>\n"
            f"💰 Harga: <b>{fmt_amount(pricing['selling'], 'IDR')}</b>\n"
            f"📊 Stok: {'Tersedia' if (await stock_for(product)) is None else await stock_for(product)}"
            + (f"\n\n<blockquote>{description}</blockquote>" if description else ""))
    await send(bot, tid, text, {"inline_keyboard": [
        [{"text": "🛒 Beli 1", "callback_data": f"buy:{product_id}:1"}],
        [{"text": "📦 Lihat Katalog", "callback_data": "catalog:0"}],
    ]})


async def show_balance(bot, tid):
    user = await db.bot_users.find_one({"telegram_id": tid}, {"balance_idr": 1})
    await send(bot, tid, f"💰 Saldo IDR: <b>{fmt_amount(float((user or {}).get('balance_idr') or 0), 'IDR')}</b>",
               {"inline_keyboard": [[{"text": "➕ Deposit", "callback_data": "deposit"}],
                                    [{"text": "🏠 Menu", "callback_data": "home"}]]})


async def show_deposit(bot, tid):
    settings = await get_settings()
    rows = []
    if settings.get("qris_enabled") and os.environ.get("GOPAY_ENABLED", "").lower() in {"1", "true", "yes"}:
        rows.append([{"text": "📱 QRIS SellerBottel", "callback_data": "deposit:qris"}])
    if settings.get("bank_enabled") and settings.get("bank_account_number"):
        rows.append([{"text": "🏦 Rekening SellerBottel", "callback_data": "deposit:bank"}])
    rows.append([{"text": "🏠 Menu", "callback_data": "home"}])
    await send(bot, tid, "➕ <b>Deposit ke SellerBottel pusat</b>\nPilih metode pembayaran. Saldo dapat dipakai di bot reseller ini.",
               {"inline_keyboard": rows})


async def show_orders(bot, tid):
    orders = await db.purchases.find({"reseller_bot_id": bot["_id"], "user_tid": tid}).sort("created_at", -1).limit(10).to_list(10)
    if not orders:
        await send(bot, tid, "🧾 Belum ada pesanan di bot ini.", menu(bot, tid))
        return
    lines = ["🧾 <b>Pesanan Saya</b>"]
    for order in orders:
        lines.append(f"\n• <code>{escape(order.get('invoice_id') or order['_id'])}</code> · {fmt_amount(order.get('total') or 0, 'IDR')} · {escape(order.get('status') or '')}")
    await send(bot, tid, "\n".join(lines), menu(bot, tid))


async def record_commission(bot, order):
    await db.reseller_commissions.update_one({"_id": order["_id"]}, {"$setOnInsert": {
        "bot_id": bot["_id"], "owner_tid": bot["owner_tid"],
        "order_id": order["_id"], "invoice_id": order.get("invoice_id"),
        "amount": int(order.get("reseller_margin") or 0), "status": "pending_payout",
        "created_at": now_iso(),
    }}, upsert=True)
    fresh = await db.reseller_bots.find_one({"_id": bot["_id"]})
    payout = await maybe_request_payout(fresh)
    if payout:
        try:
            await remind_payout(payout)
        except Exception:
            logger.exception("Reseller payout reminder failed for %s", payout["_id"])


async def show_commission(bot, tid):
    if tid != int(bot.get("admin_tid") or 0):
        await send(bot, tid, "⛔ Hanya admin bot reseller yang dapat melihat komisi.")
        return
    balance = await commission_balance(bot["_id"])
    dest = bot.get("payout_destination") or {}
    await send(bot, tid,
               f"💸 <b>Komisi @{escape(bot.get('username') or '')}</b>\n"
               f"Belum dicairkan: <b>{fmt_amount(balance.get('pending_payout', 0), 'IDR')}</b>\n"
               f"Menunggu transfer: <b>{fmt_amount(balance.get('reserved', 0), 'IDR')}</b>\n"
               f"Sudah dibayar: <b>{fmt_amount(balance.get('paid', 0), 'IDR')}</b>\n\n"
               f"Ambang pencairan: <b>{fmt_amount(bot.get('payout_threshold_idr') or 50000, 'IDR')}</b>\n"
               f"Tujuan: {escape(dest.get('provider') or 'Belum diisi')} {escape(dest.get('number') or '')}\n\n"
               "Atur ambang: <code>/setkomisi 75000</code> (minimal Rp50.000)\n"
               "Atur rekening: <code>/rekening BANK|BCA|12345678|Nama Pemilik</code>\n"
               "Atur e-wallet: <code>/rekening EWALLET|DANA|08123456789|Nama Pemilik</code>\n\n"
               "🏦 Bank transfer dianjurkan. Pencairan ke e-wallet dipotong Rp2.500 sebagai biaya top up.")


async def buy(bot, tid, product_id, qty=1):
    async with _purchase_lock(bot["_id"], tid):
        bot = await db.reseller_bots.find_one({"_id": bot["_id"]})
        if not bot or bot.get("status") != "active" or (bot.get("expires_at") or "") <= now_iso():
            await send(bot, tid, "⏸️ Bot reseller sedang tidak aktif. Hubungi owner toko.")
            return
        product = await db.products.find_one({"_id": product_id, "active": True})
        if not product:
            await send(bot, tid, "⚠️ Produk tidak tersedia.")
            return
        qty = max(1, min(10, int(qty)))
        pricing = await current_price(bot, product)
        user = await db.bot_users.find_one({"telegram_id": tid})
        if not user or user.get("frozen"):
            await send(bot, tid, "⚠️ Akun tidak tersedia. Hubungi admin pusat.")
            return
        total = pricing["selling"] * qty
        if float(user.get("balance_idr") or 0) < total:
            await send(bot, tid, f"💰 Saldo belum cukup. Harga: {fmt_amount(total, 'IDR')}.\n"
                       "Deposit dulu lewat menu berikut.", {"inline_keyboard": [[{"text": "➕ Deposit", "callback_data": "deposit"}]]})
            return
        checkout_user = {**user, "currency": "IDR"}
        result = await execute_checkout(checkout_user, [{"pid": product_id, "qty": qty}],
                                        preserve_cart=True,
                                        unit_price_overrides={product_id: pricing["selling"]},
                                        order_metadata={"reseller_bot_id": bot["_id"],
                                                        "reseller_admin_tid": bot["admin_tid"],
                                                        "reseller_wholesale": pricing["wholesale"] * qty,
                                                        "reseller_margin": pricing["commission"] * qty})
        if not result.get("ok"):
            await send(bot, tid, "⚠️ Checkout gagal. Periksa saldo atau stok lalu coba lagi.")
            return
        order = result["order"]
        await send(bot, tid, f"✅ Pembayaran diterima. Invoice <code>{escape(order['invoice_id'])}</code>\n"
                   f"Total: <b>{fmt_amount(total, 'IDR')}</b>", persistent=True)
        try:
            await notify_admin(f"🛒 <b>Penjualan melalui bot reseller</b>\n"
                               f"Bot: @{escape(bot.get('username') or '')}\n"
                               f"Owner: <code>{bot['owner_tid']}</code> · Pembeli: <code>{tid}</code>\n"
                               f"Invoice: <code>{escape(order['invoice_id'])}</code>\n"
                               f"Produk: {escape(product.get('name') or 'Produk')} ×{qty}\n"
                               f"Total: <b>{fmt_amount(total, 'IDR')}</b> · "
                               f"Komisi: <b>{fmt_amount(pricing['commission'] * qty, 'IDR')}</b>")
        except Exception:
            logger.exception("Central reseller sale notification failed for %s", order["_id"])
        async def child_send(chat_id, text, kb=None):
            return await send(bot, chat_id, text, kb, persistent=True)
        async def child_doc(chat_id, data, filename, caption=None):
            return await send_document(bot, chat_id, data, filename, caption)
        allocation = next((row for row in result.get("allocations", []) if row["product_id"] == product_id), None)
        if product.get("product_kind") == "service" or product.get("delivery_type") == "service":
            await db.purchases.update_one({"_id": order["_id"]}, {"$set": {"status": "service_waiting"}})
            await send(bot, tid, "🛎️ Pesanan jasa diterima. Admin akan memproses pesanan ini.", persistent=True)
            await notify_admin(f"🛎️ Jasa reseller @{escape(bot['username'])}\nInvoice: <code>{escape(order['invoice_id'])}</code>\nCustomer: <code>{tid}</code>")
            return
        if allocation and allocation["kind"] == "inventory":
            delivered = await deliver_inventory(tid, product, decrypt_items(allocation.get("items", [])),
                                                send_message_fn=child_send, send_document_fn=child_doc)
        else:
            delivered = True
            for _ in range(qty):
                delivered = (await deliver_product(tid, product, "id", send_message_fn=child_send,
                                                   send_document_fn=child_doc)) and delivered
        await db.purchases.update_one({"_id": order["_id"]}, {"$set": {
            "status": "delivered" if delivered else "delivery_failed",
            "delivered_at": now_iso() if delivered else None,
            "delivery_error": None if delivered else "Pengiriman otomatis gagal.",
        }})
        if delivered:
            await record_commission(bot, order)
            await send(bot, tid, "✅ Produk berhasil dikirim. Terima kasih sudah berbelanja!", persistent=True)
        else:
            await send(bot, tid, "⚠️ Pembayaran berhasil, tetapi pengiriman perlu bantuan admin.", persistent=True)


async def start_bank_deposit(bot, tid, amount):
    settings = await get_settings()
    await set_state(bot, tid, "bank_proof", {"amount": amount})
    await send(bot, tid, f"🏦 Transfer <b>{fmt_amount(amount, 'IDR')}</b> ke rekening SellerBottel:\n"
               f"{escape(settings.get('bank_name') or '')} · <code>{escape(settings.get('bank_account_number') or '')}</code>\n"
               f"a.n. {escape(settings.get('bank_account_holder') or '')}\n\n"
               "Lalu kirim foto atau dokumen bukti transfer di chat ini. Admin pusat akan memeriksa.")


async def receive_bank_proof(bot, tid, state_data, message):
    photo = (message.get("photo") or [])[-1:]
    file = photo[0] if photo else message.get("document")
    if not file:
        await send(bot, tid, "Kirim foto atau dokumen bukti transfer.")
        return
    if not photo and file.get("mime_type") not in {"image/jpeg", "image/png", "image/webp"}:
        await send(bot, tid, "Bukti transfer harus berupa gambar JPG, PNG, atau WebP.")
        return
    data = await download_file(bot, file["file_id"])
    content_type = "image/jpeg" if photo else file.get("mime_type") or "application/octet-stream"
    dep_id = str(uuid.uuid4())
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type]
    stored = await put_object(f"reseller_proofs/{dep_id}{suffix}", data, content_type)
    await db.deposits.insert_one({"_id": dep_id, "user_tid": tid, "reseller_bot_id": bot["_id"],
                                  "method": "bank", "currency": "IDR", "amount": state_data["amount"],
                                  "credited_amount": state_data["amount"], "proof_storage_path": stored["path"],
                                  "status": "pending", "auto_verified": False, "created_at": now_iso()})
    await set_state(bot, tid)
    await send(bot, tid, f"🧾 Bukti diterima. ID deposit <code>{dep_id}</code>."
               " Saldo masuk setelah admin pusat menyetujui.", persistent=True)
    await notify_admin(f"🏦 Deposit bank dari bot reseller @{escape(bot['username'])}\n"
                       f"ID: <code>{dep_id}</code>\nUser: <code>{tid}</code>\n"
                       f"Nominal: {fmt_amount(state_data['amount'], 'IDR')}")


async def handle_message(bot, message):
    tg_user = message.get("from") or {}
    if not tg_user or tg_user.get("is_bot") or message.get("chat", {}).get("type") != "private":
        return
    tid = int(tg_user["id"])
    await ensure_user(bot, tg_user)
    text = (message.get("text") or "").strip()
    is_admin = tid == int(bot.get("admin_tid") or 0)
    if text in {"/settharga", "/setharga"}:
        if not is_admin:
            await send(bot, tid, "⛔ Hanya admin bot reseller yang dapat mengatur harga.")
            return
        template = await price_template(bot)
        await send_document(bot, tid, template, "template_harga_reseller.txt",
                            "✏️ Edit kolom harga_jual pada file ini lalu kirim kembali .txt. "
                            "Atau balas angka markup seperti 5000 untuk seluruh produk.")
        await set_state(bot, tid, "await_prices")
        await send(bot, tid, "💡 <b>Cara cepat</b>\n"
                   "Komisi awal Rp2.000/unit. Balas <code>5000</code> untuk menaikkan harga jual "
                   "Rp5.000 dari harga pusat; komisi menjadi Rp7.000/unit.\n\n"
                   "📄 <b>Cara detail</b>\nBuka file .txt di atas, ubah kolom terakhir "
                   "<code>harga_jual</code> sesuai produk, simpan sebagai TXT UTF-8, lalu kirim kembali di sini. "
                   "Produk baru mengikuti <code>DEFAULT_MARKUP_IDR</code>.")
        return
    if text == "/komisi":
        await show_commission(bot, tid)
        return
    if text.startswith("/setkomisi "):
        if not is_admin:
            await send(bot, tid, "⛔ Hanya admin bot reseller yang dapat mengatur komisi.")
            return
        try:
            threshold = int(text.split(" ", 1)[1].strip().replace(".", ""))
        except ValueError:
            threshold = 0
        if not 50_000 <= threshold <= 1_000_000_000:
            await send(bot, tid, "Masukkan angka minimal 50000, contoh <code>/setkomisi 75000</code>.")
            return
        await db.reseller_bots.update_one({"_id": bot["_id"]}, {"$set": {"payout_threshold_idr": threshold}})
        fresh = await db.reseller_bots.find_one({"_id": bot["_id"]})
        payout = await maybe_request_payout(fresh)
        if payout:
            await remind_payout(payout)
        await send(bot, tid, f"✅ Ambang pencairan sekarang {fmt_amount(threshold, 'IDR')}.")
        return
    if text.startswith("/rekening "):
        if not is_admin:
            await send(bot, tid, "⛔ Hanya admin bot reseller yang dapat mengatur tujuan transfer.")
            return
        parts = [value.strip() for value in text.split(" ", 1)[1].split("|")]
        if (len(parts) != 4 or parts[0].upper() not in {"BANK", "EWALLET"}
                or not parts[1] or not parts[2].replace("+", "").isdigit()
                or not 6 <= len(parts[2]) <= 30 or not parts[3]):
            await send(bot, tid, "Format: <code>/rekening BANK|BCA|12345678|Nama Pemilik</code>\n"
                       "atau <code>/rekening EWALLET|DANA|08123456789|Nama Pemilik</code>.")
            return
        dest = {"type": parts[0].upper(), "provider": parts[1][:50],
                "number": parts[2], "name": parts[3][:100]}
        await db.reseller_bots.update_one({"_id": bot["_id"]}, {"$set": {"payout_destination": dest}})
        fresh = await db.reseller_bots.find_one({"_id": bot["_id"]})
        payout = await maybe_request_payout(fresh)
        if payout:
            await remind_payout(payout)
        await send(bot, tid, "✅ Tujuan transfer tersimpan. Komisi akan diminta saat mencapai ambang.\n"
                   + ("⚠️ E-wallet dipotong Rp2.500 per pencairan. Bank transfer lebih dianjurkan."
                      if dest["type"] == "EWALLET" else "🏦 Bank transfer tidak dikenai potongan e-wallet."))
        return
    if text.startswith("/start") or text == "/menu":
        await set_state(bot, tid)
        await show_home(bot, tid)
        return
    member = await db.reseller_bot_users.find_one({"bot_id": bot["_id"], "telegram_id": tid})
    state = (member or {}).get("state")
    if state == "await_prices" and is_admin:
        if text and text.replace(".", "").isdigit():
            markup = int(text.replace(".", ""))
            if markup > 100_000_000:
                await send(bot, tid, "Markup terlalu besar. Maksimal Rp100.000.000.")
                return
            await db.reseller_bots.update_one({"_id": bot["_id"]}, {"$set": {
                "default_markup_idr": markup, "markups": {}, "updated_at": now_iso(),
            }})
            await set_state(bot, tid)
            settings = await get_settings()
            base_commission = int(settings.get("reseller_wholesale_reduction_idr") or 2000)
            await send(bot, tid, f"✅ Semua produk memakai markup {fmt_amount(markup, 'IDR')} "
                       f"dari harga pusat. Komisi per unit sekarang "
                       f"<b>{fmt_amount(base_commission + markup, 'IDR')}</b>. "
                       "Produk baru otomatis mengikuti markup ini.")
            return
        document = message.get("document")
        if not document or not (document.get("file_name") or "").lower().endswith(".txt"):
            await send(bot, tid, "Kirim file template berakhiran .txt.")
            return
        try:
            data = await download_file(bot, document["file_id"], max_bytes=256_000)
            parsed = await parse_price_template(bot, data)
        except ValueError as exc:
            await send(bot, tid, f"⚠️ {escape(str(exc))}")
            return
        await db.reseller_bots.update_one({"_id": bot["_id"]}, {"$set": {
            "markups": parsed["markups"], "default_markup_idr": parsed["default_markup_idr"],
            "updated_at": now_iso(),
        }})
        await set_state(bot, tid)
        await send(bot, tid, f"✅ Harga {len(parsed['markups'])} produk tersimpan. Produk baru memakai markup default "
                   f"{fmt_amount(parsed['default_markup_idr'], 'IDR')}.")
        return
    if state == "deposit_amount_qris" or state == "deposit_amount_bank":
        try:
            amount = int(text.replace(".", ""))
        except ValueError:
            await send(bot, tid, "Masukkan nominal angka, contoh: 50000.")
            return
        settings = await get_settings()
        if amount < int(settings.get("min_deposit_idr") or 50000):
            await send(bot, tid, f"Minimal deposit {fmt_amount(settings.get('min_deposit_idr') or 50000, 'IDR')}.")
            return
        await set_state(bot, tid)
        if state == "deposit_amount_bank":
            await start_bank_deposit(bot, tid, amount)
            return
        user = await db.bot_users.find_one({"telegram_id": tid})
        try:
            payment = await create_gopay_payment(user, amount)
            await db.deposits.update_one({"_id": payment["deposit"]["_id"]},
                                         {"$set": {"reseller_bot_id": bot["_id"]}})
            await send_photo(bot, tid, payment["image"], "deposit-qris.jpg",
                             f"📱 <b>QRIS SellerBottel</b>\nIsi saldo: {fmt_amount(amount, 'IDR')}\n"
                             f"Total dibayar termasuk biaya QRIS: <b>{fmt_amount(payment['payment_amount'], 'IDR')}</b>\n"
                             "Saldo masuk otomatis setelah pembayaran terverifikasi.")
        except Exception:
            logger.exception("Reseller QRIS deposit failed for bot %s", bot["_id"])
            await send(bot, tid, "⚠️ Gagal membuat QRIS. Coba lagi nanti.")
        return
    if state == "bank_proof":
        await receive_bank_proof(bot, tid, member.get("state_data") or {}, message)
        return
    if text == "/produk":
        await show_catalog(bot, tid)
    elif text == "/saldo":
        await show_balance(bot, tid)
    elif text == "/deposit":
        await show_deposit(bot, tid)
    elif text == "/pesanan":
        await show_orders(bot, tid)
    else:
        await show_home(bot, tid)


async def handle_callback(bot, callback):
    tg_user = callback.get("from") or {}
    message = callback.get("message") or {}
    if message.get("chat", {}).get("type") != "private":
        return
    tid = int(tg_user["id"])
    await ensure_user(bot, tg_user)
    await telegram_call(decrypt_token(bot), "answerCallbackQuery", callback_query_id=callback["id"])
    data = callback.get("data") or ""
    if data == "home":
        await show_home(bot, tid)
    elif data.startswith("catalog:"):
        await show_catalog(bot, tid, int(data.split(":", 1)[1]))
    elif data.startswith("product:"):
        await show_product(bot, tid, data.split(":", 1)[1])
    elif data.startswith("buy:"):
        _, product_id, qty = data.split(":", 2)
        await buy(bot, tid, product_id, int(qty))
    elif data == "balance":
        await show_balance(bot, tid)
    elif data == "deposit":
        await show_deposit(bot, tid)
    elif data in {"deposit:qris", "deposit:bank"}:
        await set_state(bot, tid, "deposit_amount_qris" if data == "deposit:qris" else "deposit_amount_bank")
        await send(bot, tid, "Masukkan nominal deposit IDR, contoh <code>50000</code>.")
    elif data == "orders":
        await show_orders(bot, tid)
    elif data == "prices":
        if tid == int(bot.get("admin_tid") or 0):
            await send(bot, tid, "Ketik <code>/settharga</code> untuk mengunduh template harga.")
        else:
            await send(bot, tid, "⛔ Hanya admin bot reseller yang dapat mengatur harga.")
    elif data == "commission":
        await show_commission(bot, tid)


async def process_reseller_update(bot, update):
    try:
        if bot.get("status") != "active" or (bot.get("expires_at") or "") <= now_iso():
            message = update.get("message") or {}
            callback = update.get("callback_query") or {}
            actor = message.get("from") or callback.get("from") or {}
            tid = actor.get("id")
            text = (message.get("text") or "").strip()
            is_admin = tid and tid == bot.get("admin_tid")
            member = await db.reseller_bot_users.find_one({"bot_id": bot["_id"], "telegram_id": tid}) if is_admin else None
            admin_action = (text in {"/settharga", "/setharga", "/komisi"}
                            or text.startswith(("/setkomisi ", "/rekening "))
                            or (member or {}).get("state") == "await_prices")
            if is_admin and admin_action:
                await handle_message(bot, message)
            elif tid:
                await send(bot, tid, "⏸️ Langganan bot reseller sedang tidak aktif. "
                           "Pembelian dan deposit tersedia lagi setelah owner memperpanjang langganan.")
            return
        if "message" in update:
            actor = (update["message"].get("from") or {}).get("id")
            if actor and not await ensure_reseller_join(bot, int(actor)):
                return
            await handle_message(bot, update["message"])
        elif "callback_query" in update:
            callback = update["callback_query"]
            actor = (callback.get("from") or {}).get("id")
            if callback.get("data") == "gate:check":
                if actor:
                    await telegram_call(decrypt_token(bot), "answerCallbackQuery", callback_query_id=callback["id"])
                    clear_cache_for_user(int(actor))
                    if await ensure_reseller_join(bot, int(actor), force_refresh=True):
                        await show_home(bot, int(actor))
                return
            if actor and not await ensure_reseller_join(bot, int(actor)):
                await telegram_call(decrypt_token(bot), "answerCallbackQuery", callback_query_id=callback["id"])
                return
            await handle_callback(bot, update["callback_query"])
    except Exception:
        logger.exception("Reseller update failed for bot %s", bot.get("_id"))
