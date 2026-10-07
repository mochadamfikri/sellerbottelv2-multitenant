"""Configurable subscription pricing for the V2 platform control plane.

The owner sets every commercial number here through the Platform Control
Center API — no subscription price, reminder schedule, grace period, or plan
feature list is hard-coded anywhere in the codebase.

A mode whose price is ``None`` (or whose ``enabled`` flag is off) is simply
not offered.  The rest of the platform must read prices through
:func:`get_subscription_pricing` (or the :func:`get_mode_price` helper),
never from constants.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from db import db

# Subscription modes are authoritative from the owner's requirement document.
SUBSCRIPTION_MODES = ("demo", "monthly", "yearly", "lifetime")

_CONFIG_DOC_ID = "current"
_COLLECTION = "subscription_pricing_config"


class SubscriptionModeConfig(BaseModel):
    """Per-mode commercial terms.  All numbers are owner-configured."""

    model_config = ConfigDict(extra="forbid")

    price: float | None = Field(default=None, ge=0)
    currency: str = Field(default="IDR", min_length=1, max_length=8)
    enabled: bool = True
    feature_limits: dict[str, Any] = Field(default_factory=dict)


class SubscriptionPricingConfig(BaseModel):
    """The whole platform pricing document.  Defaults are intentionally empty."""

    model_config = ConfigDict(extra="forbid")

    modes: dict[str, SubscriptionModeConfig] = Field(default_factory=dict)
    reminder_schedule_days: list[int] | None = None
    grace_period_days: int | None = Field(default=None, ge=0)

    @field_validator("modes")
    @classmethod
    def _known_modes(cls, modes: dict[str, SubscriptionModeConfig]):
        normalized: dict[str, SubscriptionModeConfig] = {}
        for name, cfg in modes.items():
            key = str(name).strip().lower()
            if key not in SUBSCRIPTION_MODES:
                raise ValueError(f"Unknown subscription mode: {name!r}")
            normalized[key] = cfg
        return normalized

    @field_validator("reminder_schedule_days")
    @classmethod
    def _non_negative_reminder_days(cls, days: list[int] | None):
        if days is not None and any(int(d) < 0 for d in days):
            raise ValueError("reminder_schedule_days must be non-negative")
        return days


def _collection():
    return db[_COLLECTION]


def default_pricing_config() -> SubscriptionPricingConfig:
    """The platform default: nothing priced, nothing offered, nothing invented."""
    return SubscriptionPricingConfig()


async def get_subscription_pricing() -> SubscriptionPricingConfig:
    """Single accessor the platform uses to read subscription prices.

    Returns the owner-configured document, or the empty default when the
    owner has not configured anything yet.
    """
    doc = await _collection().find_one({"_id": _CONFIG_DOC_ID})
    if not doc:
        return default_pricing_config()
    data = {k: v for k, v in dict(doc).items() if k not in ("_id", "updated_at")}
    try:
        return SubscriptionPricingConfig(**data)
    except Exception:
        # A document written by an older schema must never break price reads.
        return default_pricing_config()


async def save_subscription_pricing(
    config: SubscriptionPricingConfig,
) -> SubscriptionPricingConfig:
    payload = config.model_dump()
    payload["_id"] = _CONFIG_DOC_ID
    payload["updated_at"] = datetime.now(timezone.utc)
    await _collection().replace_one({"_id": _CONFIG_DOC_ID}, payload, upsert=True)
    return config


async def get_pricing_updated_at() -> datetime | None:
    doc = await _collection().find_one({"_id": _CONFIG_DOC_ID}, {"updated_at": 1})
    if doc:
        return doc.get("updated_at")
    return None


async def get_mode_price(mode: str) -> tuple[float | None, str]:
    """Return ``(price, currency)`` for one mode.

    ``(None, currency)`` means the mode is not offered (unpriced or disabled).
    """
    config = await get_subscription_pricing()
    mode_cfg = config.modes.get(str(mode).strip().lower())
    if mode_cfg is None or not mode_cfg.enabled:
        return None, "IDR"
    return mode_cfg.price, mode_cfg.currency


def is_mode_offered_sync(config: SubscriptionPricingConfig, mode: str) -> bool:
    mode_cfg = config.modes.get(str(mode).strip().lower())
    return bool(mode_cfg and mode_cfg.enabled and mode_cfg.price is not None)
