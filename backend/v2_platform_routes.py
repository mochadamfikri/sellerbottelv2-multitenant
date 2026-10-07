"""V2 platform-control-plane tenant registry routes."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from audit_events import write_audit_event
from db import db
from dependencies import get_tenant_registry
from platform_rbac import (
    add_tenant_member,
    list_tenant_members,
    remove_tenant_member,
    require_platform_admin,
)
from reseller_service import encrypt_token, validate_token
from subscription_pricing import (
    SubscriptionModeConfig,
    SubscriptionPricingConfig,
    get_pricing_updated_at,
    get_subscription_pricing,
    save_subscription_pricing,
)
from tenant_provisioning import provision_tenant_database
from tenant_registry import MongoTenantRegistry

# These named seams keep Telegram I/O injectable in offline tests.  The shared
# reseller implementation is the established production boundary for getMe and
# Fernet-protected token storage.
validate_telegram_bot_token = validate_token
encrypt_telegram_bot_token = encrypt_token

router = APIRouter(prefix="/api/v2/platform", tags=["v2-platform"])


class CreateTenantBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slug: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)


class UpdateTenantStatusBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "suspended"]


class AddTenantMemberBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: str = Field(min_length=1, max_length=200)
    role: Literal["tenant_viewer", "tenant_operator", "tenant_admin", "tenant_owner"]


class UpdateTenantPlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: Literal["demo", "monthly", "yearly", "lifetime"]
    quotas: dict[str, int] = Field(default_factory=dict)


class ProvisionTenantResponse(BaseModel):
    provisioned: bool
    database_name: str


class ValidateTelegramBotTokenBody(BaseModel):
    """Ephemeral owner input; the token is never included in a response."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    telegram_token: str = Field(min_length=1, max_length=256)


class UpdateBotConfigBody(BaseModel):
    """Token may be supplied only when initially attaching/replacing a bot."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    telegram_token: str | None = Field(default=None, min_length=1, max_length=256)
    brand_name: str | None = Field(default=None, min_length=1, max_length=200)
    admin_ids: list[int] | None = Field(default=None, description="Telegram user IDs treated as bot admins/owners")
    reseller_enabled: bool | None = Field(default=None, description="Show the 'Bikin Bot Sendiri' reseller entry on this bot")


class TelegramBotResponse(BaseModel):
    telegram_bot_id: int
    username: str
    bot_name: str
    brand_name: str
    bot_provisioning: dict[str, Any] | None = None


class TelegramBotValidationResponse(BaseModel):
    telegram_bot_id: int
    username: str
    bot_name: str
    default_brand_name: str


class TenantMemberResponse(BaseModel):
    tenant_id: str
    user_id: str
    role: str


class TenantPlanResponse(BaseModel):
    plan: Literal["demo", "monthly", "yearly", "lifetime"]
    quotas: dict[str, int]


class TenantResponse(BaseModel):
    id: str
    slug: str
    name: str
    status: Literal["provisioning", "active", "suspended", "disabled", "failed"]
    database_name: str
    created_at: datetime


def _tenant_response(tenant: dict[str, object]) -> TenantResponse:
    """Expose tenant metadata only; never return database credentials."""
    status = str(tenant["status"])
    return TenantResponse(
        id=str(tenant["_id"]),
        slug=str(tenant["slug"]),
        name=str(tenant["name"]),
        status=status,  # type: ignore[arg-type]
        database_name=str(tenant["database_name"]),
        created_at=tenant["created_at"],  # type: ignore[arg-type]
    )


async def _find_tenant(tenant_id: str, registry: MongoTenantRegistry) -> dict[str, object] | None:
    tenants = await registry.list_tenants()
    return next(
        (
            tenant
            for tenant in tenants
            if str(tenant["_id"]) == tenant_id
        ),
        None,
    )


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


async def _require_tenant(tenant_id: str, registry: MongoTenantRegistry) -> dict[str, object]:
    tenant = await _find_tenant(tenant_id, registry)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def _member_response(member: dict[str, Any]) -> TenantMemberResponse:
    return TenantMemberResponse(
        tenant_id=str(member["tenant_id"]), user_id=str(member["user_id"]), role=str(member["role"])
    )


def _bot_identity(bot: dict[str, Any]) -> tuple[int, str, str]:
    """Return the non-secret Telegram identity fields required by the platform."""
    if not bot.get("is_bot") or not isinstance(bot.get("id"), int):
        raise ValueError("Token bot tidak valid.")
    return int(bot["id"]), str(bot.get("username") or ""), str(bot.get("first_name") or "Bot")


async def _save_bot_config(
    tenant: dict[str, object], registry: MongoTenantRegistry, *, token: str | None, brand_name: str | None
) -> dict[str, object]:
    """Persist only encrypted token material plus editable, non-secret bot metadata."""
    metadata = dict(cast(dict[str, object], tenant.get("metadata") or {}))
    current = dict(cast(dict[str, object], metadata.get("bot_config") or {}))
    if token is not None:
        bot_id, username, bot_name = _bot_identity(await validate_telegram_bot_token(token))
        current.update(
            {
                "telegram_bot_id": bot_id,
                "username": username,
                "bot_name": bot_name,
                "token_encrypted": encrypt_telegram_bot_token(token),
                "bot_provisioning": {
                    "status": "provisioning",
                    "started_at": datetime.now().isoformat(),
                    "estimated_minutes": PROVISIONING_ESTIMATED_MINUTES,
                },
            }
        )
        current["brand_name"] = brand_name or bot_name
    elif brand_name is not None and current:
        current["brand_name"] = brand_name
    else:
        raise ValueError("Telegram bot token is required before configuring a brand")

    metadata["bot_config"] = current
    await registry.set_metadata(str(tenant["slug"]), metadata)
    return current


async def _provision_database(tenant_slug: str) -> None:
    """Initialize the tenant's settings, metadata, and operational indexes."""
    await provision_tenant_database(tenant_slug, db.client)


def _bot_response(config: dict[str, object]) -> TelegramBotResponse:
    return TelegramBotResponse(
        telegram_bot_id=int(config["telegram_bot_id"]),
        username=str(config["username"]),
        bot_name=str(config["bot_name"]),
        brand_name=str(config["brand_name"]),
        bot_provisioning=cast(dict[str, Any] | None, config.get("bot_provisioning")),
    )


# ---------------------------------------------------------------------------
# Bot provisioning: status tracking, double-submit prevention, demo-once rule,
# and notifications to platform admin + tenant admins.
# ---------------------------------------------------------------------------

PROVISIONING_ESTIMATED_MINUTES = 2
PROVISIONING_LOCK_MINUTES = 5


def _demo_usage_collection():
    """Platform DB collection tracking which Telegram IDs already used demo."""
    from tenant_db import resolve_platform_database_name
    return db.client[resolve_platform_database_name(os.environ)]["demo_usage"]


def _provisioning_in_progress(bot_config: dict[str, object]) -> bool:
    """True when a provisioning run started recently and hasn't finished."""
    prov = bot_config.get("bot_provisioning") or {}
    if not isinstance(prov, dict) or prov.get("status") != "provisioning":
        return False
    try:
        started = datetime.fromisoformat(str(prov.get("started_at", "")))
    except ValueError:
        return False
    age = (datetime.now(started.tzinfo) - started).total_seconds() / 60
    return age < PROVISIONING_LOCK_MINUTES


async def _check_demo_once(admin_ids: list[int]) -> None:
    """One Telegram ID may only ever use demo once. Raises ValueError."""
    if not admin_ids:
        return
    coll = _demo_usage_collection()
    used = await coll.find_one({"telegram_id": {"$in": admin_ids}})
    if used:
        raise ValueError(
            f"ID Telegram {used['telegram_id']} sudah pernah menggunakan demo 1x "
            f"(tenant: {used.get('tenant_slug', '?')}). Satu pengguna hanya bisa demo satu kali."
        )


async def _record_demo_usage(admin_ids: list[int], tenant_slug: str) -> None:
    if not admin_ids:
        return
    coll = _demo_usage_collection()
    now = datetime.now().isoformat()
    for tid in admin_ids:
        await coll.update_one(
            {"telegram_id": tid},
            {"$setOnInsert": {"telegram_id": tid, "tenant_slug": tenant_slug, "created_at": now}},
            upsert=True,
        )


async def _send_telegram_via_central(text: str, chat_id: int) -> None:
    """Send a Telegram message using the central (platform owner) bot token."""
    import httpx

    from tenant_db import resolve_platform_database_name
    from inventory import _fernet

    coll = db.client[resolve_platform_database_name(os.environ)]["platform_config"]
    doc = await coll.find_one({"_id": "central_bot"}) or {}
    enc = doc.get("token_encrypted")
    if not enc:
        return
    try:
        token = _fernet().decrypt(enc.encode()).decode()
    except Exception:
        return

    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    verify = os.environ.get("SSL_CERT_FILE") or True
    async with httpx.AsyncClient(timeout=30, proxy=proxy, trust_env=False, verify=verify) as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        )


async def _notify_provisioning(tenant: dict[str, object], bot_config: dict[str, object]) -> None:
    """Notify platform admins + tenant admins about the provisioning run."""
    import asyncio

    username = bot_config.get("username", "?")
    tenant_name = str(tenant.get("name") or tenant.get("slug") or "?")
    admin_ids = [int(x) for x in (bot_config.get("admin_ids") or [])]

    owner_text = (
        f"🔧 <b>Pemasangan Bot Baru</b>\n\n"
        f"Bot @{username} untuk tenant \"{tenant_name}\" sedang dipasang.\n"
        f"⏱️ Estimasi selesai: ±{PROVISIONING_ESTIMATED_MINUTES} menit.\n\n"
        f"Dispatcher akan menjalankannya otomatis."
    )
    tenant_text = (
        f"🤖 <b>Bot Anda Sedang Dipasang</b>\n\n"
        f"Halo! Bot @{username} untuk toko \"{tenant_name}\" sedang dipasang.\n"
        f"⏱️ Estimasi selesai: ±{PROVISIONING_ESTIMATED_MINUTES} menit.\n\n"
        f"Mohon tunggu, bot akan aktif otomatis."
    )

    # Platform/central admins from the central bot doc.
    from tenant_db import resolve_platform_database_name
    coll = db.client[resolve_platform_database_name(os.environ)]["platform_config"]
    central = await coll.find_one({"_id": "central_bot"}) or {}
    platform_admin_ids = [int(x) for x in (central.get("admin_ids") or [])]

    targets = [(pid, owner_text) for pid in platform_admin_ids]
    targets += [(tid, tenant_text) for tid in admin_ids if tid not in platform_admin_ids]

    async def _fan_out() -> None:
        for chat_id, text in targets:
            try:
                await _send_telegram_via_central(text, chat_id)
            except Exception:
                continue

    # Fire-and-forget: never block the API response on Telegram delivery.
    asyncio.create_task(_fan_out())


async def _validated_bot_response(token: str) -> TelegramBotValidationResponse:
    bot_id, username, bot_name = _bot_identity(await validate_telegram_bot_token(token))
    return TelegramBotValidationResponse(
        telegram_bot_id=bot_id,
        username=username,
        bot_name=bot_name,
        default_brand_name=bot_name,
    )


@router.post(
    "/tenants",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    body: CreateTenantBody,
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> TenantResponse:
    try:
        # MongoTenantRegistry requires plan; use "demo" as default
        tenant = await registry.create_tenant(
            slug=body.slug,
            name=body.name,
            plan="demo",
        )
    except ValueError as error:
        detail = str(error)
        if "already exists" in detail:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from error
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail) from error
    
    await _audit(admin, "tenant.created", str(tenant["_id"]), {"slug": body.slug, "name": body.name})
    
    return _tenant_response(tenant)


@router.get("/tenants", response_model=list[TenantResponse])
async def list_tenants(
    _: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> list[TenantResponse]:
    tenants = await registry.list_tenants()
    return [_tenant_response(tenant) for tenant in tenants]


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    _: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> TenantResponse:
    tenant = await _find_tenant(tenant_id, registry)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return _tenant_response(tenant)


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    _: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
):
    """Hapus tenant beserta datanya. Tidak bisa dibatalkan."""
    from tenant_db import resolve_platform_database_name

    tenant = await _find_tenant(tenant_id, registry)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    slug = tenant.get("slug")
    database_name = tenant.get("database_name")

    # Hapus tenant database (kalau ada)
    if database_name:
        try:
            await db.client.drop_database(database_name)
        except Exception:
            pass

    # Hapus owner record
    try:
        platform_db = db.client[resolve_platform_database_name(os.environ)]
        await platform_db["tenant_owners"].delete_many({"tenant_slug": slug})
        # Hapus domain yang terdaftar untuk tenant ini
        await platform_db["domains"].delete_many({"tenant_id": str(tenant.get("_id"))})
    except Exception:
        pass

    # Hapus tenant dari registry
    try:
        await registry.delete_tenant(slug)
    except AttributeError:
        # Fallback kalau method belum ada
        platform_db = db.client[resolve_platform_database_name(os.environ)]
        await platform_db["tenants"].delete_one({"slug": slug})

    await _audit(_, "platform.tenant_deleted", slug, {})


@router.patch("/tenants/{tenant_id}/status", response_model=TenantResponse)
async def update_tenant_status(
    tenant_id: str,
    body: UpdateTenantStatusBody,
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> TenantResponse:
    tenant = await _find_tenant(tenant_id, registry)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    updated = await registry.update_status(str(tenant["slug"]), body.status)
    await _audit(admin, "tenant.status_updated", tenant_id, {"status": body.status})
    return _tenant_response(updated)


@router.post(
    "/tenants/{tenant_id}/provision",
    response_model=ProvisionTenantResponse,
)
async def provision_tenant(
    tenant_id: str,
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> ProvisionTenantResponse:
    tenant = await _require_tenant(tenant_id, registry)
    database_name = str(tenant["database_name"])
    
    await _provision_database(str(tenant["slug"]))
    # MongoTenantRegistry starts with status="provisioning", set to "active"
    await registry.update_status(str(tenant["slug"]), "active")
    
    await _audit(admin, "tenant.provisioned", tenant_id, {"database_name": database_name})
    
    return ProvisionTenantResponse(provisioned=True, database_name=database_name)


@router.post(
    "/tenants/{tenant_id}/members",
    response_model=TenantMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    tenant_id: str,
    body: AddTenantMemberBody,
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> TenantMemberResponse:
    await _require_tenant(tenant_id, registry)
    
    try:
        member = await add_tenant_member(db, tenant_id, body.user_id, body.role)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    
    await _audit(admin, "tenant.member_added", tenant_id, {"user_id": body.user_id, "role": body.role})
    
    return _member_response(member)


@router.get("/tenants/{tenant_id}/members", response_model=list[TenantMemberResponse])
async def list_members(
    tenant_id: str,
    _: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> list[TenantMemberResponse]:
    await _require_tenant(tenant_id, registry)
    members = await list_tenant_members(db, tenant_id)
    return [_member_response(member) for member in members]


@router.delete("/tenants/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    tenant_id: str,
    user_id: str,
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> Response:
    await _require_tenant(tenant_id, registry)
    
    removed = await remove_tenant_member(db, tenant_id, user_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    
    await _audit(admin, "tenant.member_removed", tenant_id, {"user_id": user_id})
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/tenants/{tenant_id}/plan", response_model=TenantPlanResponse)
async def update_plan(
    tenant_id: str,
    body: UpdateTenantPlanBody,
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> TenantPlanResponse:
    tenant = await _require_tenant(tenant_id, registry)
    
    try:
        await registry.update_plan(str(tenant["slug"]), body.plan)
        if body.quotas:
            await registry.set_quotas(str(tenant["slug"]), dict(body.quotas))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    
    await _audit(
        admin, "tenant.plan_updated", tenant_id, {"plan": body.plan, "quotas": body.quotas}
    )
    
    return TenantPlanResponse(plan=body.plan, quotas=body.quotas)


@router.get(
    "/tenants/{tenant_id}/bot-config",
    response_model=TelegramBotResponse,
)
async def get_bot_config(
    tenant_id: str,
    _: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> TelegramBotResponse:
    """Return current bot info + provisioning status. Token is never exposed."""
    tenant = await _require_tenant(tenant_id, registry)
    bot_config = dict(cast(dict[str, object], (tenant.get("metadata") or {}).get("bot_config") or {}))
    if not bot_config.get("telegram_bot_id"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Belum ada bot terpasang.")
    return _bot_response(bot_config)


@router.post(
    "/tenants/{tenant_id}/bot/validate",
    response_model=TelegramBotValidationResponse,
)
async def validate_bot(
    tenant_id: str,
    body: ValidateTelegramBotTokenBody,
    _: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> TelegramBotValidationResponse:
    await _require_tenant(tenant_id, registry)
    try:
        return await _validated_bot_response(body.telegram_token)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error


@router.put(
    "/tenants/{tenant_id}/bot-config",
    response_model=TelegramBotResponse,
)
@router.patch(
    "/tenants/{tenant_id}/bot-config",
    response_model=TelegramBotResponse,
)
async def update_bot_config(
    tenant_id: str,
    body: UpdateBotConfigBody,
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> TelegramBotResponse:
    tenant = await _require_tenant(tenant_id, registry)

    # Prevent double-submit while a provisioning run is still in flight.
    existing_config = dict(cast(dict[str, object], (tenant.get("metadata") or {}).get("bot_config") or {}))
    if body.telegram_token and _provisioning_in_progress(existing_config):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bot sedang dalam proses pemasangan, mohon tunggu hingga selesai.",
        )

    # Demo-once rule: one Telegram ID may only ever use demo one time.
    is_new_token = body.telegram_token is not None
    effective_admin_ids = (
        [int(x) for x in body.admin_ids]
        if body.admin_ids is not None
        else [int(x) for x in (existing_config.get("admin_ids") or [])]
    )
    if is_new_token and str(tenant.get("plan") or "").lower() == "demo":
        try:
            await _check_demo_once(effective_admin_ids)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error

    try:
        updated = await _save_bot_config(
            tenant,
            registry,
            token=body.telegram_token,
            brand_name=body.brand_name,
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error

    if is_new_token:
        # Record demo usage + notify platform admins and tenant admins.
        if str(tenant.get("plan") or "").lower() == "demo":
            await _record_demo_usage(effective_admin_ids, str(tenant.get("slug")))
        merged_config = dict(updated)
        if body.admin_ids is not None:
            merged_config["admin_ids"] = [int(x) for x in body.admin_ids]
        await _notify_provisioning(tenant, merged_config)

    # Re-read fresh metadata: _save_bot_config already persisted the new token
    # and provisioning status; merge on top instead of clobbering it.
    if body.admin_ids is not None or body.reseller_enabled is not None:
        fresh = await registry.get_tenant(str(tenant["slug"]))
        fresh_metadata = dict(cast(dict[str, object], (fresh.get("metadata") if fresh else None) or {}))
        fresh_config = dict(cast(dict[str, object], fresh_metadata.get("bot_config") or {}))
        if body.admin_ids is not None:
            fresh_config["admin_ids"] = [int(x) for x in body.admin_ids]
            updated["admin_ids"] = fresh_config["admin_ids"]
        if body.reseller_enabled is not None:
            fresh_config["reseller_enabled"] = bool(body.reseller_enabled)
            updated["reseller_enabled"] = fresh_config["reseller_enabled"]
        fresh_metadata["bot_config"] = fresh_config
        await registry.set_metadata(str(tenant["slug"]), fresh_metadata)

    await _audit(
        admin,
        "tenant.bot_configured",
        tenant_id,
        {"telegram_bot_id": updated.get("telegram_bot_id"), "brand_name": updated.get("brand_name")},
    )
    return _bot_response(updated)


class SubscriptionPricingResponse(BaseModel):
    """Owner-configured commercial terms; empty until the owner sets them."""

    modes: dict[str, SubscriptionModeConfig] = Field(default_factory=dict)
    reminder_schedule_days: list[int] | None = None
    grace_period_days: int | None = None
    updated_at: datetime | None = None


def _pricing_response(
    config: SubscriptionPricingConfig, updated_at: datetime | None
) -> SubscriptionPricingResponse:
    return SubscriptionPricingResponse(
        modes=config.modes,
        reminder_schedule_days=config.reminder_schedule_days,
        grace_period_days=config.grace_period_days,
        updated_at=updated_at,
    )


@router.get("/pricing", response_model=SubscriptionPricingResponse)
async def get_pricing(
    _: dict = Depends(require_platform_admin),
) -> SubscriptionPricingResponse:
    config = await get_subscription_pricing()
    return _pricing_response(config, await get_pricing_updated_at())


@router.put("/pricing", response_model=SubscriptionPricingResponse)
async def update_pricing(
    body: SubscriptionPricingConfig,
    admin: dict = Depends(require_platform_admin),
) -> SubscriptionPricingResponse:
    saved = await save_subscription_pricing(body)
    await _audit(
        admin,
        "pricing.updated",
        "platform",
        {
            "modes": sorted(saved.modes.keys()),
            "reminder_schedule_days": saved.reminder_schedule_days,
            "grace_period_days": saved.grace_period_days,
        },
    )
    return _pricing_response(saved, await get_pricing_updated_at())


@router.get("/health")
async def health() -> dict[str, str]:
    """Report that the V2 platform API is mounted."""
    return {"status": "ok", "scope": "platform"}


# ============ WELCOME MEDIA (/start banner) ============

_WELCOME_MEDIA_EXTS = {
    ".jpg": "photo", ".jpeg": "photo", ".png": "photo", ".webp": "photo",
    ".gif": "animation",
}
_WELCOME_MEDIA_MAX_BYTES = 15 * 1024 * 1024


class WelcomeMediaBody(BaseModel):
    """Per-bot /start greeting media config."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    mode: Literal["auto", "upload"] = "auto"
    tagline: str | None = Field(default=None, max_length=60)


class WelcomeMediaResponse(BaseModel):
    enabled: bool = False
    mode: Literal["auto", "upload"] = "auto"
    tagline: str | None = None
    file: str | None = None
    kind: str | None = None


def _welcome_media_response(raw: dict[str, Any] | None) -> WelcomeMediaResponse:
    raw = raw or {}
    return WelcomeMediaResponse(
        enabled=bool(raw.get("enabled", False)),
        mode=raw.get("mode") or "auto",
        tagline=raw.get("tagline"),
        file=raw.get("file"),
        kind=raw.get("kind"),
    )


async def _set_tenant_welcome_media(
    tenant: dict[str, object],
    registry: MongoTenantRegistry,
    patch: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(cast(dict[str, object], tenant.get("metadata") or {}))
    bot_config = dict(cast(dict[str, object], metadata.get("bot_config") or {}))
    current = dict(bot_config.get("welcome_media") or {})
    current.update({k: v for k, v in patch.items() if v is not None})
    if "enabled" in patch:
        current["enabled"] = bool(patch["enabled"])
    bot_config["welcome_media"] = current
    metadata["bot_config"] = bot_config
    await registry.set_metadata(str(tenant["slug"]), metadata)
    return current


def _platform_config_collection():
    from tenant_db import resolve_platform_database_name
    return db.client[resolve_platform_database_name(os.environ)]["platform_config"]


async def _set_central_welcome_media(patch: dict[str, Any]) -> dict[str, Any]:
    coll = _platform_config_collection()
    doc = await coll.find_one({"_id": "central_bot"}) or {}
    current = dict(doc.get("welcome_media") or {})
    current.update({k: v for k, v in patch.items() if v is not None})
    if "enabled" in patch:
        current["enabled"] = bool(patch["enabled"])
    await coll.update_one({"_id": "central_bot"}, {"$set": {"welcome_media": current}}, upsert=True)
    return current


def _check_upload(file: UploadFile) -> tuple[str, str]:
    name = (file.filename or "").lower()
    ext = os.path.splitext(name)[1]
    kind = _WELCOME_MEDIA_EXTS.get(ext)
    if not kind:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format tidak didukung. Pakai JPG, PNG, WEBP, atau GIF.",
        )
    return ext, kind


async def _store_welcome_upload(slug: str, file: UploadFile) -> tuple[str, str]:
    from welcome_banner import upload_media_path
    ext, kind = _check_upload(file)
    data = await file.read()
    if len(data) > _WELCOME_MEDIA_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File maksimal 15MB.",
        )
    dest = upload_media_path(slug, f"welcome{ext}")
    dest.write_bytes(data)
    return str(dest), kind


@router.get("/tenants/{tenant_id}/welcome-media", response_model=WelcomeMediaResponse)
async def get_tenant_welcome_media(
    tenant_id: str,
    _: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> WelcomeMediaResponse:
    tenant = await _require_tenant(tenant_id, registry)
    bot_config = (tenant.get("metadata") or {}).get("bot_config") or {}
    return _welcome_media_response(bot_config.get("welcome_media"))


@router.put("/tenants/{tenant_id}/welcome-media", response_model=WelcomeMediaResponse)
async def update_tenant_welcome_media(
    tenant_id: str,
    body: WelcomeMediaBody,
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> WelcomeMediaResponse:
    tenant = await _require_tenant(tenant_id, registry)
    current = await _set_tenant_welcome_media(
        tenant, registry,
        {"enabled": body.enabled, "mode": body.mode, "tagline": body.tagline},
    )
    await _audit(admin, "tenant.welcome_media_updated", tenant_id,
                 {"enabled": current.get("enabled"), "mode": current.get("mode")})
    return _welcome_media_response(current)


@router.post("/tenants/{tenant_id}/welcome-media/upload", response_model=WelcomeMediaResponse)
async def upload_tenant_welcome_media(
    tenant_id: str,
    file: UploadFile = File(...),
    admin: dict = Depends(require_platform_admin),
    registry: MongoTenantRegistry = Depends(get_tenant_registry),
) -> WelcomeMediaResponse:
    tenant = await _require_tenant(tenant_id, registry)
    slug = str(tenant.get("slug") or tenant_id)
    path, kind = await _store_welcome_upload(slug, file)
    current = await _set_tenant_welcome_media(
        tenant, registry,
        {"enabled": True, "mode": "upload", "file": path, "kind": kind},
    )
    await _audit(admin, "tenant.welcome_media_uploaded", tenant_id, {"kind": kind})
    return _welcome_media_response(current)


@router.get("/central-bot/welcome-media", response_model=WelcomeMediaResponse)
async def get_central_welcome_media(
    _: dict = Depends(require_platform_admin),
) -> WelcomeMediaResponse:
    doc = await _platform_config_collection().find_one({"_id": "central_bot"}) or {}
    return _welcome_media_response(doc.get("welcome_media"))


@router.put("/central-bot/welcome-media", response_model=WelcomeMediaResponse)
async def update_central_welcome_media(
    body: WelcomeMediaBody,
    admin: dict = Depends(require_platform_admin),
) -> WelcomeMediaResponse:
    current = await _set_central_welcome_media(
        {"enabled": body.enabled, "mode": body.mode, "tagline": body.tagline},
    )
    await _audit(admin, "central.welcome_media_updated", "platform",
                 {"enabled": current.get("enabled"), "mode": current.get("mode")})
    return _welcome_media_response(current)


@router.post("/central-bot/welcome-media/upload", response_model=WelcomeMediaResponse)
async def upload_central_welcome_media(
    file: UploadFile = File(...),
    admin: dict = Depends(require_platform_admin),
) -> WelcomeMediaResponse:
    path, kind = await _store_welcome_upload("central", file)
    current = await _set_central_welcome_media(
        {"enabled": True, "mode": "upload", "file": path, "kind": kind},
    )
    await _audit(admin, "central.welcome_media_uploaded", "platform", {"kind": kind})
    return _welcome_media_response(current)


class CentralAdminIdsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    admin_ids: list[int] = Field(description="Telegram user IDs treated as central bot admins/owners")


@router.put("/central-bot/admin-ids")
async def update_central_admin_ids(
    body: CentralAdminIdsBody,
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    ids = [int(x) for x in body.admin_ids]
    await _platform_config_collection().update_one(
        {"_id": "central_bot"}, {"$set": {"admin_ids": ids}}, upsert=True)
    await _audit(admin, "central.admin_ids_updated", "platform", {"count": len(ids)})
    return {"admin_ids": ids}


class CentralResellerBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = Field(description="Show the 'Bikin Bot Sendiri' reseller entry on the central bot")


@router.put("/central-bot/reseller-enabled")
async def update_central_reseller_enabled(
    body: CentralResellerBody,
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    enabled = bool(body.enabled)
    await _platform_config_collection().update_one(
        {"_id": "central_bot"}, {"$set": {"reseller_enabled": enabled}}, upsert=True)
    await _audit(admin, "central.reseller_enabled_updated", "platform", {"enabled": enabled})
    return {"reseller_enabled": enabled}


_GUIDE_VIDEO_EXTS = {".mp4", ".mov", ".m4v"}
_GUIDE_VIDEO_MAX_BYTES = 50 * 1024 * 1024


@router.get("/central-bot/coupon-guide-video")
async def get_central_coupon_guide_video(
    _: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Shared coupon guide video for all bots (central panel manages it)."""
    doc = await _platform_config_collection().find_one({"_id": "central_bot"}) or {}
    return {"coupon_guide_video": doc.get("coupon_guide_video")}


@router.post("/central-bot/coupon-guide-video/upload")
async def upload_central_coupon_guide_video(
    file: UploadFile = File(...),
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    from welcome_banner import _runtime_base
    name = (file.filename or "").lower()
    ext = os.path.splitext(name)[1]
    if ext not in _GUIDE_VIDEO_EXTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Format tidak didukung. Pakai MP4.",
        )
    data = await file.read()
    if len(data) > _GUIDE_VIDEO_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File maksimal 50MB.",
        )
    dest = _runtime_base() / f"coupon_guide_video{ext}"
    dest.write_bytes(data)
    await _platform_config_collection().update_one(
        {"_id": "central_bot"},
        {"$set": {"coupon_guide_video": str(dest)}},
        upsert=True,
    )
    await _audit(admin, "central.coupon_guide_video_uploaded", "platform", {})
    return {"coupon_guide_video": str(dest)}


# ---------------------------------------------------------------------------
# Domain registry: per-tenant hostnames (storefront, stock panel, api).
# ---------------------------------------------------------------------------

class DomainBody(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    tenant_id: str | None = None
    purpose: str = Field(default="storefront")
    origin: str = Field(default="owner_subdomain")


@router.get("/domains")
async def list_platform_domains(
    tenant_id: str | None = None,
    admin: dict = Depends(require_platform_admin),
) -> list[dict[str, Any]]:
    import domain_registry

    return await domain_registry.list_domains(db.client, tenant_id)


@router.post("/domains", status_code=status.HTTP_201_CREATED)
async def add_platform_domain(
    body: DomainBody,
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    import domain_registry

    try:
        doc = await domain_registry.register_domain(
            db.client,
            domain=body.domain,
            tenant_id=body.tenant_id,
            purpose=body.purpose,
            origin=body.origin,
            created_by=str(admin.get("_id") or admin.get("id") or ""),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    await _audit(admin, "platform.domain_registered", body.domain, {"purpose": body.purpose})
    return doc


@router.delete("/domains/{domain}")
async def delete_platform_domain(
    domain: str,
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    import domain_registry

    removed = await domain_registry.remove_domain(db.client, domain)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain tidak ditemukan.")
    await _audit(admin, "platform.domain_removed", domain, {})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Promo landing config (idseconnect.my.id) — edited from panel.idseconnect.my.id
# ---------------------------------------------------------------------------

@router.get("/promo-config")
async def get_promo_config_admin(
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    from promo_config import get_promo_config

    return await get_promo_config()


@router.put("/promo-config")
async def update_promo_config_admin(
    body: dict[str, Any],
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    from promo_config import (
        ACCENTS,
        BUTTON_STYLES,
        _platform_config_collection,
        _sanitize_buttons,
        get_promo_config,
    )

    data = dict(body or {})
    if "buttons" in data:
        if not isinstance(data["buttons"], list):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "buttons harus list.")
        data["buttons"] = _sanitize_buttons(data["buttons"])
    if "accent" in data and data["accent"] not in ACCENTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Warna aksen tidak dikenal.")
    # Only allow known top-level keys.
    allowed = {
        "site_name", "promo_domain", "whatsapp_number", "accent", "hero", "buttons",
        "highlights", "sections", "features_title", "steps_title",
        "faq_title", "final_cta",
    }
    data = {k: v for k, v in data.items() if k in allowed}
    coll = _platform_config_collection()
    await coll.update_one({"_id": "promo_config"}, {"$set": data}, upsert=True)
    await _audit(admin, "platform.promo_config_updated", "promo", {})
    return await get_promo_config()


# ---------------------------------------------------------------------------
# Database browser (platform admin only)
# ---------------------------------------------------------------------------

@router.get("/database/collections")
async def list_collections(
    _: dict = Depends(require_platform_admin),
) -> dict:
    """List semua collection di platform database."""
    names = await db.list_collection_names()
    result = []
    for name in sorted(names):
        try:
            count = await db[name].estimated_document_count()
        except Exception:
            count = -1
        result.append({"name": name, "count": count})
    return {"collections": result}


@router.get("/database/collections/{name}")
async def browse_collection(
    name: str,
    limit: int = 20,
    skip: int = 0,
    _: dict = Depends(require_platform_admin),
) -> dict:
    """Lihat dokumen dalam collection (max 100 per request)."""
    limit = min(max(limit, 1), 100)
    skip = max(skip, 0)
    cursor = db[name].find().skip(skip).limit(limit)
    docs = []
    async for doc in cursor:
        # Convert ObjectId & datetime ke string biar JSON-safe
        docs.append(_json_safe(doc))
    total = await db[name].estimated_document_count()
    return {"collection": name, "docs": docs, "total": total, "skip": skip, "limit": limit}


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
