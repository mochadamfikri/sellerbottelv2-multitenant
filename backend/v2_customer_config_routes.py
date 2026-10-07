"""V2 customer config panel: per-tenant customer accounts + bot/domain config.

This panel is ACCESS-SEPARATED from the webshop, the web profile, and the
central stock admin:
- platform-admin endpoints live under ``/api/v2/platform`` and require
  ``require_platform_admin`` (a login here is an admin login, checked against
  the admins collection);
- customer endpoints live under ``/api/v2/customer/{tenant_slug}`` and use a
  customer JWT that is looked up in ``customer_accounts`` — never in admins.

A customer login therefore grants nothing on the platform, shop, profile, or
central stock admin routes, and vice versa.

Tenant isolation: every account/OTP document carries ``tenant_id`` and every
query is scoped by it, so customer A's credentials can never reach customer
B's data.

OTP email delivery is a clearly-marked seam (``send_otp_email``): the default
implementation only logs the code and is gated behind ``CUSTOMER_OTP_DEV_LOG``.
Production MUST inject a real sender and disable the dev log.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from audit_events import write_audit_event
from auth import JWT_ALGORITHM, create_access_token, get_jwt_secret, hash_password, verify_password
from db import db
from dependencies import get_tenant_registry
from platform_rbac import require_platform_admin
from reseller_service import encrypt_token, validate_token
from tenant_registry import MongoTenantRegistry

import jwt as _pyjwt

logger = logging.getLogger("v2_customer_config")

# These named seams keep Telegram I/O and email delivery injectable in offline
# tests.  The shared reseller implementation is the established production
# boundary for getMe and Fernet-protected token storage — do NOT reimplement
# token crypto here.
validate_telegram_bot_token = validate_token
encrypt_telegram_bot_token = encrypt_token

OTP_TTL_SECONDS = 600
OTP_MAX_ATTEMPTS = 5
OTP_CODE_LENGTH = 6
OTP_RESEND_COOLDOWN_SECONDS = 60

CUSTOMER_OTP_DEV_LOG = os.environ.get("CUSTOMER_OTP_DEV_LOG", "1") == "1"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)


async def send_otp_email(email: str, code: str, purpose: str) -> dict[str, Any]:
    """SEAM: deliver an OTP code to the customer's email.

    Default implementation is DEV-ONLY: it logs the code and is gated behind
    ``CUSTOMER_OTP_DEV_LOG`` (default on).  Production MUST replace this with
    a real SMTP/API sender (monkeypatch or dependency override) and set
    ``CUSTOMER_OTP_DEV_LOG=0`` — OTP codes must NEVER be logged in production.
    """
    if CUSTOMER_OTP_DEV_LOG:
        logger.warning("DEV-ONLY OTP email -> %s [purpose=%s] code=%s", email, purpose, code)
    return {"dev_logged": CUSTOMER_OTP_DEV_LOG}


platform_router = APIRouter(prefix="/api/v2/platform", tags=["v2-platform-customer-config"])
customer_router = APIRouter(prefix="/api/v2/customer", tags=["v2-customer"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _hash_otp(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def _new_otp_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(OTP_CODE_LENGTH))


_indexes_ready = False


async def ensure_customer_config_indexes() -> None:
    """Create the uniqueness/scope indexes for customer accounts and OTPs."""
    global _indexes_ready
    if _indexes_ready:
        return
    await db.customer_accounts.create_index(
        [("tenant_id", 1), ("email_lower", 1)], unique=True
    )
    await db.customer_accounts.create_index(
        [("tenant_id", 1), ("username_lower", 1)], unique=True
    )
    await db.customer_account_otps.create_index(
        [("account_id", 1), ("purpose", 1), ("used", 1)]
    )
    _indexes_ready = True


async def _find_tenant_by_id(tenant_id: str, registry: MongoTenantRegistry) -> dict[str, Any] | None:
    tenants = await registry.list_tenants()
    return next((t for t in tenants if str(t["_id"]) == tenant_id), None)


async def _require_tenant_by_id(tenant_id: str, registry: MongoTenantRegistry) -> dict[str, Any]:
    tenant = await _find_tenant_by_id(tenant_id, registry)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant  # type: ignore[return-value]


async def _resolve_customer_tenant(
    tenant_slug: str, registry: MongoTenantRegistry, *, require_active: bool = True
) -> dict[str, Any]:
    tenant = await registry.get_tenant(tenant_slug)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    if require_active and tenant.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is not active")
    return tenant  # type: ignore[return-value]


def _actor_id(admin: dict) -> str:
    return str(admin.get("_id") or admin.get("user_id") or admin.get("email"))


async def _audit(admin: dict, action: str, tenant_id: str, metadata: dict[str, Any]) -> None:
    await write_audit_event(
        actor=_actor_id(admin),
        action=action,
        tenant_id=tenant_id,
        platform="control-plane",
        metadata=metadata,
    )


def _bot_identity(bot: dict[str, Any]) -> tuple[int, str, str]:
    """Return the non-secret Telegram identity fields required by the platform."""
    if not bot.get("is_bot") or not isinstance(bot.get("id"), int):
        raise ValueError("Token bot tidak valid.")
    return int(bot["id"]), str(bot.get("username") or ""), str(bot.get("first_name") or "Bot")


def _normalize_username(username: str) -> str:
    username = username.strip()
    if not _USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Username harus 3-32 karakter: huruf, angka, _, . atau -.",
        )
    return username


def _normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.fullmatch(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format email tidak valid.",
        )
    return email


async def _find_account(tenant_id: str, identifier: str) -> dict[str, Any] | None:
    ident = identifier.strip().lower()
    return await db.customer_accounts.find_one(
        {
            "tenant_id": tenant_id,
            "$or": [{"email_lower": ident}, {"username_lower": ident}],
        }
    )


def _public_account(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_id": str(account["_id"]),
        "username": account["username"],
        "email": account["email"],
        "email_verified": bool(account.get("email_verified")),
        "status": account.get("status"),
    }


# ---------------------------------------------------------------------------
# OTP core
# ---------------------------------------------------------------------------

async def _issue_otp(account: dict[str, Any], purpose: str) -> None:
    """Create a fresh OTP for the account, invalidating older unused ones."""
    account_id = str(account["_id"])
    await db.customer_account_otps.update_many(
        {"account_id": account_id, "purpose": purpose, "used": False},
        {"$set": {"used": True, "superseded_at": _utcnow()}},
    )
    latest = await db.customer_account_otps.find_one(
        {"account_id": account_id, "purpose": purpose},
        sort=[("created_at", -1)],
    )
    if latest is not None:
        created = _as_aware(latest["created_at"])
        if (_utcnow() - created).total_seconds() < OTP_RESEND_COOLDOWN_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Tunggu sebentar sebelum meminta kode baru.",
            )
    code = _new_otp_code()
    salt = secrets.token_hex(8)
    await db.customer_account_otps.insert_one(
        {
            "_id": uuid4().hex,
            "account_id": account_id,
            "tenant_id": account["tenant_id"],
            "purpose": purpose,
            "code_hash": _hash_otp(code, salt),
            "salt": salt,
            "expires_at": _utcnow() + timedelta(seconds=OTP_TTL_SECONDS),
            "attempts": 0,
            "max_attempts": OTP_MAX_ATTEMPTS,
            "used": False,
            "created_at": _utcnow(),
        }
    )
    await send_otp_email(str(account["email"]), code, purpose)


async def _consume_otp(account: dict[str, Any], purpose: str, code: str) -> None:
    """Validate and burn the latest unused OTP. Raises HTTPException on failure."""
    account_id = str(account["_id"])
    otp = await db.customer_account_otps.find_one(
        {"account_id": account_id, "purpose": purpose, "used": False},
        sort=[("created_at", -1)],
    )
    if otp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kode OTP tidak ditemukan. Minta kode baru.",
        )
    if _as_aware(otp["expires_at"]) < _utcnow():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Kode OTP kedaluwarsa. Minta kode baru.",
        )
    if int(otp["attempts"]) >= OTP_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Terlalu banyak percobaan salah. Minta kode baru.",
        )
    if _hash_otp(code.strip(), str(otp["salt"])) != str(otp["code_hash"]):
        await db.customer_account_otps.update_one(
            {"_id": otp["_id"]}, {"$inc": {"attempts": 1}}
        )
        remaining = OTP_MAX_ATTEMPTS - (int(otp["attempts"]) + 1)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Kode salah. Sisa percobaan: {max(remaining, 0)}.",
        )
    await db.customer_account_otps.update_one(
        {"_id": otp["_id"]}, {"$set": {"used": True, "used_at": _utcnow()}}
    )


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

class DomainChoiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["subdomain_of_webshop", "own_domain", "owner_subdomain"]
    hostname: str = Field(min_length=3, max_length=253)


class CustomerConfigBody(BaseModel):
    """Platform-admin input: bot fields + domain choice. Token is write-only."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    telegram_token: str | None = Field(default=None, min_length=1, max_length=256)
    bot_username: str | None = Field(default=None, min_length=1, max_length=64)
    owner_telegram_user_id: int | None = None
    owner_telegram_username: str | None = Field(default=None, min_length=1, max_length=64)
    brand_name: str | None = Field(default=None, min_length=1, max_length=200)
    domain_choice: DomainChoiceBody | None = None


class CustomerConfigResponse(BaseModel):
    telegram_bot_id: int | None = None
    bot_username: str | None = None
    bot_name: str | None = None
    brand_name: str | None = None
    owner_telegram_user_id: int | None = None
    owner_telegram_username: str | None = None
    domain_choice: dict[str, Any] | None = None


class CreateCustomerAccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class OtpRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=254)


class OtpVerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=12)


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class PasswordResetConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=12)
    new_password: str = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# platform-admin endpoints
# ---------------------------------------------------------------------------

async def _save_customer_config(
    tenant: dict[str, Any], registry: MongoTenantRegistry, body: CustomerConfigBody
) -> dict[str, Any]:
    """Persist bot + domain config into tenant metadata.

    The bot fields land in ``metadata.bot_config`` with the exact shape the
    dispatcher expects (``token_encrypted`` etc.), so a bot provisioned here is
    picked up by ``bot_dispatcher`` unchanged.  The token itself is validated
    via getMe and stored encrypted only — never returned.
    """
    metadata = dict(tenant.get("metadata") or {})
    bot_config = dict(metadata.get("bot_config") or {})

    if body.telegram_token is not None:
        bot_id, username, bot_name = _bot_identity(
            await validate_telegram_bot_token(body.telegram_token)
        )
        if body.bot_username:
            declared = body.bot_username.strip().lstrip("@").lower()
            if declared != username.lower():
                raise ValueError(
                    "Bot username tidak cocok dengan token (getMe). Periksa kembali."
                )
        bot_config.update(
            {
                "telegram_bot_id": bot_id,
                "username": username,
                "bot_name": bot_name,
                "token_encrypted": encrypt_telegram_bot_token(body.telegram_token),
                "brand_name": body.brand_name or bot_name,
            }
        )
    elif body.brand_name is not None and bot_config:
        bot_config["brand_name"] = body.brand_name
    elif body.telegram_token is None and not bot_config and (
        body.brand_name is not None
        or body.owner_telegram_user_id is not None
        or body.owner_telegram_username is not None
    ):
        raise ValueError("Telegram bot token is required before configuring a bot")

    if body.owner_telegram_user_id is not None:
        bot_config["owner_telegram_user_id"] = body.owner_telegram_user_id
    if body.owner_telegram_username is not None:
        bot_config["owner_telegram_username"] = body.owner_telegram_username.strip().lstrip("@")

    if bot_config:
        metadata["bot_config"] = bot_config

    domain_choice: dict[str, Any] | None = None
    if body.domain_choice is not None:
        hostname = body.domain_choice.hostname.strip().lower()
        if not _HOSTNAME_RE.fullmatch(hostname):
            raise ValueError("Hostname tidak valid.")
        domain_choice = {"mode": body.domain_choice.mode, "hostname": hostname}
        customer_config = dict(metadata.get("customer_config") or {})
        customer_config["domain_choice"] = domain_choice
        customer_config["domain_verified"] = False  # DNS/TLS handled by domain routing
        metadata["customer_config"] = customer_config
    else:
        existing = metadata.get("customer_config") or {}
        domain_choice = existing.get("domain_choice")

    await registry.set_metadata(str(tenant["slug"]), metadata)
    return {
        "telegram_bot_id": bot_config.get("telegram_bot_id"),
        "bot_username": bot_config.get("username"),
        "bot_name": bot_config.get("bot_name"),
        "brand_name": bot_config.get("brand_name"),
        "owner_telegram_user_id": bot_config.get("owner_telegram_user_id"),
        "owner_telegram_username": bot_config.get("owner_telegram_username"),
        "domain_choice": domain_choice,
    }


@platform_router.put("/tenants/{tenant_id}/customer-config", response_model=CustomerConfigResponse)
async def put_customer_config(
    tenant_id: str,
    body: CustomerConfigBody,
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> CustomerConfigResponse:
    tenant = await _require_tenant_by_id(tenant_id, registry)
    try:
        saved = await _save_customer_config(tenant, registry, body)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    await _audit(
        admin,
        "tenant.customer_configured",
        tenant_id,
        {
            "telegram_bot_id": saved.get("telegram_bot_id"),
            "brand_name": saved.get("brand_name"),
            "domain_choice": saved.get("domain_choice"),
        },
    )
    return CustomerConfigResponse(**saved)


@platform_router.get("/tenants/{tenant_id}/customer-config", response_model=CustomerConfigResponse)
async def get_customer_config(
    tenant_id: str,
    _: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> CustomerConfigResponse:
    tenant = await _require_tenant_by_id(tenant_id, registry)
    metadata = tenant.get("metadata") or {}
    bot_config = metadata.get("bot_config") or {}
    customer_config = metadata.get("customer_config") or {}
    return CustomerConfigResponse(
        telegram_bot_id=bot_config.get("telegram_bot_id"),
        bot_username=bot_config.get("username"),
        bot_name=bot_config.get("bot_name"),
        brand_name=bot_config.get("brand_name"),
        owner_telegram_user_id=bot_config.get("owner_telegram_user_id"),
        owner_telegram_username=bot_config.get("owner_telegram_username"),
        domain_choice=customer_config.get("domain_choice"),
    )


@platform_router.post(
    "/tenants/{tenant_id}/customer-accounts",
    status_code=status.HTTP_201_CREATED,
)
async def create_customer_account(
    tenant_id: str,
    body: CreateCustomerAccountBody,
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> dict[str, Any]:
    """Platform admin pre-creates a customer account (still needs OTP verify)."""
    tenant = await _require_tenant_by_id(tenant_id, registry)
    await ensure_customer_config_indexes()
    username = _normalize_username(body.username)
    email = _normalize_email(body.email)
    tid = str(tenant["_id"])
    if await _find_account(tid, email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email sudah terdaftar.")
    if await _find_account(tid, username) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username sudah dipakai.")
    account = {
        "_id": uuid4().hex,
        "tenant_id": tid,
        "username": username,
        "username_lower": username.lower(),
        "email": email,
        "email_lower": email,
        "password_hash": hash_password(body.password),
        "email_verified": False,
        "status": "pending_verification",
        "created_at": _utcnow(),
        "created_by": f"platform-admin:{_actor_id(admin)}",
    }
    await db.customer_accounts.insert_one(account)
    await _audit(admin, "tenant.customer_account_created", tenant_id, {"email": email})
    return {**_public_account(account), "verification_required": True}


# ---------------------------------------------------------------------------
# customer-facing endpoints
# ---------------------------------------------------------------------------

async def get_current_customer(
    tenant_slug: str,
    request: Request,
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> dict[str, Any]:
    """Resolve the customer JWT to an account strictly inside this tenant.

    A token minted for tenant A resolves to nothing on tenant B's routes —
    this is what keeps customer logins from granting anything elsewhere.
    """
    tenant = await _resolve_customer_tenant(tenant_slug, registry, require_active=False)
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = _pyjwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    except _pyjwt.PyJWTError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from error
    account = await db.customer_accounts.find_one(
        {"_id": payload.get("sub"), "tenant_id": str(tenant["_id"])}
    )
    if account is None or account.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return account


@customer_router.post("/{tenant_slug}/register", status_code=status.HTTP_201_CREATED)
async def customer_register(
    tenant_slug: str,
    body: RegisterBody,
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> dict[str, Any]:
    tenant = await _resolve_customer_tenant(tenant_slug, registry)
    await ensure_customer_config_indexes()
    username = _normalize_username(body.username)
    email = _normalize_email(body.email)
    tid = str(tenant["_id"])
    if await _find_account(tid, email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email sudah terdaftar.")
    if await _find_account(tid, username) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username sudah dipakai.")
    account = {
        "_id": uuid4().hex,
        "tenant_id": tid,
        "username": username,
        "username_lower": username.lower(),
        "email": email,
        "email_lower": email,
        "password_hash": hash_password(body.password),
        "email_verified": False,
        "status": "pending_verification",
        "created_at": _utcnow(),
    }
    await db.customer_accounts.insert_one(account)
    return {**_public_account(account), "verification_required": True}


@customer_router.post("/{tenant_slug}/otp/request")
async def customer_otp_request(
    tenant_slug: str,
    body: OtpRequestBody,
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> dict[str, Any]:
    tenant = await _resolve_customer_tenant(tenant_slug, registry)
    await ensure_customer_config_indexes()
    account = await _find_account(str(tenant["_id"]), _normalize_email(body.email))
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Akun tidak ditemukan.")
    if account.get("email_verified"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email sudah terverifikasi.")
    await _issue_otp(account, "verify_email")
    return {"ok": True, "expires_in_seconds": OTP_TTL_SECONDS}


@customer_router.post("/{tenant_slug}/otp/verify")
async def customer_otp_verify(
    tenant_slug: str,
    body: OtpVerifyBody,
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> dict[str, Any]:
    tenant = await _resolve_customer_tenant(tenant_slug, registry)
    await ensure_customer_config_indexes()
    account = await _find_account(str(tenant["_id"]), _normalize_email(body.email))
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Akun tidak ditemukan.")
    await _consume_otp(account, "verify_email", body.code)
    await db.customer_accounts.update_one(
        {"_id": account["_id"]},
        {"$set": {"email_verified": True, "status": "active", "verified_at": _utcnow()}},
    )
    return {"ok": True, "email_verified": True}


@customer_router.post("/{tenant_slug}/login")
async def customer_login(
    tenant_slug: str,
    body: LoginBody,
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> dict[str, Any]:
    tenant = await _resolve_customer_tenant(tenant_slug, registry)
    await ensure_customer_config_indexes()
    account = await _find_account(str(tenant["_id"]), body.identifier)
    if account is None or not verify_password(body.password, str(account["password_hash"])):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Username/email atau password salah."
        )
    if not account.get("email_verified") or account.get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verifikasi email Anda terlebih dahulu sebelum login.",
        )
    token = create_access_token(str(account["_id"]), str(account["email"]))
    return {"access_token": token, "token_type": "bearer", "account": _public_account(account)}


@customer_router.post("/{tenant_slug}/password-reset/request")
async def customer_password_reset_request(
    tenant_slug: str,
    body: OtpRequestBody,
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> dict[str, Any]:
    tenant = await _resolve_customer_tenant(tenant_slug, registry)
    await ensure_customer_config_indexes()
    account = await _find_account(str(tenant["_id"]), _normalize_email(body.email))
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Akun tidak ditemukan.")
    if not account.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email belum terverifikasi.",
        )
    await _issue_otp(account, "password_reset")
    return {"ok": True, "expires_in_seconds": OTP_TTL_SECONDS}


@customer_router.post("/{tenant_slug}/password-reset/confirm")
async def customer_password_reset_confirm(
    tenant_slug: str,
    body: PasswordResetConfirmBody,
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> dict[str, Any]:
    tenant = await _resolve_customer_tenant(tenant_slug, registry)
    await ensure_customer_config_indexes()
    account = await _find_account(str(tenant["_id"]), _normalize_email(body.email))
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Akun tidak ditemukan.")
    await _consume_otp(account, "password_reset", body.code)
    await db.customer_accounts.update_one(
        {"_id": account["_id"]},
        {"$set": {"password_hash": hash_password(body.new_password), "password_changed_at": _utcnow()}},
    )
    return {"ok": True}


@customer_router.get("/{tenant_slug}/me")
async def customer_me(account: dict = Depends(get_current_customer)) -> dict[str, Any]:
    return _public_account(account)
