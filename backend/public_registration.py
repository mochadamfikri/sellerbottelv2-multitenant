"""Public self-service tenant registration (landing page signup).

Flow (mirrors the JokiBot reference):
  1. POST /api/public/register/request-code {email} -> OTP to Gmail
  2. POST /api/public/register {username, store_name, email, code,
     whatsapp, password} -> verify OTP, create tenant (demo),
     auto-register <username>-shop.<base> subdomain.

Username rules (from reference): 3-50 chars, lowercase letters, numbers,
dots, underscores, dashes. The username becomes the tenant slug.
"""
from __future__ import annotations

import os
import re
import secrets
import logging
from pymongo.errors import DuplicateKeyError
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["public-registration"])

OTP_TTL_SECONDS = 600
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = 60

USERNAME_RE = re.compile(r"^[a-z0-9.-]{3,50}$")  # tanpa underscore — nggak valid buat subdomain/SSL
BASE_DOMAIN = os.environ.get("TENANT_BASE_DOMAIN", "idseconnect.my.id").strip().lower()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _platform_db():
    from db import db
    from tenant_db import resolve_platform_database_name

    return db.client[resolve_platform_database_name(os.environ)]


def _otp_collection():
    return _platform_db()["public_reg_otp"]


def _owners_collection():
    return _platform_db()["tenant_owners"]


class RequestCodeBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=5, max_length=254)

    @field_validator("email")
    @classmethod
    def _gmail_only(cls, value: str) -> str:
        value = value.strip().lower()
        if not value.endswith("@gmail.com"):
            raise ValueError("Wajib menggunakan email @gmail.com.")
        return value


class RegisterBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=50)
    store_name: str = Field(min_length=2, max_length=200)
    email: str = Field(min_length=5, max_length=254)
    code: str | None = Field(default=None, min_length=6, max_length=6)
    verify_token: str | None = Field(default=None, max_length=100)
    package: str = Field(default="demo", max_length=20)
    whatsapp: str = Field(min_length=9, max_length=20)
    password: str = Field(min_length=12, max_length=128)
    bot_token: str | None = Field(default=None, max_length=100)
    admin_telegram_id: str | None = Field(default=None, max_length=30)
    has_domain: bool = Field(default=False)
    custom_domain: str | None = Field(default=None, max_length=253)
    subdomain: str | None = Field(default=None, max_length=50)

    @field_validator("username")
    @classmethod
    def _valid_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not USERNAME_RE.match(value):
            raise ValueError(
                "Username 3-50 karakter: huruf kecil, angka, titik atau strip. Tanpa underscore."
            )
        return value

    @field_validator("email")
    @classmethod
    def _gmail_only(cls, value: str) -> str:
        value = value.strip().lower()
        if not value.endswith("@gmail.com"):
            raise ValueError("Wajib menggunakan email @gmail.com.")
        return value


async def _send_otp_email(email: str, code: str) -> None:
    """Kirim OTP via SMTP yang dikonfigurasi di .env (via proxy)."""
    import smtplib
    import socket
    import base64
    from email.message import EmailMessage
    from urllib.parse import urlparse

    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", "").strip() or user
    from_name = os.environ.get("SMTP_FROM_NAME", "IDSE")

    # Dev fallback: kalau SMTP belum dikonfigurasi, log aja
    if not all((host, user, password)):
        logger.warning("Registration email delivery unavailable: SMTP is not configured")
        raise HTTPException(503, "Email pendaftaran belum dikonfigurasi.")

    msg = EmailMessage()
    msg["Subject"] = "Kode OTP Pendaftaran IDSEConnect"
    msg["From"] = f"{from_name} <{sender}>"
    msg["To"] = email
    msg.set_content(
        f"Halo!\n\n"
        f"Kode OTP pendaftaran toko IDSEConnect kamu: {code}\n\n"
        f"Kode berlaku 10 menit. Jangan bagikan ke siapa pun.\n\n"
        f"Salam,\nTim IDSE"
    )

    port = int(os.environ.get("SMTP_PORT", "587"))
    use_ssl = os.environ.get("SMTP_USE_SSL", "false").lower() in {"1", "true", "yes"}

    def _proxy_socket(target_host: str, target_port: int) -> socket.socket:
        """Buka socket ke SMTP via HTTP proxy (CONNECT)."""
        # Baca proxy dari file yang diupdate watchdog (kredensial rotate)
        proxy_url = ""
        for p in ("/tmp/hatch_proxy_url", os.path.expanduser("~/.hatch_proxy_url")):
            try:
                with open(p) as f:
                    proxy_url = f.read().strip()
                    if proxy_url:
                        break
            except Exception:
                pass
        if not proxy_url:
            proxy_url = (
                os.environ.get("PROXY_URL")
                or os.environ.get("https_proxy")
                or os.environ.get("HTTPS_PROXY")
                or ""
            )
        if not proxy_url:
            return socket.create_connection((target_host, target_port), timeout=20)
        p = urlparse(proxy_url)
        sock = socket.create_connection((p.hostname, p.port or 3128), timeout=20)
        auth = ""
        if p.username:
            creds = f"{p.username}:{p.password or ''}"
            auth = f"Proxy-Authorization: Basic {base64.b64encode(creds.encode()).decode()}\r\n"
        req = (
            f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
            f"Host: {target_host}:{target_port}\r\n"
            f"{auth}\r\n"
        )
        sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk
        if b" 200 " not in resp.split(b"\r\n", 1)[0]:
            sock.close()
            raise ConnectionError(f"Proxy CONNECT gagal: {resp[:100]}")
        return sock

    def deliver():
        sock = _proxy_socket(host, port)
        try:
            if use_ssl:
                import ssl
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(sock, server_hostname=host)
                server = smtplib.SMTP()
                server.sock = sock
                server.getreply()
            else:
                server = smtplib.SMTP()
                server._host = host
                server.sock = sock
                server.getreply()
                server.starttls()
            server.login(user, password)
            server.send_message(msg)
            server.quit()
        finally:
            try:
                sock.close()
            except Exception:
                pass

    import asyncio
    await asyncio.to_thread(deliver)


@router.post("/register/request-code")
async def request_registration_code(body: RequestCodeBody) -> dict:
    coll = _otp_collection()
    now = _utcnow()
    existing = await coll.find_one({"email": body.email})
    if existing:
        last = existing.get("created_at")
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last and (now - last).total_seconds() < OTP_RESEND_COOLDOWN:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tunggu sebentar sebelum minta kode lagi.",
            )
    code = f"{secrets.randbelow(900000) + 100000}"
    await coll.update_one(
        {"email": body.email},
        {
            "$set": {
                "email": body.email,
                "code": code,
                "attempts": 0,
                "created_at": now,
                "expires_at": now + timedelta(seconds=OTP_TTL_SECONDS),
            }
        },
        upsert=True,
    )
    try:
        await _send_otp_email(body.email, code)
    except Exception as error:
        await coll.delete_one({"email": body.email, "code": code})
        logger.warning("Registration email delivery failed (%s)", type(error).__name__)
        raise HTTPException(503, "Kode verifikasi gagal dikirim. Silakan coba lagi.") from None
    return {"ok": True}


class VerifyCodeBody(RequestCodeBody):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=5, max_length=254)
    code: str = Field(min_length=6, max_length=6)


@router.get("/register/check-dns")
async def check_custom_domain_dns(domain: str = "") -> dict:
    """Cek apakah custom domain user sudah mengarah ke server kita.
    Return {"connected": true/false}."""
    import socket

    domain = (domain or "").strip().lower().rstrip(".")
    if not domain or len(domain) < 4:
        return {"connected": False}

    # IP VPS yang diharapkan — TODO: ambil dari config
    EXPECTED_IP = "16.78.106.9"

    try:
        # Resolve A record
        ips = socket.gethostbyname_ex(domain)[2]
        return {"connected": EXPECTED_IP in ips, "ips": ips}
    except Exception:
        return {"connected": False}


@router.post("/register/verify-code")
async def verify_registration_code(body: VerifyCodeBody) -> dict:
    """Validasi OTP saja (tanpa buat tenant) — untuk flow pilih paket.
    Return verify_token yang dipakai di /register."""
    coll = _otp_collection()
    record = await coll.find_one({"email": body.email.strip().lower()})
    now = _utcnow()
    exp = record.get("expires_at") if record else None
    if exp and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if not record or not exp or exp < now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kode OTP kadaluarsa. Minta kode baru.")
    if int(record.get("attempts") or 0) >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Terlalu banyak percobaan. Minta kode baru.")
    if record.get("code") != body.code.strip():
        await coll.update_one({"email": body.email.strip().lower()}, {"$inc": {"attempts": 1}})
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kode OTP salah.")

    # OTP valid — buat verify token (berlaku 30 menit)
    verify_token = secrets.token_urlsafe(32)
    await _platform_db()["public_reg_verified"].update_one(
        {"email": body.email.strip().lower()},
        {"$set": {
            "email": body.email.strip().lower(),
            "verify_token": verify_token,
            "verified_at": now,
            "expires_at": now + timedelta(seconds=1800),
        }},
        upsert=True,
    )
    # Hapus OTP biar nggak dipakai ulang
    await coll.delete_one({"email": body.email.strip().lower()})
    return {"ok": True, "verify_token": verify_token}


async def _notify_owner_new_registration(data: dict) -> None:
    """Kirim notifikasi Telegram ke owner tiap ada pendaftar baru."""
    try:
        from db import client
        from dependencies import resolve_platform_database_name
        from inventory import _fernet
        import httpx

        platform_db = client[resolve_platform_database_name(os.environ)]
        doc = await platform_db["platform_config"].find_one({"_id": "central_bot"})
        if not doc:
            return

        token = _fernet().decrypt(doc["bot_token_enc"].encode()).decode()
        admin_ids = doc.get("admin_ids") or []
        if not admin_ids:
            return

        text = (
            "🆕 <b>Pendaftar Baru!</b>\n\n"
            f"🏪 Toko: {data['store_name']}\n"
            f"👤 Username: <code>{data['username']}</code>\n"
            f"📧 Email: {data['email']}\n"
            f"📱 WA: {data['whatsapp']}\n"
            f"🌐 Shop: {data['shop_url']}\n"
            f"🤖 Bot token: {'✅ diisi' if data.get('has_bot_token') else '❌ kosong'}\n"
            f"🆔 Admin TG ID: {data.get('admin_tg') or '-'}"
        )

        async with httpx.AsyncClient(timeout=15) as http:
            for aid in admin_ids:
                try:
                    await http.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": aid, "text": text, "parse_mode": "HTML"},
                    )
                except Exception as error:
                    logger.warning("Registration notification failed (%s)", type(error).__name__)
    except Exception as error:
        logger.warning("Registration notification unavailable (%s)", type(error).__name__)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_tenant(body: RegisterBody) -> dict:
    from dependencies import get_tenant_registry
    import domain_registry

    # 1. Verify OTP atau verify_token.
    email_norm = body.email.strip().lower()
    now = _utcnow()

    if body.verify_token:
        # Flow baru: OTP sudah diverifikasi di halaman sebelumnya
        vdoc = await _platform_db()["public_reg_verified"].find_one({"email": email_norm})
        vexp = vdoc.get("expires_at") if vdoc else None
        if vexp and vexp.tzinfo is None:
            vexp = vexp.replace(tzinfo=timezone.utc)
        if not vdoc or vdoc.get("verify_token") != body.verify_token or not vexp or vexp < now:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Verifikasi kadaluarsa. Ulangi dari awal.")
    else:
        # Flow lama: verifikasi kode langsung
        if not body.code:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kode OTP wajib diisi.")
        coll = _otp_collection()
        record = await coll.find_one({"email": email_norm})
        exp = record.get("expires_at") if record else None
        if exp and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if not record or not exp or exp < now:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kode OTP kadaluarsa. Minta kode baru.")
        if int(record.get("attempts") or 0) >= OTP_MAX_ATTEMPTS:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Terlalu banyak percobaan. Minta kode baru.")
        if record.get("code") != body.code:
            await coll.update_one({"email": email_norm}, {"$inc": {"attempts": 1}})
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kode OTP salah.")

    # 2. Normalisasi slug → single DNS label
    # Lestari.Store → lestari-store, LESTARI_STORE → lestari-store
    def _norm_slug(v: str) -> str:
        v = (v or "").lower()
        v = re.sub(r"[._\s]+", "-", v)  # . _ spasi → -
        v = re.sub(r"[^a-z0-9-]", "", v)  # buang selain a-z 0-9 -
        v = re.sub(r"-+", "-", v)  # collapse ---
        return v.strip("-")  # trim - di awal/akhir

    raw_slug = body.subdomain or body.username
    safe_slug = _norm_slug(raw_slug)
    if not safe_slug or len(safe_slug) < 3:
        safe_slug = _norm_slug(body.username)
    if not safe_slug or len(safe_slug) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sub-domain tidak valid. Minimal 3 karakter huruf/angka.")
    registry = get_tenant_registry()
    if await registry.get_tenant(safe_slug):
        raise HTTPException(status.HTTP_409_CONFLICT, f'Sub-domain "{safe_slug}" sudah dipakai. Pilih yang lain.')

    from db import client as registration_client
    from inventory_transform import DOMAIN_RE
    if body.has_domain:
        shop_domain = (body.custom_domain or "").strip().lower().rstrip(".")
        if not DOMAIN_RE.fullmatch(shop_domain):
            raise HTTPException(422, "Custom domain tidak valid.")
        if shop_domain in {BASE_DOMAIN, "idsestock.my.id", "idsehub.my.id", "idsedm.duckdns.org"} or shop_domain.endswith("." + BASE_DOMAIN):
            raise HTTPException(409, "Domain platform tidak dapat didaftarkan sebagai custom domain.")
        domain_origin = "custom"
    else:
        shop_domain = f"{safe_slug}.{BASE_DOMAIN}"
        domain_origin = "owner_subdomain"
    await _owners_collection().create_index("email", unique=True, name="owner_email_unique")
    if await _owners_collection().find_one({"email": email_norm}):
        raise HTTPException(409, "Email sudah terdaftar sebagai pemilik tenant.")
    existing_domain = await domain_registry.resolve_domain(registration_client, shop_domain)
    if existing_domain:
        raise HTTPException(409, "Domain sudah terdaftar.")
    from tenant_db import tenant_database_name
    database_name = tenant_database_name(safe_slug, registry.platform_database_name)
    if database_name in await registration_client.list_database_names():
        raise HTTPException(409, "Database tenant sudah ada. Hubungi admin platform.")

    # 3. Create tenant (paket yang dipilih).
    valid_packages = {"demo", "monthly", "yearly", "lifetime"}
    plan = body.package.strip().lower() if body.package else "demo"
    if plan not in valid_packages:
        plan = "demo"
    try:
        tenant = await registry.create_tenant(
            slug=safe_slug,
            name=body.store_name,
            plan=plan,
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    try:
        await domain_registry.register_domain(
            registration_client, domain=shop_domain, tenant_id=str(tenant["_id"]),
            purpose="storefront", origin=domain_origin, created_by="public-registration",
        )
        panel_base = os.environ.get("TENANT_PANEL_DOMAIN", "").strip().lower()
        if panel_base:
            await domain_registry.register_domain(
                registration_client, domain=f"{safe_slug}.{panel_base}",
                tenant_id=str(tenant["_id"]), purpose="stock_panel",
                origin="owner_subdomain", created_by="public-registration",
            )
        # 4. Store owner credentials.
        owner_doc = {
            "tenant_id": str(tenant["_id"]),
            "tenant_slug": safe_slug,
            "email": email_norm,
            "store_name": body.store_name,
            "whatsapp": body.whatsapp,
            "password_hash": hash_password(body.password),
            "created_at": now.isoformat(),
        }
        # Simpan admin ID kalau diisi (token hanya disimpan terenkripsi di metadata)
        bot_token = (body.bot_token or "").strip()
        admin_tg = (body.admin_telegram_id or "").strip()
        if admin_tg:
            owner_doc["admin_telegram_id"] = admin_tg
        await _owners_collection().insert_one(owner_doc)

        # Kalau token bot diisi, langsung simpan ke tenant bot_config (status pending)
        # biar bisa diproses/aktivasi dari platform panel
        if bot_token:
            from inventory import _fernet
            enc_token = _fernet().encrypt(bot_token.encode()).decode()
            # Validasi token ke Telegram sebelum simpan
            bot_valid = False
            bot_username = None
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as hc:
                    r = await hc.get(f"https://api.telegram.org/bot{bot_token}/getMe")
                    if r.status_code == 200:
                        j = r.json()
                        if j.get("ok"):
                            bot_valid = True
                            bot_username = j.get("result", {}).get("username")
            except Exception as error:
                logger.warning("Bot validation unavailable for tenant %s (%s)", safe_slug, type(error).__name__)
            bot_config = {
                "token_encrypted": enc_token,
                "provisioning_status": "active" if bot_valid else "invalid_token",
                "bot_username": bot_username,
            }
            if admin_tg:
                try:
                    bot_config["admin_ids"] = [int(admin_tg)]
                except ValueError:
                    pass
            # Merge dengan metadata yang ada
            existing = await registry.get_tenant(safe_slug)
            existing_meta = dict((existing.get("metadata") or {}))
            existing_meta["bot_config"] = bot_config
            await registry.set_metadata(safe_slug, existing_meta)

        from tenant_provisioning import provision_tenant_database
        await provision_tenant_database(safe_slug, registration_client)
        await registration_client[tenant["database_name"]].settings.update_one(
            {"_id": "main"}, {"$set": {"store_name": body.store_name}},
        )
        await registry.update_status(safe_slug, "active")
    except Exception as error:
        # Only remove records created by this attempt; never another tenant's domain.
        await _owners_collection().delete_many({"tenant_id": str(tenant["_id"])})
        await _platform_db().domains.delete_many({"tenant_id": str(tenant["_id"]), "created_by": "public-registration"})
        # The preflight and registry's unique database_name claim guarantee
        # this is a new database owned only by this registration attempt.
        await registration_client.drop_database(tenant["database_name"])
        await registry.collection.delete_one({"_id": tenant["_id"], "slug": safe_slug})
        logger.error("Registration rolled back for tenant %s (%s)", safe_slug, type(error).__name__)
        if isinstance(error, (ValueError, DuplicateKeyError)):
            raise HTTPException(409, "Domain atau email sudah terdaftar.") from None
        raise HTTPException(503, "Pendaftaran gagal. Silakan coba lagi.") from None

    await _platform_db()["public_reg_verified"].delete_one({"email": email_norm})
    await _otp_collection().delete_one({"email": email_norm})

    result = {
        "ok": True,
        "tenant_slug": safe_slug,
        "store_name": body.store_name,
        "shop_url": f"https://{shop_domain}",
    }

    # Notifikasi ke owner (async, jangan blokir response)
    import asyncio
    asyncio.create_task(_notify_owner_new_registration({
        "username": safe_slug,
        "store_name": body.store_name,
        "email": body.email,
        "whatsapp": body.whatsapp,
        "shop_url": result["shop_url"],
        "has_bot_token": bool(body.bot_token and body.bot_token.strip()),
        "admin_tg": (body.admin_telegram_id or "").strip() or None,
    }))

    return result


# ---------------------------------------------------------------------------
# Tenant owner login & panel (terpisah dari panel owner)
# ---------------------------------------------------------------------------

class TenantLoginBody(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=200)


def _json_safe(obj):
    """Convert Mongo types ke JSON-serializable."""
    from bson import ObjectId
    from datetime import datetime
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


@router.post("/tenant/login")
async def tenant_login(body: TenantLoginBody) -> dict:
    """Login pemilik tenant — untuk akses panel admin tenant sendiri."""
    from auth import verify_password, create_access_token

    email = body.email.strip().lower()
    owner = await _owners_collection().find_one({"email": email})
    if not owner or not verify_password(body.password, owner.get("password_hash", "")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email atau password salah.")

    await _active_owner_tenant(owner)

    token = create_access_token(str(owner["_id"]), email)
    return {
        "ok": True,
        "token": token,
        "tenant_slug": owner.get("tenant_slug"),
        "store_name": owner.get("store_name", ""),
        "email": email,
    }


async def _require_tenant_owner(request) -> dict:
    """Validasi JWT tenant owner, return owner doc."""
    from auth import get_jwt_secret, JWT_ALGORITHM
    import jwt as _jwt

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login dulu.")
    try:
        payload = _jwt.decode(auth[7:], get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        owner_id = payload.get("sub")
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token tidak valid.")

    from bson import ObjectId
    from bson.errors import InvalidId
    from pymongo.errors import PyMongoError
    try:
        object_id = ObjectId(owner_id)
    except (InvalidId, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token tidak valid.") from None
    try:
        owner = await _owners_collection().find_one({"_id": object_id})
    except PyMongoError as error:
        logger.warning("Tenant owner lookup unavailable (%s)", type(error).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Layanan sementara tidak tersedia. Silakan coba lagi.") from None
    if not owner:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Akun tidak ditemukan.")
    await _active_owner_tenant(owner)
    return owner


async def _active_owner_tenant(owner):
    from dependencies import get_tenant_registry
    tenant = await get_tenant_registry().get_tenant(owner.get("tenant_slug"))
    if not tenant or str(tenant.get("_id")) != str(owner.get("tenant_id")):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant tidak ditemukan.")
    if tenant.get("status") != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant tidak aktif.")
    return tenant


@router.get("/tenant/me")
async def tenant_me(request: Request) -> dict:
    owner = await _require_tenant_owner(request)
    return {
        "tenant_slug": owner.get("tenant_slug"),
        "email": owner.get("email"),
        "whatsapp": owner.get("whatsapp"),
    }


@router.get("/tenant/products")
async def tenant_products(request: Request) -> dict:
    """List produk di database tenant sendiri."""
    from dependencies import get_tenant_registry

    owner = await _require_tenant_owner(request)
    registry = get_tenant_registry()
    tenant = await registry.get_tenant(owner.get("tenant_slug"))
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant tidak ditemukan.")

    from db import db as _db
    tenant_db = _db.client[tenant.get("database_name")]
    products = []
    async for p in tenant_db.products.find({}, {"content": 0}).sort("created_at", -1).limit(100):
        products.append(_json_safe(p))
    return {"products": products, "tenant_slug": owner.get("tenant_slug")}


async def _get_tenant_db(request) -> tuple:
    """Helper: return (owner, tenant, tenant_db) untuk endpoint tenant."""
    from dependencies import get_tenant_registry
    from db import db as _db

    owner = await _require_tenant_owner(request)
    registry = get_tenant_registry()
    tenant = await registry.get_tenant(owner.get("tenant_slug"))
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant tidak ditemukan.")
    tenant_db = _db.client[tenant.get("database_name")]
    return owner, tenant, tenant_db


@router.post("/tenant/products")
async def tenant_create_product(request: Request, body: dict) -> dict:
    """Tambah produk baru di tenant sendiri."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    from datetime import datetime, timezone
    doc = {
        "name": str(body.get("name", "")).strip()[:200],
        "description": str(body.get("description", "")).strip()[:2000],
        "active": bool(body.get("active", True)),
        "created_at": datetime.now(timezone.utc),
    }
    if not doc["name"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nama produk wajib diisi.")
    result = await tenant_db.products.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return {"ok": True, "product": _json_safe(doc)}


@router.put("/tenant/products/{product_id}")
async def tenant_update_product(request: Request, product_id: str, body: dict) -> dict:
    """Update produk di tenant sendiri."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    from bson import ObjectId
    try:
        oid = ObjectId(product_id)
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ID tidak valid.")
    update = {}
    if "name" in body:
        update["name"] = str(body["name"]).strip()[:200]
    if "description" in body:
        update["description"] = str(body["description"]).strip()[:2000]
    if "active" in body:
        update["active"] = bool(body["active"])
    if not update:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tidak ada yang diubah.")
    result = await tenant_db.products.update_one({"_id": oid}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produk tidak ditemukan.")
    return {"ok": True}


@router.delete("/tenant/products/{product_id}")
async def tenant_delete_product(request: Request, product_id: str) -> dict:
    """Hapus produk di tenant sendiri."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    from bson import ObjectId
    try:
        oid = ObjectId(product_id)
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ID tidak valid.")
    result = await tenant_db.products.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produk tidak ditemukan.")
    return {"ok": True}


@router.get("/tenant/orders")
async def tenant_orders(request: Request) -> dict:
    """List order di tenant sendiri."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    orders = []
    async for o in tenant_db.purchases.find({}).sort("created_at", -1).limit(100):
        orders.append(_json_safe(o))
    return {"orders": orders}


@router.get("/tenant/stats")
async def tenant_stats(request: Request) -> dict:
    """Statistik dashboard tenant."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    products = await tenant_db.products.count_documents({})
    orders = await tenant_db.purchases.count_documents({})
    catalogs = await tenant_db.product_catalogs.count_documents({})
    users = await tenant_db.bot_users.count_documents({})
    return {
        "tenant_slug": tenant.get("slug"),
        "store_name": tenant.get("name"),
        "products": products,
        "orders": orders,
        "catalogs": catalogs,
        "users": users,
    }


# === KATALOG ===
@router.get("/tenant/catalogs")
async def tenant_catalogs(request: Request) -> dict:
    """List katalog di tenant sendiri."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    catalogs = []
    async for c in tenant_db.catalogs.find({}).sort("name", 1):
        catalogs.append(_json_safe(c))
    return {"catalogs": catalogs}


@router.post("/tenant/catalogs")
async def tenant_create_catalog(request: Request, body: dict) -> dict:
    """Tambah katalog baru."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    from datetime import datetime, timezone
    doc = {
        "name": str(body.get("name", "")).strip()[:100],
        "description": str(body.get("description", "")).strip()[:500],
        "created_at": datetime.now(timezone.utc),
    }
    if not doc["name"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nama katalog wajib diisi.")
    result = await tenant_db.catalogs.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return {"ok": True, "catalog": _json_safe(doc)}


@router.delete("/tenant/catalogs/{catalog_id}")
async def tenant_delete_catalog(request: Request, catalog_id: str) -> dict:
    """Hapus katalog."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    from bson import ObjectId
    try:
        oid = ObjectId(catalog_id)
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ID tidak valid.")
    result = await tenant_db.catalogs.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Katalog tidak ditemukan.")
    return {"ok": True}


# === INVENTORY ===
@router.get("/tenant/inventory")
async def tenant_inventory(request: Request) -> dict:
    """List inventory/stok produk."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    items = []
    async for p in tenant_db.products.find({}, {"name": 1, "stock": 1}):
        items.append({
            "_id": str(p["_id"]),
            "name": p.get("name", ""),
            "stock": p.get("stock", 0),
        })
    return {"inventory": items}


@router.put("/tenant/inventory/{product_id}")
async def tenant_update_stock(request: Request, product_id: str, body: dict) -> dict:
    """Update stok produk."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    from bson import ObjectId
    try:
        oid = ObjectId(product_id)
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ID tidak valid.")
    stock = body.get("stock")
    if not isinstance(stock, int) or stock < 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Stok harus angka >= 0.")
    result = await tenant_db.products.update_one({"_id": oid}, {"$set": {"stock": stock}})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produk tidak ditemukan.")
    return {"ok": True}


# === USERS ===
@router.get("/tenant/users")
async def tenant_users(request: Request) -> dict:
    """List pengguna/customer tenant."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    users = []
    async for u in tenant_db.bot_users.find({}).sort("created_at", -1).limit(100):
        users.append(_json_safe(u))
    return {"users": users, "total": await tenant_db.bot_users.count_documents({})}


# === BROADCAST ===
@router.post("/tenant/broadcast")
async def tenant_broadcast(request: Request, body: dict) -> dict:
    """Compatibility route; execute the canonical scoped broadcast implementation."""
    from tenant_full_routes import tenant_send_broadcast
    return await tenant_send_broadcast(request, body)


@router.get("/tenant/broadcasts")
async def tenant_broadcasts(request: Request) -> dict:
    """Riwayat broadcast."""
    _, tenant, tenant_db = await _get_tenant_db(request)
    items = []
    async for b in tenant_db.broadcasts.find({}).sort("created_at", -1).limit(20):
        items.append(_json_safe(b))
    return {"broadcasts": items}


@router.get("/artwork-preview")
async def public_artwork_preview(name: str = "Produk", catalog_name: str = ""):
    from fastapi import Response
    from product_artwork import render_product_artwork
    return Response(render_product_artwork(name[:300], catalog_name[:80]), media_type="image/webp")


@router.get("/host-config")
async def public_host_config(request: Request, host: str = ""):
    from db import client
    from domain_registry import resolve_domain
    registration = await resolve_domain(client, host or request.headers.get("host", ""))
    if registration and registration.get("purpose") in {"storefront", "stock_panel", "config_panel"} and registration.get("tenant_id"):
        tenant = await _platform_db().tenants.find_one({"_id": registration["tenant_id"]})
        if tenant:
            return {"tenant_slug": tenant["slug"]}
    return {"tenant_slug": None}
