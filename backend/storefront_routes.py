"""Customer storefront endpoints backed by the existing Telegram users and orders."""
import hashlib
import hmac
import base64
import io
import os
import re
import secrets
import smtplib
import asyncio
import logging
import uuid
import zipfile
from email.message import EmailMessage
from html import escape
from datetime import datetime, timezone, timedelta
from email_validator import validate_email, EmailNotValidError
from pymongo import ReturnDocument

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ConfigDict, field_validator

from auth import JWT_ALGORITHM, get_jwt_secret
from db import db, get_settings
from product_catalog import catalog_name
from product_artwork import artwork_urls, image_response
from pricing import price_for_product
from checkout import stock_for
from storage import get_object
from inventory import decrypt_items
from services import fmt_amount

router = APIRouter(prefix="/api/store")
logger = logging.getLogger("storefront")


def _utc_datetime(value, fallback=None):
    if not isinstance(value, datetime):
        return fallback or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _email_code_hash(email: str, code: str) -> str:
    return hmac.new(get_jwt_secret().encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


async def _send_email_code(email: str, code: str, purpose: str):
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", "").strip() or user
    if not all((host, user, password, sender)):
        raise HTTPException(503, "Pengiriman email belum dikonfigurasi. Admin perlu mengisi SMTP di server.")
    msg = EmailMessage()
    msg["Subject"] = "Kode verifikasi IDSE Digital Product" if purpose == "register" else "Kode reset kata sandi IDSE Digital Product"
    msg["From"] = f"{os.getenv('SMTP_FROM_NAME', 'IDSE verification-noreply')} <{sender}>"
    msg["To"] = email
    msg.set_content(f"Kode verifikasi IDSE Digital Product: {code}\n\nKode berlaku 10 menit. Jangan bagikan kode ini kepada siapa pun.")
    port = int(os.getenv("SMTP_PORT", "587"))
    use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() in {"1", "true", "yes"}
    def deliver():
        cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with cls(host, port, timeout=15) as server:
            if not use_ssl:
                server.starttls()
            server.login(user, password)
            server.send_message(msg)
    try:
        await asyncio.to_thread(deliver)
    except Exception:
        logger.exception("Store email OTP delivery failed")
        raise HTTPException(502, "Email kode verifikasi gagal dikirim. Periksa konfigurasi SMTP.")


def _safe_attachment_name(value: str, fallback: str) -> str:
    name = os.path.basename(str(value or "")).replace("\x00", "")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name[:100] or fallback


def _format_order_attachments(order: dict, purchased: dict[str, list[dict]]):
    session_zip = io.BytesIO()
    session_archive = zipfile.ZipFile(session_zip, "w", compression=zipfile.ZIP_DEFLATED)
    session_count = 0
    account_lines = []
    for item in order.get("items") or []:
        product_id = str(item.get("product_id") or "")
        records = purchased.get(product_id, [])
        if not records:
            continue
        product = item.get("_product") or {}
        schema = [str(field) for field in (product.get("inventory_schema") or []) if not str(field).startswith("__")]
        for index, record in enumerate(records, 1):
            file_data = record.get("__file_data_b64")
            file_name = record.get("__file_name")
            if file_data and file_name:
                try:
                    payload = base64.b64decode(file_data, validate=True)
                except Exception as exc:
                    raise ValueError("File sesi produk tidak dapat dibaca.") from exc
                safe_name = _safe_attachment_name(file_name, f"session-{session_count + 1}.session")
                if safe_name in {".", ".."}:
                    safe_name = f"session-{session_count + 1}.session"
                session_archive.writestr(f"{_safe_attachment_name(item.get('name'), 'produk')}/{safe_name}", payload)
                session_count += 1
                continue
            fields = schema or [key for key in record if not str(key).startswith("__")]
            account_lines.append(f"PRODUK: {item.get('name') or 'Produk'} · ITEM {index}")
            for field in fields:
                if field in record:
                    account_lines.append(f"{field}: {record[field]}")
            account_lines.append("")

    session_archive.close()
    attachments = []
    invoice = _safe_attachment_name(order.get("invoice_id"), str(order.get("_id")))
    if session_count:
        attachments.append((f"invoice-{invoice}.zip", "application", "zip", session_zip.getvalue()))
    if account_lines:
        attachments.append((f"invoice-{invoice}.txt", "text", "plain", "\n".join(account_lines).encode("utf-8")))
    return attachments


async def send_order_completion_email(order_id: str) -> bool:
    """Send a completed web order receipt once and attach only its sold inventory."""
    order = await db.purchases.find_one({"_id": order_id, "status": "delivered"})
    if not order:
        return False
    customer = await db.store_customers.find_one({"_id": order.get("customer_id")}) if order.get("customer_id") else None
    email = str(order.get("customer_email") or (customer or {}).get("email") or "").strip()
    if not email:
        return False
    claimed = await db.purchases.update_one(
        {"_id": order_id, "status": "delivered", "delivery_email_status": {"$exists": False}},
        {"$set": {"delivery_email_status": "sending", "delivery_email_started_at": datetime.now(timezone.utc)}},
    )
    if claimed.modified_count != 1:
        return False

    try:
        by_product = {}
        for item in order.get("items") or []:
            product = await db.products.find_one({"_id": item.get("product_id")}, {
                "inventory_schema": 1, "inventory_mode": 1, "product_kind": 1,
                "delivery_type": 1, "inventory_enabled": 1, "content": 1,
            })
            item["_product"] = product or {}
            if product and (product.get("product_kind") == "digital" or product.get("delivery_type") == "inventory" or product.get("inventory_enabled")):
                stored = await db.inventory_items.find({
                    "order_id": order_id, "product_id": item.get("product_id"), "status": "sold"
                }).sort("sold_at", 1).limit(max(1, int(item.get("qty") or 1))).to_list(max(1, int(item.get("qty") or 1)))
                if len(stored) != int(item.get("qty") or 1):
                    raise ValueError("Data inventory pesanan tidak lengkap.")
                by_product[str(item.get("product_id"))] = decrypt_items(stored)
        attachments = _format_order_attachments(order, by_product)
        host = os.getenv("SMTP_HOST", "").strip()
        user = os.getenv("SMTP_USER", "").strip()
        password = os.getenv("SMTP_PASSWORD", "")
        sender = os.getenv("SMTP_FROM", "").strip() or user
        if not all((host, user, password, sender)):
            raise RuntimeError("Konfigurasi SMTP belum lengkap.")

        currency = order.get("currency") or "IDR"
        customer_name = str(order.get("customer_name") or email.split("@", 1)[0])
        lines = [f"Halo {customer_name},", "", "Order kamu telah berhasil diselesaikan.", "", "Order Details"]
        html_items = []
        for item in order.get("items") or []:
            qty = int(item.get("qty") or 0)
            unit = fmt_amount(item.get("unit_price") or 0, currency)
            subtotal = fmt_amount(item.get("subtotal") or 0, currency)
            lines.extend([f"{item.get('name') or 'Produk'} × {qty}", f"Harga product: {unit}", f"Total harga product: {subtotal}", ""])
            html_items.append(f"<li><strong>{escape(str(item.get('name') or 'Produk'))}</strong> × {qty}<br>Harga/unit: {escape(unit)} · Subtotal: {escape(subtotal)}</li>")
            product = item.get("_product") or {}
            if product.get("content") and item.get("delivery_type") not in {"inventory", "service"}:
                fulfillment = str(product["content"])
                lines.extend(["Informasi produk:", fulfillment, ""])
                html_items.append(f"<li><strong>Informasi produk:</strong><br><pre>{escape(fulfillment)}</pre></li>")
        payment = "QRIS" if order.get("payment_method") == "qris" else "Saldo"
        total = fmt_amount(order.get("total") or 0, currency)
        created = str(order.get("created_at") or "-")
        lines.extend([f"Pembayaran: {payment}", "Status: Completed", f"Nomor Invoice: {order.get('invoice_id') or order_id}", f"Tanggal: {created}", f"Total: {total}"])
        msg = EmailMessage()
        msg["Subject"] = f"Order completed - {order.get('invoice_id') or order_id}"
        msg["From"] = f"IDSE Digital Product <{sender}>"
        msg["To"] = email
        msg.set_content("\n".join(lines))
        msg.add_alternative(
            "<html><body style='font-family:Arial,sans-serif;color:#1f2937'>"
            f"<h2>Order kamu telah berhasil diselesaikan</h2><p>Halo {escape(customer_name)},</p>"
            f"<ul>{''.join(html_items)}</ul><p><b>Pembayaran:</b> {payment}<br>"
            f"<b>Total:</b> {escape(total)}<br><b>Status:</b> Completed<br>"
            f"<b>Nomor Invoice:</b> {escape(str(order.get('invoice_id') or order_id))}<br>"
            f"<b>Tanggal:</b> {escape(created)}</p></body></html>", subtype="html")
        for filename, maintype, subtype, payload in attachments:
            msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
        port = int(os.getenv("SMTP_PORT", "587"))
        use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() in {"1", "true", "yes"}
        def deliver():
            cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
            with cls(host, port, timeout=20) as server:
                if not use_ssl:
                    server.starttls()
                server.login(user, password)
                server.send_message(msg)
        await asyncio.to_thread(deliver)
        await db.purchases.update_one({"_id": order_id, "delivery_email_status": "sending"},
            {"$set": {"delivery_email_status": "sent", "delivery_email_sent_at": datetime.now(timezone.utc)}})
        return True
    except Exception as exc:
        logger.exception("Order completion email failed for %s", order_id)
        await db.purchases.update_one({"_id": order_id, "delivery_email_status": "sending"},
            {"$set": {"delivery_email_status": "failed", "delivery_email_error": str(exc)[:300]}})
        return False


def _set_customer_cookie(response: Response, customer: dict):
    session = jwt.encode({"sub": customer["_id"], "type": "customer", "sv": customer.get("session_version", 0),
                          "exp": datetime.now(timezone.utc) + timedelta(hours=12)}, get_jwt_secret(), algorithm=JWT_ALGORITHM)
    secure = os.getenv("COOKIE_SECURE", "true").lower() in {"1", "true", "yes"}
    response.set_cookie("customer_access_token", session, httponly=True, secure=secure, samesite="lax", max_age=43200, path="/")


async def current_customer(request: Request):
    token = request.cookies.get("customer_access_token")
    if not token:
        raise HTTPException(401, "Silakan masuk ke akun IDSE Digital Product.")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "customer":
            raise HTTPException(401, "Sesi pelanggan tidak valid.")
        customer = await db.store_customers.find_one({"_id": payload["sub"]})
        if not customer or payload.get("sv", 0) != customer.get("session_version", 0):
            raise HTTPException(401, "Akun pelanggan tidak ditemukan.")
        return customer
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(401, "Sesi pelanggan tidak valid.")


@router.get("/config")
async def storefront_config(request: Request):
    # Host-based tenant routing: if Host matches a registered tenant domain,
    # serve that tenant's storefront config instead of the owner's.
    tenant_slug = await _tenant_slug_from_host(request)
    if tenant_slug:
        return await tenant_storefront_config(tenant_slug)
    # Tenant subdomain yang tidak terdaftar → 404, jangan fallback diam-diam
    host = (request.headers.get("host") or "").strip().lower().split(":")[0]
    if host.endswith(".idseconnect.my.id") and host != "idseconnect.my.id":
        raise HTTPException(404, "Toko tidak ditemukan.")
    settings = await get_settings()
    return {
        "telegram_bot_username": os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@"),
        "whatsapp_contact_number": settings.get("whatsapp_contact_number", ""),
        "telegram_contact_target": settings.get("telegram_contact_target", ""),
        # White-label branding: tenant's own store name, never hardcoded "IDSE".
        "store_name": (settings.get("store_name") or "").strip() or "IDSE Marketplace",
        "store_tagline": (settings.get("store_tagline") or "").strip(),
        # Broadcast banner
        "broadcast_enabled": bool(settings.get("broadcast_enabled")),
        "broadcast_message": (settings.get("broadcast_message") or "").strip(),
        # Wajib join channel
        "require_channel_join": bool(settings.get("require_channel_join")),
        "channel_url": (settings.get("channel_url") or "").strip(),
        "channel_name": (settings.get("channel_name") or "").strip(),
    }


class EmailBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class RegisterBody(EmailBody):
    code: str = Field(min_length=6, max_length=6)
    password: str = Field(min_length=8, max_length=128)


class LoginBody(EmailBody):
    password: str = Field(min_length=8, max_length=128)


class ResetBody(RegisterBody):
    pass


def _clean_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise HTTPException(400, "Format email tidak valid.")


async def _issue_email_code(email: str, purpose: str):
    now = datetime.now(timezone.utc)
    if purpose == "register" and await db.store_customers.find_one({"email": email}, {"_id": 1}):
        raise HTTPException(409, "Email sudah terdaftar. Silakan masuk atau reset kata sandi.")
    if purpose == "reset" and not await db.store_customers.find_one({"email": email}, {"_id": 1}):
        return {"ok": True, "message": "Jika email terdaftar, kode reset akan dikirim."}
    prior = await db.store_email_codes.find_one({"email": email, "purpose": purpose})
    if prior and now - _utc_datetime(prior.get("last_sent_at"), now) < timedelta(seconds=60):
        raise HTTPException(429, "Tunggu 60 detik sebelum meminta kode baru.")
    if prior and now - _utc_datetime(prior.get("window_started_at"), now) < timedelta(hours=1) and prior.get("sent_count", 0) >= 5:
        raise HTTPException(429, "Batas permintaan kode tercapai. Coba lagi satu jam lagi.")
    if prior and now - _utc_datetime(prior.get("window_started_at"), now) >= timedelta(hours=1):
        await db.store_email_codes.update_one({"_id": prior["_id"]}, {"$set": {"window_started_at": now, "sent_count": 0}})
    code = f"{secrets.randbelow(1_000_000):06d}"
    await db.store_email_codes.update_one(
        {"email": email, "purpose": purpose},
        {"$set": {"code_hash": _email_code_hash(email, code), "expires_at": now + timedelta(minutes=10),
                   "last_sent_at": now, "attempts": 0},
         "$setOnInsert": {"window_started_at": now}, "$inc": {"sent_count": 1}},
        upsert=True,
    )
    await _send_email_code(email, code, purpose)
    return {"ok": True, "message": "Kode dikirim jika alamat email dapat menerima email."}


@router.post("/register/request-code")
async def registration_code(body: EmailBody):
    return await _issue_email_code(_clean_email(body.email), "register")


@router.post("/register/verify")
async def customer_register(body: RegisterBody, response: Response):
    email = _clean_email(body.email)
    record = await db.store_email_codes.find_one({"email": email, "purpose": "register"})
    now = datetime.now(timezone.utc)
    if not record or _utc_datetime(record.get("expires_at"), now) <= now or record.get("attempts", 0) >= 5:
        raise HTTPException(400, "Kode tidak valid atau kedaluwarsa. Minta kode baru.")
    if not hmac.compare_digest(record.get("code_hash", ""), _email_code_hash(email, body.code)):
        await db.store_email_codes.update_one({"_id": record["_id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(400, "Kode verifikasi salah.")
    from auth import hash_password
    customer = {"_id": str(uuid.uuid4()), "email": email, "password_hash": hash_password(body.password),
                "balance_idr": 0, "balance_usd": 0, "verified_at": now, "created_at": now,
                "session_version": 0}
    try:
        await db.store_customers.insert_one(customer)
    except Exception as exc:
        if exc.__class__.__name__ == "DuplicateKeyError":
            raise HTTPException(409, "Email sudah terdaftar.")
        raise
    await db.store_email_codes.delete_one({"_id": record["_id"]})
    _set_customer_cookie(response, customer)
    return {"ok": True}


@router.post("/login")
async def customer_login(body: LoginBody, response: Response):
    email = _clean_email(body.email)
    customer = await db.store_customers.find_one({"email": email})
    from auth import verify_password
    if not customer or not verify_password(body.password, customer.get("password_hash", "")):
        raise HTTPException(401, "Email atau kata sandi salah.")
    _set_customer_cookie(response, customer)
    return {"ok": True}


@router.post("/password/request-code")
async def password_reset_code(body: EmailBody):
    return await _issue_email_code(_clean_email(body.email), "reset")


@router.post("/password/reset")
async def password_reset(body: ResetBody):
    email = _clean_email(body.email)
    record = await db.store_email_codes.find_one({"email": email, "purpose": "reset"})
    now = datetime.now(timezone.utc)
    if not record or _utc_datetime(record.get("expires_at"), now) <= now or record.get("attempts", 0) >= 5:
        raise HTTPException(400, "Kode reset tidak valid atau kedaluwarsa.")
    if not hmac.compare_digest(record.get("code_hash", ""), _email_code_hash(email, body.code)):
        await db.store_email_codes.update_one({"_id": record["_id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(400, "Kode reset salah.")
    from auth import hash_password
    await db.store_customers.update_one({"email": email}, {"$set": {"password_hash": hash_password(body.password), "password_updated_at": now}, "$inc": {"session_version": 1}})
    await db.store_email_codes.delete_one({"_id": record["_id"]})
    return {"ok": True}


@router.post("/link-code")
async def create_telegram_link_code(customer: dict = Depends(current_customer)):
    if customer.get("telegram_id"):
        raise HTTPException(409, "Akun Telegram sudah terhubung.")
    code = secrets.token_hex(4).upper()
    updated = await db.store_customers.update_one({"_id": customer["_id"], "telegram_id": {"$exists": False}}, {"$set": {
        "telegram_link_code_hash": hashlib.sha256(code.encode()).hexdigest(),
        "telegram_link_expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
    }})
    if updated.modified_count != 1:
        raise HTTPException(409, "Akun Telegram sudah terhubung.")
    return {"code": code, "bot_username": os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")}


async def complete_telegram_link(telegram_id: int, code: str):
    from pymongo.errors import DuplicateKeyError
    digest = hashlib.sha256(code.strip().upper().encode()).hexdigest()
    merge_id = str(uuid.uuid4())
    try:
        customer = await db.store_customers.find_one_and_update(
            {"telegram_link_code_hash": digest, "telegram_link_expires_at": {"$gt": datetime.now(timezone.utc)},
             "telegram_id": {"$exists": False}},
            [
                {"$set": {
                    "telegram_id": telegram_id,
                    "telegram_linked_at": datetime.now(timezone.utc),
                    "wallet_merge": {
                        "id": merge_id,
                        "status": "pending",
                        "amount_idr": {"$ifNull": ["$balance_idr", 0]},
                        "amount_usd": {"$ifNull": ["$balance_usd", 0]},
                    },
                    "balance_idr": 0,
                    "balance_usd": 0,
                }},
                {"$unset": ["telegram_link_code_hash", "telegram_link_expires_at"]},
            ],
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return None
    if customer:
        from services import apply_pending_wallet_merge
        await apply_pending_wallet_merge(customer["_id"])
        customer = await db.store_customers.find_one({"_id": customer["_id"]})
    return customer


@router.post("/logout")
async def customer_logout(response: Response):
    response.delete_cookie("customer_access_token", path="/")
    return {"ok": True}


def _public_product(product):
    item = {key: product.get(key) for key in (
        "name", "description", "price_usd", "price_idr", "product_kind", "delivery_type", "minimum_purchase_qty"
    )}
    # Convert ObjectId ke string
    item["_id"] = str(product.get("_id", ""))
    item["catalog_name"] = catalog_name(product)
    item["minimum_purchase_qty"] = max(1, int(item.get("minimum_purchase_qty") or 1))
    item.update(artwork_urls(product))
    return item


@router.get("/products")
async def store_products(request: Request, search: str = ""):
    # Host-based tenant routing first.
    tenant_slug = await _tenant_slug_from_host(request)
    if tenant_slug:
        return await tenant_store_products(tenant_slug, search)
    # Tenant subdomain yang tidak terdaftar → 404, jangan fallback diam-diam
    host = (request.headers.get("host") or "").strip().lower().split(":")[0]
    if host.endswith(".idseconnect.my.id") and host != "idseconnect.my.id":
        raise HTTPException(404, "Toko tidak ditemukan.")
    query = {"active": True}
    term = search.strip()[:80]
    if term:
        import re
        escaped = re.escape(term)
        query["$or"] = [{"name": {"$regex": escaped, "$options": "i"}}, {"description": {"$regex": escaped, "$options": "i"}}]
    products = await db.products.find(query, {"content": 0, "inventory_schema": 0}).sort("created_at", -1).to_list(length=None)
    sales_rows = await db.purchases.aggregate([
        {"$match": {"status": {"$in": ["paid", "delivered", "completed", "service_waiting", "delivery_failed"]}}},
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.product_id", "sales_count": {"$sum": {"$ifNull": ["$items.qty", 0]}}}},
    ]).to_list(length=None)
    sales_by_product = {str(row["_id"]): int(row.get("sales_count") or 0) for row in sales_rows if row.get("_id") is not None}
    result = []
    for product in products:
        item = _public_product(product)
        stock = await stock_for(product)
        item["stock"] = stock
        item["sales_count"] = sales_by_product.get(str(product["_id"]), 0)
        for currency in ("IDR", "USD"):
            pricing = await price_for_product(product, currency, 1)
            item[f"price_{currency.lower()}_current"] = pricing["unit_price"]
            item[f"discount_{currency.lower()}"] = pricing["discount_per_unit"]
        result.append(item)
    return result


@router.get("/products/{product_id}")
async def store_product(product_id: str):
    product = await db.products.find_one({"_id": product_id, "active": True}, {"content": 0, "inventory_schema": 0})
    if not product:
        raise HTTPException(404, "Produk tidak ditemukan.")
    item = _public_product(product)
    item["stock"] = await stock_for(product)
    for currency in ("IDR", "USD"):
        pricing = await price_for_product(product, currency, 1)
        item[f"price_{currency.lower()}_current"] = pricing["unit_price"]
        item[f"discount_{currency.lower()}"] = pricing["discount_per_unit"]
    return item


@router.get("/products/{product_id}/image")
async def store_product_image(product_id: str, catalog: bool = False):
    product = await db.products.find_one({"_id": product_id, "active": True})
    if not product:
        raise HTTPException(404, "Foto produk tidak ditemukan.")
    return await image_response(product, catalog)


@router.get("/me")
async def customer_profile(user: dict = Depends(current_customer)):
    bot_user = await db.bot_users.find_one({"telegram_id": user["telegram_id"]}) if user.get("telegram_id") else None
    if user.get("telegram_id") and (user.get("wallet_merge") or {}).get("status") != "complete":
        from services import apply_pending_wallet_merge
        await apply_pending_wallet_merge(user["_id"])
        user = await db.store_customers.find_one({"_id": user["_id"]}) or user
        bot_user = await db.bot_users.find_one({"telegram_id": user["telegram_id"]})
    return profile_payload(user, bot_user)


def profile_payload(user, bot_user=None):
    return {"email": user.get("email"), "telegram_id": user.get("telegram_id"),
            "display_name": user.get("display_name") or (bot_user or {}).get("first_name") or "",
            "phone": user.get("phone") or "", "email_verified": bool(user.get("verified_at")),
            "created_at": user.get("created_at"),
            "username": (bot_user or {}).get("username"), "first_name": (bot_user or {}).get("first_name"),
            "balance_idr": (bot_user or {}).get("balance_idr", 0) if user.get("telegram_id") else user.get("balance_idr", 0),
            "balance_usd": (bot_user or {}).get("balance_usd", 0) if user.get("telegram_id") else user.get("balance_usd", 0),
            "web_balance_idr": user.get("balance_idr", 0), "web_balance_usd": user.get("balance_usd", 0),
            "telegram_linked": bool(user.get("telegram_id")), "currency": (bot_user or {}).get("currency", "IDR"),
            "frozen": (bot_user or {}).get("frozen", False)}


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(default="", max_length=30)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value):
        value = " ".join(value.split())
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Nama tampilan wajib diisi.")
        return value

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value):
        value = value.strip()
        if value and (not re.fullmatch(r"\+?[0-9 ()-]+", value) or not 7 <= len(re.sub(r"\D", "", value)) <= 20):
            raise ValueError("Nomor kontak tidak valid. Gunakan 7–20 digit, boleh diawali +.")
        return value


@router.patch("/me")
async def update_customer_profile(body: ProfileUpdate, response: Response, user: dict = Depends(current_customer)):
    # Restrict the write to optional profile fields; financial/auth fields stay intact.
    changed = await db.store_customers.update_one({"_id": user["_id"]}, {"$set": {
        **body.model_dump(), "profile_updated_at": datetime.now(timezone.utc),
    }})
    if not changed.matched_count:
        raise HTTPException(404, "Akun tidak ditemukan.")
    updated = await db.store_customers.find_one({"_id": user["_id"]})
    bot_user = await db.bot_users.find_one({"telegram_id": updated["telegram_id"]}) if updated.get("telegram_id") else None
    response.headers["Cache-Control"] = "no-store, private"
    return profile_payload(updated, bot_user)


class CheckoutBody(BaseModel):
    items: list[dict] = Field(min_length=1, max_length=50)
    currency: str = "IDR"
    coupon_code: str | None = Field(default=None, max_length=32)
    payment_method: str = "qris"
    idempotency_key: str = Field(min_length=8, max_length=80)


class QuoteBody(BaseModel):
    items: list[dict] = Field(min_length=1, max_length=50)
    currency: str = "IDR"
    coupon_code: str | None = Field(default=None, max_length=32)


class StoreDepositBody(BaseModel):
    amount_idr: int = Field(ge=10000, le=10000000)


@router.post("/quote")
async def store_quote(body: QuoteBody):
    """Return a live cart estimate; checkout recalculates every value before charging."""
    if body.currency not in {"IDR", "USD"}:
        raise HTTPException(400, "Currency tidak valid.")
    quantities = {}
    try:
        for raw in body.items:
            pid = str(raw.get("pid") or "")
            qty = int(raw.get("qty", 1))
            if not pid or qty < 1 or qty > 100:
                raise ValueError
            quantities[pid] = quantities.get(pid, 0) + qty
        if not quantities or any(qty > 1000 for qty in quantities.values()):
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(400, "Isi keranjang tidak valid.")

    quote_items = []
    for product_id, qty in quantities.items():
        product = await db.products.find_one({"_id": product_id, "active": True})
        if not product:
            raise HTTPException(409, "Salah satu produk di keranjang tidak tersedia.")
        minimum = max(1, int(product.get("minimum_purchase_qty") or 1))
        if qty < minimum:
            raise HTTPException(409, f"Minimum pembelian {minimum} pcs untuk {product['name']}.")
        stock = await stock_for(product)
        if stock is not None and qty > stock:
            raise HTTPException(409, f"Stok {product['name']} berubah. Tersedia {stock}.")
        pricing = await price_for_product(product, body.currency, qty)
        quote_items.append({
            "product_id": product_id, "name": product.get("name") or "Produk", "qty": qty,
            "unit_price": pricing["unit_price"], "base_unit_price": pricing["base_unit_price"],
            "subtotal": round(float(pricing["unit_price"]) * qty, 2),
            "discount_total": pricing["discount_total"], "discount_name": pricing.get("discount_name"),
        })

    subtotal = round(sum(float(item["subtotal"]) for item in quote_items), 2)
    total = subtotal
    coupon_error = None
    coupon_applied = False
    coupon_discount_amount = 0.0
    code = str(body.coupon_code or "").strip()
    if code:
        from promo_service import validate_coupon, coupon_discount
        buyer = {"user_tid": "__storefront_quote__"}
        base = sum(float(item["base_unit_price"]) * item["qty"] for item in quote_items)
        coupon, coupon_error = await validate_coupon(
            code, buyer, body.currency, base, [item["product_id"] for item in quote_items]
        )
        if coupon:
            eligible_ids = set(coupon.get("product_ids") or [])
            eligible = [item for item in quote_items if not eligible_ids or item["product_id"] in eligible_ids]
            eligible_base = sum(float(item["base_unit_price"]) * item["qty"] for item in eligible)
            if eligible_base < float(coupon.get("min_purchase") or 0):
                coupon_error = "Total produk yang memenuhi syarat belum mencapai minimum kupon."
            else:
                existing_discount = sum(float(item["discount_total"] or 0) for item in eligible)
                candidate = min(coupon_discount(coupon, eligible_base), eligible_base)
                if candidate > existing_discount:
                    coupon_discount_amount = round(candidate - existing_discount, 2)
                    coupon_applied = True
                    total = round(subtotal - coupon_discount_amount, 2)
                else:
                    coupon_error = "Diskon produk yang aktif sudah lebih besar; kupon tidak menambah potongan."

    product_discounts = sum(float(item["discount_total"] or 0) for item in quote_items)
    return {
        "items": quote_items, "subtotal": subtotal,
        "discount_total": round(product_discounts + coupon_discount_amount, 2),
        "coupon_discount": coupon_discount_amount, "coupon_applied": coupon_applied,
        "coupon_error": coupon_error, "total": total, "currency": body.currency,
    }


@router.post("/checkout")
async def store_checkout(body: CheckoutBody, user: dict = Depends(current_customer)):
    if body.currency != "IDR":
        raise HTTPException(400, "Pembayaran saldo dan QRIS Front Store menggunakan IDR.")
    method = str(body.payment_method or "qris").strip().lower()
    if method not in {"qris", "balance"}:
        raise HTTPException(400, "Metode pembayaran tidak valid.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", body.idempotency_key):
        raise HTTPException(400, "Kunci checkout tidak valid.")
    existing = await db.purchases.find_one({"customer_id": user["_id"], "idempotency_key": body.idempotency_key})
    if existing:
        return {key: existing.get(key) for key in ("_id", "invoice_id", "status", "total", "currency", "payment_method", "discount_total", "created_at", "items", "delivery_email_status")}
    if user.get("account_disabled"):
        raise HTTPException(403, "Akun sedang dinonaktifkan.")
    cart = []
    try:
        quantities = {}
        for item in body.items:
            pid = str(item.get("pid") or "")
            qty = int(item.get("qty", 1))
            if not pid or qty < 1 or qty > 100:
                raise ValueError
            quantities[pid] = quantities.get(pid, 0) + qty
        if any(qty > 1000 for qty in quantities.values()):
            raise ValueError
        cart = [{"pid": pid, "qty": qty} for pid, qty in quantities.items()]
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(400, "Isi keranjang tidak valid.")
    if user.get("telegram_id"):
        bot_user = await db.bot_users.find_one({"telegram_id": user["telegram_id"]})
        if not bot_user:
            raise HTTPException(403, "Akun Telegram belum terdaftar di bot. Buka bot lalu kirim /start.")
        if bot_user.get("frozen"):
            raise HTTPException(403, "Akun sedang dibekukan.")
        user = {**user, "username": bot_user.get("username", ""), "traffic_source_code": bot_user.get("traffic_source_code"),
                "traffic_source_kind": bot_user.get("traffic_source_kind")}
    if method == "balance":
        if user.get("telegram_id"):
            from services import apply_pending_wallet_merge
            await apply_pending_wallet_merge(user["_id"])
        checkout_user = {**user, "customer_id": user["_id"], "currency": "IDR"}
        try:
            from checkout import execute_checkout
            result = await execute_checkout(
                checkout_user, cart, coupon_code=body.coupon_code, purchase_source="WEB",
                order_metadata={"idempotency_key": body.idempotency_key,
                                "customer_id": user["_id"], "customer_email": user.get("email")},
            )
        except Exception:
            logger.exception("Storefront balance checkout failed for customer %s", user["_id"])
            raise HTTPException(503, "Checkout saldo gagal diproses. Saldo belum berhasil dipotong.")
        if not result.get("ok"):
            error = result.get("error")
            if error == "balance":
                detail = result.get("message") or "Saldo tidak cukup. Deposit atau pilih QRIS."
            elif error == "minimum_qty":
                detail = f"Minimum pembelian {result['minimum_qty']} pcs untuk {result['product']['name']}."
            elif error == "stock":
                detail = f"Stok {result['product']['name']} berubah. Tersedia {result.get('stock', 0)}."
            elif error == "coupon":
                detail = result.get("message") or "Kupon tidak dapat digunakan."
            elif error == "checkout" and "Saldo" in str(result.get("message") or ""):
                detail = "Saldo tidak cukup. Deposit saldo atau pilih pembayaran QRIS."
            else:
                detail = result.get("message") or "Saldo tidak cukup atau checkout gagal."
            raise HTTPException(400, detail)
        order_id = result["order"]["_id"]
        await _finalize_store_balance_order(order_id)
        completed = await db.purchases.find_one({"_id": order_id})
        return {key: completed.get(key) for key in ("_id", "invoice_id", "status", "total", "currency", "payment_method", "discount_total", "created_at", "items", "delivery_email_status")}
    try:
        from direct_checkout import create_store_qris_order
        result = await create_store_qris_order(
            user, cart, coupon_code=body.coupon_code, idempotency_key=body.idempotency_key
        )
    except Exception:
        logger.exception("QRIS checkout could not be created for customer %s", user["_id"])
        raise HTTPException(503, "QRIS checkout gagal dibuat. Coba lagi beberapa saat.")
    if not result or result.get("error"):
        detail = (result or {}).get("error") or (result or {}).get("message")
        raise HTTPException(400, detail or "Checkout QRIS gagal. Periksa produk dan coba lagi.")
    order = result["order"]
    if order.get("status") in {"failed", "expired"}:
        raise HTTPException(409, "Checkout QRIS sebelumnya gagal atau kedaluwarsa. Coba buat QRIS baru.")
    payment = result.get("payment") or {}
    response = {key: order.get(key) for key in ("_id", "invoice_id", "status", "total", "currency", "discount_total", "created_at", "items", "expires_at", "expires_in_minutes")}
    response.update({
        "payment_method": "QRIS", "payment_amount": payment.get("payment_amount"),
        "payment_status": payment.get("status"),
        "qr_image": "data:image/png;base64," + base64.b64encode(result["image"]).decode("ascii") if result.get("image") else None,
    })
    return response


@router.get("/orders")
async def customer_orders(user: dict = Depends(current_customer)):
    query = {"customer_id": user["_id"]}
    if user.get("telegram_id"):
        query = {"$or": [{"customer_id": user["_id"]}, {"user_tid": user["telegram_id"]}]}
    orders = await db.purchases.find(query).sort("created_at", -1).limit(100).to_list(100)
    return [{key: order.get(key) for key in ("_id", "invoice_id", "status", "total", "currency", "discount_total", "created_at", "items", "payment_method", "delivery_email_status", "expires_at", "expires_in_minutes")} for order in orders]


@router.get("/orders/{order_id}/qris")
async def customer_order_qris(order_id: str, user: dict = Depends(current_customer)):
    owner = [{"customer_id": user["_id"]}]
    if user.get("telegram_id"):
        owner.append({"user_tid": user["telegram_id"]})
    order = await db.purchases.find_one({"_id": order_id, "$or": owner})
    if not order:
        raise HTTPException(404, "Pesanan tidak ditemukan.")
    if order.get("payment_method") != "qris" or order.get("status") != "pending_payment":
        raise HTTPException(409, "Pesanan ini tidak sedang menunggu pembayaran QRIS.")
    payment = await db.gopay_payments.find_one({"_id": order.get("payment_id"), "status": "pending"})
    if not payment or payment.get("expires_at", "") <= datetime.now(timezone.utc).isoformat():
        raise HTTPException(410, "QRIS pesanan sudah kedaluwarsa. Buat checkout baru.")
    from gopay_provider import _run_node
    try:
        data = await asyncio.to_thread(_run_node, "create_qris.mjs", [str(payment["payment_amount"])])
        image = base64.b64decode(data["image_base64"], validate=True)
    except Exception:
        logger.exception("Could not regenerate QRIS image for order %s", order_id)
        raise HTTPException(503, "QRIS pesanan belum dapat ditampilkan.")
    return {
        "_id": order_id, "invoice_id": order.get("invoice_id"), "status": order.get("status"),
        "payment_amount": payment["payment_amount"], "expires_at": order.get("expires_at"),
        "expires_in_minutes": order.get("expires_in_minutes", 5),
        "qr_image": "data:image/png;base64," + base64.b64encode(image).decode("ascii"),
    }


@router.get("/orders/{order_id}/delivery")
async def customer_order_delivery(order_id: str, response: Response, user: dict = Depends(current_customer)):
    from order_fulfillment import owned_order, fulfillment, PRIVATE_HEADERS
    response.headers.update(PRIVATE_HEADERS)
    return await fulfillment(await owned_order(order_id, user))


@router.get("/orders/{order_id}/download")
async def download_order_text(order_id: str, user: dict = Depends(current_customer)):
    from order_fulfillment import owned_order, fulfillment, fulfillment_text, PRIVATE_HEADERS
    order = await owned_order(order_id, user)
    if order.get("status") not in {"delivered", "completed"}:
        raise HTTPException(409, "Data akun belum tersedia.", headers=PRIVATE_HEADERS)
    data = await fulfillment(order)
    name = _safe_attachment_name(str(order.get("invoice_id") or order_id), "order")
    return Response(fulfillment_text(data).encode("utf-8-sig"), media_type="text/plain; charset=utf-8",
                    headers={**PRIVATE_HEADERS, "Content-Disposition": f'attachment; filename="{name}.txt"'})


@router.get("/orders/{order_id}/files/{item_id}")
async def download_order_file(order_id: str, item_id: str, user: dict = Depends(current_customer)):
    from order_fulfillment import owned_order, delivered_file, PRIVATE_HEADERS
    data, filename = await delivered_file(await owned_order(order_id, user), item_id)
    name = _safe_attachment_name(filename, "inventory.session")
    return Response(data, media_type="application/octet-stream", headers={**PRIVATE_HEADERS, "Content-Disposition": f'attachment; filename="{name}"'})


async def _finalize_store_balance_order(order_id: str) -> bool:
    order = await db.purchases.find_one({"_id": order_id, "status": "paid"})
    if not order:
        return False
    service_names = []
    for item in order.get("items") or []:
        product = await db.products.find_one({"_id": item.get("product_id")})
        if product and (product.get("product_kind") == "service" or product.get("delivery_type") == "service"):
            service_names.append(f"{item.get('name') or product.get('name') or 'Jasa'} ×{item.get('qty') or 1}")
    if service_names:
        changed = await db.purchases.update_one({"_id": order_id, "status": "paid"}, {"$set": {"status": "service_waiting"}})
        if changed.modified_count:
            from services import notify_transaction_channel_safely
            await notify_transaction_channel_safely({**order, "status": "service_waiting"})
        try:
            from services import notify_admin
            await notify_admin(
                "🛎️ <b>Pesanan jasa dari web menunggu tindak lanjut</b>\n"
                f"Invoice: <code>{escape(str(order.get('invoice_id') or order_id))}</code>\n"
                f"Pelanggan: {escape(str(order.get('customer_email') or '-'))}\n"
                f"Produk jasa: {escape(', '.join(service_names))}\n"
                "Selesaikan pesanan dari menu Orders setelah pekerjaan selesai."
            )
        except Exception:
            logger.exception("Could not notify admin about balance-paid web service order %s", order_id)
        return True
    changed = await db.purchases.update_one({"_id": order_id, "status": "paid"}, {"$set": {
        "status": "delivered", "delivered_at": datetime.now(timezone.utc).isoformat(), "delivery_error": None,
    }})
    if changed.modified_count:
        from services import notify_transaction_channel_safely
        await notify_transaction_channel_safely({**order, "status": "delivered"})
        await send_order_completion_email(order_id)
    return True


@router.post("/deposits")
async def create_store_deposit(body: StoreDepositBody, user: dict = Depends(current_customer)):
    from direct_checkout import store_qris_ready
    if not await store_qris_ready():
        raise HTTPException(503, "Pembayaran QRIS sedang tidak tersedia.")
    customer = {"customer_id": user["_id"], "email": user["email"],
                "telegram_id": user.get("telegram_id"), "username": "", "first_name": user.get("name", "")}
    if user.get("telegram_id"):
        bot_user = await db.bot_users.find_one({"telegram_id": user["telegram_id"]}) or {}
        customer.update({"username": bot_user.get("username", ""), "first_name": bot_user.get("first_name", "")})
    try:
        payment = await __import__("gopay_provider").create_gopay_payment(customer, body.amount_idr)
    except Exception:
        logger.exception("Storefront QRIS deposit could not be created for customer %s", user["_id"])
        raise HTTPException(503, "QRIS gagal dibuat. Coba lagi beberapa saat.")
    return {
        "deposit_id": payment["deposit"]["_id"],
        "amount": payment["deposit"]["amount"],
        "admin_fee": payment["admin_fee"],
        "payment_amount": payment["payment_amount"],
        "platform_code": payment["platform_code"],
        "status": "pending",
        "created_at": payment["deposit"]["created_at"],
        "expires_at": payment["expires_at"].isoformat(),
        "expires_in_minutes": payment["expires_in_minutes"],
        "payment_method": "QRIS",
        "qr_image": "data:image/png;base64," + base64.b64encode(payment["image"]).decode("ascii"),
    }


@router.get("/deposits")
async def customer_deposits(user: dict = Depends(current_customer)):
    clauses = [{"customer_id": user["_id"]}]
    if user.get("telegram_id"):
        clauses.append({"user_tid": user["telegram_id"]})
    rows = await db.deposits.find({"$or": clauses}, {
        "_id": 1, "amount": 1, "credited_amount": 1, "currency": 1, "method": 1,
        "status": 1, "created_at": 1, "decided_at": 1, "expires_at": 1,
        "payment_amount": 1, "note": 1, "gopay_tx_id": 1,
    }).sort("created_at", -1).limit(100).to_list(100)
    return [{"deposit_id": row["_id"], **{key: value for key, value in row.items() if key != "_id"}} for row in rows]


@router.get("/transactions")
async def customer_transactions(user: dict = Depends(current_customer)):
    orders = await customer_orders(user)
    deposits = await customer_deposits(user)
    rows = [{"type": "order", "created_at": row.get("created_at"), "amount": row.get("total"),
             "currency": row.get("currency"), "status": row.get("status"), "reference": row.get("invoice_id"),
             "payment_method": row.get("payment_method"), "items": row.get("items"), "id": row.get("_id")} for row in orders]
    rows.extend({"type": "deposit", "created_at": row.get("created_at"), "amount": row.get("credited_amount") or row.get("amount"),
                 "currency": row.get("currency"), "status": row.get("status"), "reference": row.get("deposit_id"),
                 "payment_method": row.get("method"), "id": row.get("deposit_id")} for row in deposits)
    return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)[:200]


# ---------------------------------------------------------------------------
# Per-tenant storefront (path-based: /api/store/t/{slug}/...)
# Lets each tenant have their own public store link, e.g.
# https://idse-dev.duckdns.org/store/t/anasyah-store
# Host-based routing (anasyah-store.idseconnect.my.id) resolves via the
# domain registry below; path-based is the dev fallback.
# ---------------------------------------------------------------------------

async def _tenant_slug_from_host(request: Request) -> str | None:
    """Resolve tenant slug from the Host header via the domain registry."""
    import domain_registry

    # Cek X-Forwarded-Host dulu (dari panel server proxy), baru Host biasa
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").strip().lower().split(",")[0].split(":")[0]
    if not host:
        return None
    reg = await domain_registry.resolve_domain(db.client, host)
    if not reg or reg.get("purpose") != "storefront":
        return None
    tenant_id = reg.get("tenant_id")
    if not tenant_id:
        return None
    from dependencies import get_tenant_registry

    registry = get_tenant_registry()
    # tenant_id here may be the registry _id, id, or slug; find the slug.
    for t in await registry.list_tenants():
        if str(t.get("_id")) == str(tenant_id) or str(t.get("id")) == str(tenant_id) or str(t.get("slug")) == str(tenant_id):
            return str(t.get("slug"))
    return None

async def _resolve_tenant_store(slug: str):
    """Return (tenant_doc, tenant_db) for a storefront slug, or raise 404."""
    from dependencies import get_tenant_registry

    registry = get_tenant_registry()
    tenant = await registry.get_tenant(slug)
    if not tenant:
        raise HTTPException(404, "Toko tidak ditemukan.")
    database_name = tenant.get("database_name")
    if not database_name:
        raise HTTPException(404, "Toko belum siap.")
    return tenant, db.client[database_name]


@router.get("/t/{slug}/config")
async def tenant_storefront_config(slug: str):
    tenant, tenant_db = await _resolve_tenant_store(slug)
    metadata = tenant.get("metadata") or {}
    bot_config = metadata.get("bot_config") or {}
    settings = await tenant_db.settings.find_one({"_id": "main"}) or {}
    return {
        "tenant_name": tenant.get("name") or slug,
        "tenant_slug": slug,
        "telegram_bot_username": (bot_config.get("username") or "").lstrip("@"),
        "store_name": (settings.get("store_name") or "").strip() or tenant.get("name") or "Toko",
        "store_tagline": (settings.get("store_tagline") or "").strip(),
        "broadcast_enabled": bool(settings.get("broadcast_enabled")),
        "broadcast_message": (settings.get("broadcast_message") or "").strip(),
        "require_channel_join": bool(settings.get("require_channel_join")),
        "channel_url": (settings.get("channel_url") or "").strip(),
        "channel_name": (settings.get("channel_name") or "").strip(),
    }


@router.get("/t/{slug}/products")
async def tenant_store_products(slug: str, search: str = ""):
    tenant, tenant_db = await _resolve_tenant_store(slug)
    query = {"active": True}
    term = search.strip()[:80]
    if term:
        escaped = re.escape(term)
        query["$or"] = [{"name": {"$regex": escaped, "$options": "i"}}, {"description": {"$regex": escaped, "$options": "i"}}]
    products = await tenant_db.products.find(query, {"content": 0, "inventory_schema": 0}).sort("created_at", -1).to_list(length=None)
    result = []
    for product in products:
        item = _public_product(product)
        try:
            item["stock"] = await stock_for(product)
        except Exception:
            item["stock"] = None
        result.append(item)
    return result
