"""Candidate read-only runtime mode for V3 pre-cutover.

When CANDIDATE_READONLY=1, all economic/external-write operations are
blocked at the backend/service level.  This is a fail-closed enforcement:
if the flag is set, writes MUST be denied regardless of UI state.

Usage:
    from candidate_readonly import is_candidate_readonly, require_writable
"""

from __future__ import annotations

import os
import logging
import re
from functools import wraps
from typing import Any

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core flag
# ---------------------------------------------------------------------------

def is_candidate_readonly() -> bool:
    """Return True when the runtime is in candidate read-only mode."""
    return os.environ.get("CANDIDATE_READONLY", "").lower() in {"1", "true", "yes"}


# ---------------------------------------------------------------------------
# Route-level guard decorator
# ---------------------------------------------------------------------------

def require_writable(fn):
    """Decorator: reject the request when candidate_readonly is active."""
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        if is_candidate_readonly():
            raise HTTPException(
                status_code=503,
                detail="Operasi ini dinonaktifkan dalam mode candidate_readonly.",
            )
        return await fn(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Middleware: blanket deny for known write-path prefixes
# ---------------------------------------------------------------------------

# Paths (prefix match) that are unconditionally blocked in readonly mode.
_BLOCKED_PREFIXES: tuple[str, ...] = (
    # Telegram webhooks (write path)
    "/api/telegram/webhook",
    "/api/telegram/bot2/webhook",
    # Storefront economic writes
    "/api/store/checkout",
    "/api/store/deposit",
    "/api/store/order",
    # Admin balance / payment / fulfillment
    "/api/admin/balance",
    "/api/admin/orders/fulfill",
    "/api/admin/orders/refund",
    # Payments / Kasera / GoPay hooks
    "/api/payments",
    "/api/kasera",
    "/api/gopay",
    # Reseller financial
    "/api/admin/resellers/payout",
    "/api/admin/resellers/subscription",
    # Inventory mutation
    "/api/admin/inventory/transform",
    "/api/admin/inventory/upload",
    # Broadcast / outreach
    "/api/admin/broadcast",
    "/api/admin/marketing",
    # Promo / coupon redemption
    "/api/admin/promo",
    "/api/promo/redeem",
    # V2 commerce writes
    "/api/v2/tenant/checkout",
    "/api/v2/tenant/deposit",
    "/api/v2/tenant/order",
    "/api/v2/tenant/payment",
    "/api/v2/tenant/inventory/reserve",
    "/api/v2/tenant/inventory/consume",
    "/api/v2/tenant/inventory/release",
    # Public registration economic (deposit/checkout sub-paths)
    "/api/public/tenant/full/orders/fulfill",
    "/api/public/tenant/full/orders/refund",
    "/api/public/tenant/full/broadcasts",
)

# Methods considered safe (read-only).
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Paths that are always allowed regardless of method (health, login, profile reads).
_SAFE_READ_PREFIXES: tuple[str, ...] = (
    "/api/",               # root
    "/api/health",
    "/docs",
    "/openapi.json",
    "/api/analytics",
    "/api/domain-check",
)

_PRIVILEGED_PREFIXES: tuple[str, ...] = (
    "/api/admin",
    "/api/v2/platform",
    "/api/public/tenant/full",
)

_ALLOWED_POST_PATTERNS = (
    re.compile(r"^/api/auth/login$"),
    re.compile(r"^/api/store/login$"),
    re.compile(r"^/api/v2/customer/[a-z0-9-]+/login$"),
    re.compile(r"^/api/public/tenant/login$"),
    re.compile(r"^/api/candidate/customer/[a-z0-9-]+/login$"),
)


class CandidateReadonlyMiddleware(BaseHTTPMiddleware):
    """Middleware that blocks write operations when CANDIDATE_READONLY is set."""

    async def dispatch(self, request: Request, call_next):
        if not is_candidate_readonly():
            return await call_next(request)

        path = request.url.path
        method = request.method

        # Archive/history access is withheld during the pre-cutover candidate
        # regardless of HTTP method, so no historical data can be relabeled.
        if "/history" in path:
            logger.warning("candidate_readonly: history-hidden block %s %s", method, path)
            return JSONResponse(
                status_code=503,
                content={"detail": "Riwayat tidak tersedia untuk kandidat ini."},
            )

        # Candidate owner identity is intentionally unresolved until explicit
        # production authorization. Privileged routes must therefore stay held.
        if any(path.startswith(prefix) for prefix in _PRIVILEGED_PREFIXES):
            from candidate_owner_mapping import resolve_candidate_owner
            resolution = resolve_candidate_owner()
            if not resolution.is_resolved:
                logger.warning("candidate_readonly: owner-held block %s %s", method, path)
                return JSONResponse(
                    status_code=503,
                    content={"detail": f"Owner access held ({resolution.status}): {resolution.detail}"},
                )

        # Read-only requests are allowed.  Login is explicitly allowlisted
        # because it verifies a password but does not persist a session.
        if method in _SAFE_METHODS or any(pattern.fullmatch(path) for pattern in _ALLOWED_POST_PATTERNS):
            return await call_next(request)

        # Block known write prefixes
        if any(path.startswith(p) for p in _BLOCKED_PREFIXES):
            logger.warning("candidate_readonly: blocked %s %s", method, path)
            return JSONResponse(
                status_code=503,
                content={"detail": "Operasi ini dinonaktifkan dalam mode candidate_readonly."},
            )

        # For non-safe methods on unknown paths, block by default (fail-closed)
        if method not in _SAFE_METHODS:
            logger.warning("candidate_readonly: fail-closed block %s %s", method, path)
            return JSONResponse(
                status_code=503,
                content={"detail": "Operasi tulis dinonaktifkan dalam mode candidate_readonly."},
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Worker startup guard
# ---------------------------------------------------------------------------

_BLOCKED_WORKERS = (
    "payment_maintenance",
    "gopay_monitor",
    "bot2_payment_monitor",
    "stock_monitor",
    "daily_recap",
    "followup",
    "reseller_monitor",
    "marketing",
    "physical_expiry",
    "promo_runtime",
    "resume_service_waiters",
    "telegram_webhook_setup",
)


def should_start_worker(worker_name: str) -> bool:
    """Return True only if the worker should be started."""
    if is_candidate_readonly():
        if worker_name in _BLOCKED_WORKERS:
            logger.info("candidate_readonly: skipping worker %s", worker_name)
            return False
    return True


# ---------------------------------------------------------------------------
# External provider client guard
# ---------------------------------------------------------------------------

def guard_external_client(provider_name: str) -> None:
    """Raise if an external provider client is being instantiated in readonly mode."""
    if is_candidate_readonly():
        raise RuntimeError(
            f"candidate_readonly: external provider '{provider_name}' "
            f"must not be instantiated in read-only mode"
        )

# ---------------------------------------------------------------------------
# Direct service-level guard (callable without HTTP request / middleware)
# ---------------------------------------------------------------------------

class CandidateReadonlyError(RuntimeError):
    """Raised when an economic or external write operation is attempted in readonly mode."""
    pass


def assert_service_writable(operation_name: str) -> None:
    """Enforce fail-closed guard directly at the service / business-logic level.

    Must be called by economic functions (checkout, payment creation, deposit,
    inventory reservation, fulfillment, payouts, etc.) regardless of whether
    they were invoked via HTTP, background worker, or direct Python call.
    """
    if is_candidate_readonly():
        logger.warning("CANDIDATE_READONLY_BLOCKED: operation '%s' rejected", operation_name)
        raise CandidateReadonlyError(
            f"CANDIDATE_READONLY_BLOCKED: Operasi '{operation_name}' "
            f"dinonaktifkan dalam mode candidate_readonly."
        )
