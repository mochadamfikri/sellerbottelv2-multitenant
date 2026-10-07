"""Pure tenant database naming and configuration helpers."""

import re
from typing import Mapping


PLATFORM_DATABASE_ENV_VAR = "PLATFORM_DB_NAME"

# Fallback chain for the platform database name:
# 1. PLATFORM_DB_NAME (dedicated, preferred)
# 2. DB_NAME (legacy single-var setups)
# 3. "sellerbottel" (built-in default)
_PLATFORM_DB_FALLBACK_VARS = ("PLATFORM_DB_NAME", "DB_NAME")

_TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?$")
_DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

_RESERVED_DATABASE_NAMES = frozenset({
    "sellerbottel",
    "sellerbottel_mock_only",
    "admin",
    "config",
    "local",
    "platform",
})


def validate_tenant_id(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not _TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise ValueError("tenant ID must be an alphanumeric slug")
    
    # Reject double separators and mixed separator patterns
    if "__" in tenant_id or "_-" in tenant_id or "-_" in tenant_id:
        raise ValueError("tenant ID must be an alphanumeric slug")
    
    return tenant_id


def resolve_platform_database_name(environment: Mapping[str, str]) -> str:
    for var in _PLATFORM_DB_FALLBACK_VARS:
        value = (environment.get(var) or "").strip()
        if value:
            if not _DATABASE_NAME_PATTERN.fullmatch(value):
                raise ValueError(f"{var} must be a valid database name")
            return value
    return "sellerbottel"


def tenant_database_name(tenant_id: str, platform_database_name: str | None = None) -> str:
    validated_id = validate_tenant_id(tenant_id)
    normalized_id = validated_id.lower().replace("-", "_")
    
    # Check if the tenant_id itself is reserved
    if normalized_id in _RESERVED_DATABASE_NAMES:
        raise ValueError(f"tenant ID '{tenant_id}' is reserved")
    
    # Build the full tenant database name
    db_name = "sellerbottel_tenant_" + normalized_id
    
    # Check if the full name collides with reserved names
    if db_name.lower() in _RESERVED_DATABASE_NAMES:
        raise ValueError(f"tenant database name would collide with reserved name")
    
    # Check if it collides with platform database name
    if platform_database_name and db_name.lower() == platform_database_name.lower():
        raise ValueError(f"tenant database name would collide with reserved platform database")
    
    # Reject if the original tenant_id already looks like a reserved full database name
    if validated_id.lower() in _RESERVED_DATABASE_NAMES:
        raise ValueError(f"tenant ID '{tenant_id}' is reserved")
    
    return db_name
