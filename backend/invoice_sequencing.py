"""Pure module for invoice reference composition, validation, and counter initialization.

Enforces:
- IDSE legacy invoice format: INV-YYYYMMDD-NNNN (unchanged)
- Non-IDSE / V2 tenant invoice format: INV-{TENANT}-{YYYYMMDD}-{NNNN} (globally safe)
"""

import re
from typing import Any

_LEGACY_INV_RE = re.compile(r"^INV-(\d{8})-(\d{4,})$")
_V2_INV_RE = re.compile(r"^INV-([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)-(\d{8})-(\d{4,})$")


def compose_invoice_reference(tenant_id: str, date_str: str, seq: int) -> str:
    if not tenant_id or not isinstance(tenant_id, str):
        raise ValueError("tenant_id must be a non-empty string")
    if not isinstance(seq, int) or seq < 1:
        raise ValueError("sequence must be a positive integer >= 1")
    if not isinstance(date_str, str) or not re.match(r"^\d{8}$", date_str):
        raise ValueError("date must be an 8-digit string in YYYYMMDD format")
    
    clean_tenant = tenant_id.strip()
    if not clean_tenant:
        raise ValueError("tenant_id must be a non-empty string")
    
    if clean_tenant.lower() == "idse":
        return f"INV-{date_str}-{seq:04d}"
    return f"INV-{clean_tenant.upper()}-{date_str}-{seq:04d}"


def counter_initial_value() -> int:
    return 0


def invoice_counter_key(tenant_id: str, date_str: str) -> str:
    clean_tenant = tenant_id.strip() if isinstance(tenant_id, str) else str(tenant_id)
    if clean_tenant.lower() == "idse":
        return f"invoice:{date_str}"
    return f"invoice:{clean_tenant.lower()}:{date_str}"



def parse_invoice_reference(ref: Any) -> dict | None:
    if not isinstance(ref, str):
        return None

    legacy_match = _LEGACY_INV_RE.match(ref)
    if legacy_match:
        date_str, seq_str = legacy_match.groups()
        return {
            "tenant_id": "idse",
            "date_str": date_str,
            "seq": int(seq_str),
            "is_legacy": True,
        }

    v2_match = _V2_INV_RE.match(ref)
    if v2_match:
        tenant_str, date_str, seq_str = v2_match.groups()
        return {
            "tenant_id": tenant_str.lower(),
            "date_str": date_str,
            "seq": int(seq_str),
            "is_legacy": False,
        }

    return None


def is_valid_invoice_reference(ref: Any, tenant_id: str | None = None) -> bool:
    parsed = parse_invoice_reference(ref)
    if not parsed:
        return False
    if tenant_id is not None and parsed["tenant_id"] != tenant_id.lower():
        return False
    return True



