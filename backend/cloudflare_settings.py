"""Owner-only Cloudflare DNS and wildcard certificate configuration."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from audit_events import write_audit_event
from db import db
from platform_rbac import require_platform_admin
from reseller_service import encrypt_token
from tenant_db import resolve_platform_database_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/platform/cloudflare", tags=["cloudflare"])
_REQUIRED_ZONES = ("idsestock.my.id", "idseconnect.my.id")
_CERT_HELPER = "/usr/local/sbin/sellerbottel-cloudflare-wildcard"


class CloudflareTokenBody(BaseModel):
    """Ephemeral token input. It is never returned or included in audit data."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    api_token: str = Field(min_length=20, max_length=512)


def _config_collection():
    return db.client[resolve_platform_database_name(os.environ)]["platform_config"]


def _masked_hint(token: str) -> str:
    return f"cf_tok_...{token[-4:]}" if len(token) >= 4 else "cf_tok_..."


def _public_status(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config or {}
    return {
        "configured": bool(config.get("token_encrypted")),
        "status": config.get("status") or "not_configured",
        "token_hint": config.get("token_hint"),
        "verified_zones": list(config.get("verified_zones") or []),
        "last_checked": config.get("last_checked"),
        "wildcard_ssl_status": config.get("wildcard_ssl_status") or "not_configured",
        "wildcard_ssl_updated_at": config.get("wildcard_ssl_updated_at"),
    }


async def _cloudflare_get(client: httpx.AsyncClient, path: str, token: str, *, params=None) -> dict[str, Any]:
    try:
        response = await client.get(
            f"https://api.cloudflare.com/client/v4{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
    except httpx.HTTPError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Cloudflare tidak dapat dihubungi. Coba lagi.") from error

    try:
        payload = response.json()
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Respons Cloudflare tidak valid.") from error
    if response.status_code >= 400 or not payload.get("success"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Token Cloudflare tidak valid atau izin token belum mencukupi.")
    return payload


async def verify_cloudflare_token(token: str) -> list[str]:
    """Verify the token and confirm it can inspect every managed zone."""
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        await _cloudflare_get(client, "/user/tokens/verify", token)
        verified_zones: list[str] = []
        for zone_name in _REQUIRED_ZONES:
            payload = await _cloudflare_get(client, "/zones", token, params={"name": zone_name})
            zones = payload.get("result") or []
            if not any(item.get("name") == zone_name for item in zones if isinstance(item, dict)):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(f"Token tidak dapat membaca zone {zone_name}. "
                            "Tambahkan izin Zone:Read dan akses ke kedua zone."),
                )
            verified_zones.append(zone_name)
    return verified_zones


async def _activate_wildcard_certificate(token: str) -> bool:
    """Run the narrow root helper. Token is supplied only over stdin."""
    try:
        process = await asyncio.create_subprocess_exec(
            "sudo", _CERT_HELPER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.communicate((token + "\n").encode()), timeout=240)
    except (OSError, asyncio.TimeoutError) as error:
        logger.warning("Cloudflare wildcard helper did not complete: %s", type(error).__name__)
        return False
    return process.returncode == 0


@router.get("")
async def get_cloudflare_settings(_: dict = Depends(require_platform_admin)) -> dict[str, Any]:
    config = await _config_collection().find_one({"_id": "cloudflare"})
    return _public_status(config)


@router.post("")
async def save_cloudflare_settings(
    body: CloudflareTokenBody,
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    token = body.api_token.strip()
    verified_zones = await verify_cloudflare_token(token)
    now = datetime.now(timezone.utc).isoformat()
    collection = _config_collection()
    await collection.update_one(
        {"_id": "cloudflare"},
        {"$set": {
            "token_encrypted": encrypt_token(token),
            "token_hint": _masked_hint(token),
            "status": "verified",
            "verified_zones": verified_zones,
            "last_checked": now,
            "wildcard_ssl_status": "provisioning",
            "wildcard_ssl_updated_at": now,
        }},
        upsert=True,
    )

    wildcard_ready = await _activate_wildcard_certificate(token)
    ssl_status = "active" if wildcard_ready else "pending"
    await collection.update_one(
        {"_id": "cloudflare"},
        {"$set": {"wildcard_ssl_status": ssl_status,
                  "wildcard_ssl_updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    await write_audit_event(
        actor=str(admin.get("_id") or admin.get("email")),
        action="platform.cloudflare_configured",
        platform="control-plane",
        metadata={"zones": verified_zones, "wildcard_ssl_status": ssl_status},
    )
    config = await collection.find_one({"_id": "cloudflare"})
    result = _public_status(config)
    result["message"] = (
        "Token tersimpan terenkripsi dan wildcard SSL aktif."
        if wildcard_ready else
        "Token tersimpan dan terverifikasi, tetapi wildcard SSL belum aktif. Hubungi administrator server untuk memeriksa helper certbot."
    )
    return result
