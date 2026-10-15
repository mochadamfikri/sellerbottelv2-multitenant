"""Encrypted owner-managed runtime settings for app-level provider configuration.

Bootstrap secrets (Mongo URL, inventory key, JWT and Telegram webhook secret) stay
in the root-only service environment. This module intentionally never returns
secret values to HTTP clients.
"""
from __future__ import annotations

import json
import os
from typing import Any

from inventory import _fernet
from tenant_db import resolve_platform_database_name

DOC_ID = "runtime_env"
SECRET_FIELDS = {"GOPAY_EMAIL", "GOPAY_PASSWORD", "GOPAY_PHONE", "GOPAY_QRIS_STRING"}
VALUE_FIELDS = {"GOPAY_ENABLED", "GOPAY_LOGIN_METHOD", "GOPAY_QR_TIMEOUT_MINUTES", "GOPAY_POLL_INTERVAL"}
DEFAULTS = {
    "GOPAY_ENABLED": "true",
    "GOPAY_LOGIN_METHOD": "password",
    "GOPAY_QR_TIMEOUT_MINUTES": "5",
    "GOPAY_POLL_INTERVAL": "15",
}
LABELS = {
    "GOPAY_ENABLED": "Aktifkan GoPay QRIS",
    "GOPAY_LOGIN_METHOD": "Metode Login GoPay",
    "GOPAY_EMAIL": "Email GoPay",
    "GOPAY_PASSWORD": "Password GoPay",
    "GOPAY_PHONE": "Nomor HP GoPay",
    "GOPAY_QRIS_STRING": "String QRIS GoPay",
    "GOPAY_QR_TIMEOUT_MINUTES": "Batas Waktu QRIS (menit)",
    "GOPAY_POLL_INTERVAL": "Interval Pemeriksaan Pembayaran (detik)",
}

def _collection(client):
    return client[resolve_platform_database_name(os.environ)]["platform_config"]

def _binding() -> str:
    return "platform:runtime-env:v1"

def _seal(values: dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps({"binding": _binding(), "values": values}, separators=(",", ":")).encode()).decode()

def _unseal(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    raw = json.loads(_fernet().decrypt(value.encode()).decode())
    if raw.get("binding") != _binding() or not isinstance(raw.get("values"), dict):
        raise ValueError("Runtime configuration binding invalid")
    return {str(k): str(v) for k, v in raw["values"].items() if k in SECRET_FIELDS | VALUE_FIELDS}

async def load(client) -> dict[str, str]:
    doc = await _collection(client).find_one({"_id": DOC_ID}, {"encrypted": 1}) or {}
    return _unseal(doc.get("encrypted"))

async def hydrate(client) -> None:
    """Load owner-provided provider config into this process only."""
    try:
        values = await load(client)
    except Exception:
        return
    for key, value in values.items():
        if value:
            os.environ[key] = value

def public_status(values: dict[str, str] | None = None) -> dict[str, Any]:
    values = values or {}
    result: dict[str, Any] = {"labels": LABELS, "values": {}, "configured": {}}
    for key in VALUE_FIELDS:
        result["values"][key] = values.get(key) or os.environ.get(key) or DEFAULTS.get(key, "")
    for key in SECRET_FIELDS:
        result["configured"][key] = bool(values.get(key) or os.environ.get(key))
    return result

async def status(client) -> dict[str, Any]:
    return public_status(await load(client))

async def save(client, updates: dict[str, Any]) -> dict[str, Any]:
    current = await load(client)
    for key, value in updates.items():
        if key not in SECRET_FIELDS | VALUE_FIELDS or value is None:
            continue
        value = str(value).strip()
        # Blank secret fields mean "keep existing", never erase by accident.
        if key in SECRET_FIELDS and not value:
            continue
        if key == "GOPAY_ENABLED" and value.lower() not in {"true", "false"}:
            raise ValueError("Aktifkan GoPay QRIS harus bernilai true atau false.")
        if key == "GOPAY_LOGIN_METHOD" and value not in {"password", "email_otp", "otp"}:
            raise ValueError("Metode login GoPay tidak valid.")
        if key in {"GOPAY_QR_TIMEOUT_MINUTES", "GOPAY_POLL_INTERVAL"}:
            if not value.isdigit() or int(value) < 1 or int(value) > 3600:
                raise ValueError("Nilai waktu GoPay tidak valid.")
        current[key] = value
        os.environ[key] = value
    await _collection(client).update_one({"_id": DOC_ID}, {"$set": {"encrypted": _seal(current)}}, upsert=True)
    return public_status(current)
