import os
import re
from typing import Mapping

_DATABASE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")
_TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")
_PLATFORM_DB_FALLBACK_VARS = ("PLATFORM_DB_NAME", "MONGO_DB_NAME", "DB_NAME")


def validate_tenant_id(tenant_id: str) -> str:
    if not isinstance(tenant_id, str):
        raise ValueError("Tenant ID must be a non-empty string")
    cleaned = tenant_id.strip()
    if not cleaned:
        raise ValueError("Tenant ID must be a non-empty string")
    if not _TENANT_ID_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "Tenant ID contains invalid characters; must contain only letters, numbers, underscores, and hyphens"
        )
    return cleaned


def resolve_platform_database_name(environment: Mapping[str, str]) -> str:
    for var in _PLATFORM_DB_FALLBACK_VARS:
        if var not in environment:
            continue
        raw = environment[var]
        if not isinstance(raw, str):
            raise ValueError(f"{var} must be a valid database name")
        value = raw.strip()
        if not value or not _DATABASE_NAME_PATTERN.fullmatch(value):
            raise ValueError(f"{var} must be a valid database name")
        return value
    return "sellerbottel"
