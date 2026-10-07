"""Safe environment configuration helpers.

This module validates environment-dependent database settings without logging or
otherwise exposing credentials.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


_VALID_ENVIRONMENTS = frozenset({"development", "test", "production"})
_TRUE_VALUES = frozenset({"1", "true", "yes"})
# Production database names that must never be targeted outside production.
# 'sellerbottel': legacy single-tenant production database
# 'sellerbottel_platform': V2 multi-tenant control plane database (standard)
_PRODUCTION_DATABASE_NAMES = frozenset({"sellerbottel", "sellerbottel_platform"})


def get_environment() -> str:
    """Return the normalized deployment environment."""
    environment = os.environ.get("ENVIRONMENT", "development").strip().lower()
    if environment not in _VALID_ENVIRONMENTS:
        raise ValueError(
            "ENVIRONMENT must be one of: development, test, production"
        )
    return environment


def validate_mongo_url(mongo_url: str | None = None) -> None:
    """Reject MongoDB's default port in non-production environments."""
    value = mongo_url if mongo_url is not None else os.environ.get("MONGO_URL", "")
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("MONGO_URL contains an invalid port") from error

    if get_environment() != "production" and port == 27017:
        raise ValueError("MONGO_URL port 27017 is only allowed in production")


def validate_db_name(db_name: str | None = None) -> None:
    """Reject the production database name outside production."""
    value = db_name if db_name is not None else os.environ.get("DB_NAME", "")
    if get_environment() != "production" and value.strip().lower() in _PRODUCTION_DATABASE_NAMES:
        raise ValueError("production database name is not allowed outside production")


def validate_environment() -> str:
    """Validate startup environment settings and return the normalized mode."""
    environment = get_environment()
    validate_mongo_url()
    validate_db_name()
    return environment


def is_external_enabled(flag: str) -> bool:
    """Return whether an explicitly enabled external integration flag is set."""
    return os.environ.get(flag, "").strip().lower() in _TRUE_VALUES


@dataclass(frozen=True, repr=False)
class SafeConfig:
    """Configuration container whose string representations mask credentials."""

    environment: str
    mongo_url: str
    db_name: str
    jwt_secret: str

    def safe_summary(self) -> dict[str, str]:
        """Return non-secret configuration metadata suitable for diagnostics."""
        return {
            "environment": self.environment,
            "db_name": self.db_name,
            "mongo_url": "***",
            "jwt_secret": "***",
        }

    def __repr__(self) -> str:
        return f"SafeConfig({self.safe_summary()!r})"

    __str__ = __repr__
