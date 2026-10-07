"""Shared configuration, token handling, pricing, and activation for reseller bots."""
import calendar
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from html import escape

import httpx
from checkout import stock_for
from db import db, get_settings
from inventory import _fernet
from pricing import base_price
from services import fmt_amount, now_iso


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(bot: dict) -> str:
    return _fernet().decrypt(bot["token_encrypted"].encode()).decode()


async def telegram_call(token: str, method: str, **payload):
    """Sandbox-hardened Telegram API call for arbitrary bot tokens.

    Mirrors tgapi._client: trust_env=False because the sandbox NO_PROXY
    carries bracketed IPv6 entries this httpx version cannot parse
    ("Invalid port" errors); proxy and CA bundle are set explicitly
    (the proxy MITMs TLS with a custom CA).
    """
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    verify = os.environ.get("SSL_CERT_FILE") or True
    async with httpx.AsyncClient(timeout=30, proxy=proxy,
                                 trust_env=False, verify=verify) as client:
        response = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload)
        return response.json()


async def validate_token(token: str) -> dict:
    token = token.strip()
    if not re.fullmatch(r"\d{5,15}:[A-Za-z0-9_-]{30,}", token):
        raise ValueError("Format token Telegram tidak valid.")
    if token in {os.environ.get("TELEGRAM_TOKEN"), os.environ.get("BOT2_TELEGRAM_TOKEN")}:
        raise ValueError("Token ini sudah digunakan bot utama.")
    try:
        result = await telegram_call(token, "getMe")
    except (httpx.HTTPError, ValueError) as exc:
        raise ValueError("Token tidak dapat diverifikasi ke Telegram.") from exc
    if not result.get("ok") or not (result.get("result") or {}).get("is_bot"):
        raise ValueError("Token bot tidak valid.")
    return result["result"]


def activation_fees(settings: dict) -> dict:
    bot_price = max(0, int(settings.get("reseller_bot_price_idr") or 0))
    admin_fee = max(0, int(settings.get("reseller_admin_fee_idr") or 0))
    platform_fee = max(0, int(settings.get("reseller_platform_fee_idr") or 0))
    return {"bot_price": bot_price, "admin_fee": admin_fee, "platform_fee": platform_fee,
            "total": bot_price + admin_fee + platform_fee}


async def create_draft(owner_tid: int, token: str) -> dict:
    info = await validate_token(token)
    bot_tid = int(info["id"])
    existing = await db.reseller_bots.find_one({"telegram_bot_id": bot_tid})
    if existing:
        raise ValueError("Bot ini sudah terdaftar.")
    bot = {"_id": str(uuid.uuid4()), "telegram_bot_id": bot_tid,
           "username": info.get("username") or "", "name": info.get("first_name") or "Bot Reseller",
           "owner_tid": owner_tid, "admin_tid": None, "token_encrypted": encrypt_token(token),
           "webhook_secret": secrets.token_urlsafe(32), "status": "draft", "markups": {},
           "default_markup_idr": 0,
           "created_at": now_iso(), "activated_at": None}
    await db.reseller_bots.insert_one(bot)
    return bot


async def finalize_draft(bot: dict, admin_tid: int) -> dict:
    settings = await get_settings()
    if not settings.get("reseller_enabled", False):
        raise ValueError("Pembuatan bot reseller belum dibuka oleh admin.")
    fees = activation_fees(settings)
    if fees["total"] <= 0:
        raise ValueError("Biaya aktivasi belum diatur oleh admin.")
    cycle_id = str(uuid.uuid4())
    await db.reseller_bots.update_one({"_id": bot["_id"], "status": "draft"},
                                      {"$set": {"admin_tid": admin_tid, "status": "pending_payment",
                                                "fees": fees, "cycle_id": cycle_id,
                                                "updated_at": now_iso()}})
    return {**bot, "admin_tid": admin_tid, "status": "pending_payment", "fees": fees,
            "cycle_id": cycle_id}


def fee_text(bot: dict) -> str:
    fees = bot["fees"]
    return (f"🤖 <b>Langganan bulanan @{escape(bot['username'])}</b>\n\n"
            f"Harga bot reseller / bulan: <b>{fmt_amount(fees['bot_price'], 'IDR')}</b>\n"
            f"Admin fee: <b>{fmt_amount(fees['admin_fee'], 'IDR')}</b>\n"
            f"Admin platform: <b>{fmt_amount(fees['platform_fee'], 'IDR')}</b>\n"
            f"Total: <b>{fmt_amount(fees['total'], 'IDR')}</b>\n\n"
            "Masa aktif satu bulan kalender. Setelah pembayaran terkonfirmasi, bot akan diaktifkan otomatis.\n"
            "⚠️ Tanpa penjualan berbayar 14 hari, bot dinonaktifkan tanpa pengembalian biaya langganan.")


def next_month(value: datetime) -> datetime:
    year = value.year + (value.month == 12)
    month = value.month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


async def begin_renewal(bot: dict) -> dict:
    if bot.get("status") not in {"active", "expired", "paused", "inactive_no_sales"} or bot.get("renewal_pending"):
        raise ValueError("Perpanjangan bot ini belum tersedia atau sedang menunggu pembayaran.")
    settings = await get_settings()
    fees = activation_fees(settings)
    if fees["total"] <= 0:
        raise ValueError("Biaya langganan belum diatur admin.")
    cycle_id = str(uuid.uuid4())
    await db.reseller_bots.update_one({"_id": bot["_id"]}, {"$set": {
        "renewal_pending": True, "fees": fees, "cycle_id": cycle_id, "updated_at": now_iso(),
    }})
    return {**bot, "renewal_pending": True, "fees": fees, "cycle_id": cycle_id}


async def configure_webhook(bot: dict) -> None:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not base.startswith("https://"):
        raise RuntimeError("PUBLIC_BASE_URL HTTPS belum dikonfigurasi.")
    result = await telegram_call(decrypt_token(bot), "setWebhook",
                                 url=f"{base}/api/telegram/reseller/{bot['_id']}/webhook",
                                 secret_token=bot["webhook_secret"],
                                 allowed_updates=["message", "callback_query"])
    if not result.get("ok"):
        raise RuntimeError(result.get("description") or "Telegram menolak webhook.")


async def activate_paid_bot(bot: dict) -> bool:
    """Charge the quoted fee once, then register the webhook. Safe to retry."""
    if bot.get("status") not in {"pending_payment", "active", "expired", "paused", "inactive_no_sales", "activating"}:
        return False
    if bot.get("status") in {"active", "paused", "inactive_no_sales"} and not bot.get("renewal_pending"):
        return False
    total = int((bot.get("fees") or {}).get("total") or 0)
    cycle_id = bot.get("cycle_id")
    if total <= 0 or not cycle_id:
        return False
    user = await db.bot_users.find_one({"telegram_id": bot["owner_tid"]}, {"reseller_charge_ids": 1})
    already_charged = cycle_id in (user or {}).get("reseller_charge_ids", [])
    if not already_charged and float((await db.bot_users.find_one({"telegram_id": bot["owner_tid"]}) or {}).get("balance_idr") or 0) < total:
        return False
    stale = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    claim = await db.reseller_bots.update_one(
        {"_id": bot["_id"], "cycle_id": cycle_id,
         "$and": [{"$or": [{"status": {"$in": ["pending_payment", "activating"]}},
                            {"renewal_pending": True}]},
                  {"$or": [{"activation_lock": {"$ne": True}},
                            {"activation_lock_at": {"$lte": stale}}]}]},
        {"$set": {"activation_lock": True, "activation_lock_at": now_iso(), "updated_at": now_iso()}},
    )
    if not claim.modified_count:
        return False
    try:
        if bot.get("status") != "active":
            await configure_webhook(bot)
        charged = await db.bot_users.update_one(
            {"telegram_id": bot["owner_tid"], "balance_idr": {"$gte": total},
             "reseller_charge_ids": {"$ne": cycle_id}},
            {"$inc": {"balance_idr": -total}, "$addToSet": {"reseller_charge_ids": cycle_id}},
        )
        if not charged.modified_count and not already_charged:
            return False
        start = datetime.now(timezone.utc)
        old_expiry = bot.get("expires_at")
        if old_expiry:
            try:
                old = datetime.fromisoformat(old_expiry)
                if old > start:
                    start = old
            except ValueError:
                pass
        expiry = next_month(start).isoformat()
        await db.reseller_bots.update_one({"_id": bot["_id"], "cycle_id": cycle_id},
                                          {"$set": {"status": "active", "expires_at": expiry,
                                                    "activated_at": bot.get("activated_at") or now_iso(),
                                                    "last_cycle_paid_at": now_iso(),
                                                    "updated_at": now_iso(), "renewal_pending": False},
                                           "$unset": {"expiry_reminder_at": "", "activation_deposit_id": ""}})
        await db.reseller_payments.update_one({"_id": cycle_id}, {"$setOnInsert": {
            "bot_id": bot["_id"], "owner_tid": bot["owner_tid"], "fees": bot["fees"],
            "amount": total, "created_at": now_iso(), "expires_at": expiry,
        }}, upsert=True)
    finally:
        await db.reseller_bots.update_one({"_id": bot["_id"], "cycle_id": cycle_id},
                                          {"$unset": {"activation_lock": "", "activation_lock_at": ""}})
    return True


async def sellable_products() -> list[dict]:
    products = []
    async for product in db.products.find({"active": True}).sort("name", 1):
        stock = await stock_for(product)
        if stock is not None and stock <= 0:
            continue
        products.append({"id": str(product["_id"]), "name": str(product.get("name") or "Produk"),
                         "stock": stock, "public_price": int(await base_price(product, "IDR"))})
    return products


def wholesale_price(public_price: int, reduction: int) -> int:
    return max(0, public_price - max(0, reduction))


async def price_template(bot: dict) -> bytes:
    settings = await get_settings()
    reduction = int(settings.get("reseller_wholesale_reduction_idr") or 2000)
    lines = ["# TEMPLATE HARGA BOT RESELLER",
             "# Ubah DEFAULT_MARKUP_IDR untuk produk baru; ubah harga_jual untuk produk tertentu.",
             "# Harga jual ikut bergerak jika harga pusat berubah; selisih harga tersimpan sebagai markup.",
             "# Harga jual tidak boleh lebih rendah dari harga modal.",
             "# Contoh: harga pusat 10000, modal 8000, harga jual 15000 = komisi 7000 per unit.",
             "# Simpan sebagai TXT UTF-8 dan kirim kembali ke bot ini.",
             "# Format: id_produk|nama_produk|harga_modal|harga_jual",
             f"DEFAULT_MARKUP_IDR={int(bot.get('default_markup_idr') or 0)}",
             "id_produk|nama_produk|harga_modal|harga_jual"]
    for item in await sellable_products():
        modal = wholesale_price(item["public_price"], reduction)
        markup = int((bot.get("markups") or {}).get(item["id"], bot.get("default_markup_idr") or 0))
        selling = max(modal, item["public_price"] + markup)
        lines.append(f"{item['id']}|{item['name'].replace('|', '/')}|{modal}|{selling}")
    return ("\n".join(lines) + "\n").encode("utf-8")


async def parse_price_template(bot: dict, data: bytes) -> dict[str, int]:
    if len(data) > 256_000:
        raise ValueError("File harga terlalu besar.")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("File harus berformat UTF-8 .txt.") from exc
    products = {row["id"]: row for row in await sellable_products()}
    settings = await get_settings()
    reduction = int(settings.get("reseller_wholesale_reduction_idr") or 2000)
    markups = dict(bot.get("markups") or {})
    default_markup = int(bot.get("default_markup_idr") or 0)
    changed = 0
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("id_produk|"):
            continue
        if line.startswith("DEFAULT_MARKUP_IDR="):
            try:
                default_markup = int(line.split("=", 1)[1].strip().replace(".", ""))
            except ValueError as exc:
                raise ValueError("DEFAULT_MARKUP_IDR harus angka bulat.") from exc
            if not -reduction <= default_markup <= 100_000_000:
                raise ValueError("DEFAULT_MARKUP_IDR di luar batas harga yang diizinkan.")
            continue
        cells = [value.strip() for value in line.split("|")]
        if len(cells) != 4 or cells[0] not in products:
            raise ValueError("Ada baris dengan ID produk atau format yang tidak valid.")
        try:
            selling = int(cells[3].replace(".", ""))
        except ValueError as exc:
            raise ValueError(f"Harga jual {cells[1]} harus angka bulat.") from exc
        floor = wholesale_price(products[cells[0]]["public_price"], reduction)
        if selling < floor:
            raise ValueError(f"Harga jual {products[cells[0]]['name']} minimal {fmt_amount(floor, 'IDR')}.")
        markups[cells[0]] = selling - products[cells[0]]["public_price"]
        changed += 1
    if changed == 0 and default_markup == int(bot.get("default_markup_idr") or 0):
        raise ValueError("File tidak berisi perubahan harga atau markup.")
    return {"markups": markups, "default_markup_idr": default_markup}
