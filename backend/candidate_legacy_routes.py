"""Read-only customer endpoints for the V3 pre-cutover candidate."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from candidate_readonly import is_candidate_readonly
from legacy_customer_adapter import (
    LegacyPasswordResetRequiredError,
    authenticate_legacy_customer,
    resolve_logical_wallet,
)
from legacy_web_reset import password_reset_required
from dependencies import get_tenant_registry
from db import client

router = APIRouter(prefix="/api/candidate/customer", tags=["candidate-customer"])


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


def _secret() -> bytes:
    value = os.environ.get("CANDIDATE_AUTH_SECRET", "")
    if not value:
        raise HTTPException(503, "Candidate customer auth is not configured.")
    return value.encode("utf-8")


def _issue_token(tenant_slug: str, customer_id: str, session_version: int) -> str:
    payload = json.dumps(
        {"tenant": tenant_slug, "customer": customer_id, "session": session_version},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(_secret(), encoded, hashlib.sha256).hexdigest().encode("ascii")
    return (encoded + b"." + signature).decode("ascii")


def _read_token(token: str, tenant_slug: str) -> tuple[str, int]:
    try:
        encoded, signature = token.encode("ascii").split(b".", 1)
        expected = hmac.new(_secret(), encoded, hashlib.sha256).hexdigest().encode("ascii")
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4)))
        if payload.get("tenant") != tenant_slug:
            raise ValueError("tenant")
        customer_id = str(payload.get("customer") or "")
        session_version = payload.get("session")
        if not customer_id or not isinstance(session_version, int):
            raise ValueError("customer")
        return customer_id, session_version
    except (ValueError, UnicodeError, json.JSONDecodeError):
        raise HTTPException(401, "Invalid candidate customer session.")


async def _tenant_database(tenant_slug: str):
    registry = get_tenant_registry()
    tenant = await registry.get_tenant(tenant_slug)
    if not tenant or tenant.get("status") != "active":
        raise HTTPException(404, "Unknown candidate tenant.")
    return client[tenant["database_name"]]


@router.post("/{tenant_slug}/login")
async def login(tenant_slug: str, body: LoginBody) -> dict[str, Any]:
    """Verify an existing legacy hash without writes or rehashing."""
    if not is_candidate_readonly():
        raise HTTPException(503, "This endpoint is available only in candidate_readonly.")
    database = await _tenant_database(tenant_slug)
    customer = await database.store_customers.find_one({"email": body.email.strip().lower()})
    if customer and await password_reset_required(database, customer):
        raise HTTPException(
            403,
            detail={
                "code": "PASSWORD_RESET_REQUIRED",
                "message": "Untuk keamanan, akun lama Anda memerlukan pembaruan password. Silakan reset password untuk melanjutkan.",
            },
        )
    try:
        identity = await authenticate_legacy_customer(database, body.email, body.password)
    except LegacyPasswordResetRequiredError:
        raise HTTPException(
            403,
            detail={
                "code": "PASSWORD_RESET_REQUIRED",
                "message": "Untuk keamanan, akun lama Anda memerlukan pembaruan password. Silakan reset password untuk melanjutkan.",
            },
        )
    if not identity or identity.is_blocked:
        raise HTTPException(401, "Email or password is invalid.")
    wallet = await resolve_logical_wallet(database, identity)
    return {
        "session_token": _issue_token(tenant_slug, identity.id, identity.session_version),
        "wallet": wallet,
        "customer": identity.to_profile_dict(),
    }


@router.get("/{tenant_slug}/profile")
async def profile(tenant_slug: str, authorization: str = Header(default="")) -> dict[str, Any]:
    """Read-only profile lookup scoped by signed tenant-bound session token."""
    token = authorization.removeprefix("Bearer ").strip()
    customer_id, session_version = _read_token(token, tenant_slug)
    database = await _tenant_database(tenant_slug)
    customer = await database.store_customers.find_one({"_id": customer_id})
    if not customer:
        raise HTTPException(404, "Customer not found.")
    if customer.get("session_version", 1) != session_version:
        raise HTTPException(401, "Candidate customer session is no longer valid.")
    if await password_reset_required(database, customer):
        raise HTTPException(403, detail={"code": "PASSWORD_RESET_REQUIRED", "message": "Password reset is required."})
    from legacy_customer_adapter import LegacyCustomerIdentity
    identity = LegacyCustomerIdentity(customer, "web")
    return {"customer": identity.to_profile_dict()}


@router.get("/{tenant_slug}/balance")
async def balance(tenant_slug: str, authorization: str = Header(default="")) -> dict[str, Any]:
    token = authorization.removeprefix("Bearer ").strip()
    customer_id, session_version = _read_token(token, tenant_slug)
    database = await _tenant_database(tenant_slug)
    customer = await database.store_customers.find_one({"_id": customer_id})
    if not customer:
        raise HTTPException(404, "Customer not found.")
    if customer.get("session_version", 1) != session_version:
        raise HTTPException(401, "Candidate customer session is no longer valid.")
    if await password_reset_required(database, customer):
        raise HTTPException(403, detail={"code": "PASSWORD_RESET_REQUIRED", "message": "Password reset is required."})
    from legacy_customer_adapter import LegacyCustomerIdentity
    return {"wallet": await resolve_logical_wallet(database, LegacyCustomerIdentity(customer, "web"))}


@router.get("/{tenant_slug}/history")
async def history(tenant_slug: str) -> dict[str, Any]:
    """First-cutover history policy: explicitly unavailable; archive remains untouched."""
    if is_candidate_readonly():
        raise HTTPException(503, "Historical reads are not enabled for this candidate.")
    raise HTTPException(404, "Not found.")
