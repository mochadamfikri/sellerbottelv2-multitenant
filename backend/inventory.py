import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken
from pymongo.errors import BulkWriteError

from db import db

logger = logging.getLogger(__name__)

KEY_ENV = "INVENTORY_ENCRYPTION_KEY"

MISSING_KEY_MESSAGE = (
    "INVENTORY_ENCRYPTION_KEY belum diisi di backend/.env, jadi inventory tidak bisa disimpan. "
    "Buat key dengan: python -c \"from cryptography.fernet import Fernet; "
    "print(Fernet.generate_key().decode())\" lalu isi di .env dan restart backend."
)
INVALID_KEY_MESSAGE = (
    "INVENTORY_ENCRYPTION_KEY tidak valid (harus Fernet key base64 sepanjang 44 karakter). "
    "Perbaiki nilainya di backend/.env lalu restart backend."
)
MISMATCH_KEY_MESSAGE = (
    "INVENTORY_ENCRYPTION_KEY tidak cocok dengan data inventory yang sudah tersimpan. "
    "Kembalikan key yang dipakai sebelumnya di backend/.env lalu restart backend. "
    "Jangan mengganti key selama masih ada data inventory lama."
)


class InventoryError(Exception):
    """Error inventory dengan pesan yang aman ditampilkan ke admin."""

    status_code = 500

    def __init__(self, detail: str, status_code: int | None = None):
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class InventoryConfigError(InventoryError):
    """Konfigurasi server (mis. encryption key) belum benar."""

    status_code = 503


class InventoryWriteError(InventoryError):
    """Data valid tetapi gagal ditulis ke database."""

    status_code = 500


def now_iso():
    return datetime.now(timezone.utc).isoformat()


@lru_cache(maxsize=8)
def _build_fernet(key: str) -> Fernet:
    return Fernet(key.encode("utf-8"))


def _fernet() -> Fernet:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise InventoryConfigError(MISSING_KEY_MESSAGE)
    try:
        return _build_fernet(key)
    except (ValueError, TypeError) as exc:
        raise InventoryConfigError(INVALID_KEY_MESSAGE) from exc


async def encryption_status() -> dict:
    """Diagnosa konfigurasi enkripsi tanpa membocorkan key."""
    status = {"configured": False, "valid": False, "data_readable": None, "message": None}
    if not os.environ.get(KEY_ENV, "").strip():
        status["message"] = MISSING_KEY_MESSAGE
        return status
    status["configured"] = True
    try:
        cipher = _fernet()
    except InventoryConfigError as exc:
        status["message"] = exc.detail
        return status
    status["valid"] = True

    samples = (
        await db.inventory_items.find({"secret": {"$exists": True, "$ne": None}}, {"secret": 1})
        .sort("created_at", -1)
        .limit(3)
        .to_list(3)
    )
    if samples:
        readable = True
        for sample in samples:
            try:
                cipher.decrypt(sample["secret"].encode("utf-8"))
            except (InvalidToken, ValueError, TypeError):
                readable = False
                break
        status["data_readable"] = readable
        if not readable:
            status["message"] = MISMATCH_KEY_MESSAGE
    return status


def normalize_schema(schema: Iterable[str]) -> list[str]:
    result = []
    seen = set()
    for raw in schema or []:
        field = str(raw or "").strip()
        if not field or field in seen:
            continue
        seen.add(field)
        result.append(field)
    return result


def normalize_record(record: dict, schema: list[str] | None = None):
    schema = normalize_schema(schema or list(record.keys()))
    clean = {}
    for field in schema:
        value = record.get(field, "")
        if value is None:
            value = ""
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        clean[field] = str(value).strip()
    if not clean or not any(value for value in clean.values()):
        return None, None, schema

    # File inventory metadata is stored alongside the normal schema fields.
    # The payload remains encrypted with the same Fernet mechanism.
    for meta_key in ("__file_name", "__file_data_b64"):
        if meta_key in record and record.get(meta_key):
            clean[meta_key] = str(record[meta_key])

    canonical = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return clean, fingerprint, schema


def _canonical(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def _check_records(product_id: str, records: list[dict], schema: list[str]):
    """Normalisasi + deteksi duplikat. Return (schema, valid_pairs, duplicate_pairs)."""
    schema = normalize_schema(schema)
    normalized = []
    seen = set()
    for record in records:
        clean, fingerprint, _ = normalize_record(record, schema)
        if not clean or fingerprint in seen:
            continue
        seen.add(fingerprint)
        normalized.append((clean, fingerprint))

    fingerprints = [fingerprint for _, fingerprint in normalized]
    existing = set()
    if fingerprints:
        cursor = db.inventory_items.find(
            {
                "product_id": product_id,
                "fingerprint": {"$in": fingerprints},
            },
            {"fingerprint": 1},
        )
        existing = {doc["fingerprint"] async for doc in cursor}

    valid = [(record, fp) for record, fp in normalized if fp not in existing]
    duplicates = [(record, fp) for record, fp in normalized if fp in existing]
    return schema, valid, duplicates


async def validate_records(product_id: str, records: list[dict], schema: list[str]):
    schema, valid, duplicates = await _check_records(product_id, records, schema)
    return {
        "valid": [record for record, _ in valid],
        "duplicates": [record for record, _ in duplicates],
        "valid_count": len(valid),
        "duplicate_count": len(duplicates),
        "schema": schema,
    }


async def add_records(product_id: str, records: list[dict], schema: list[str]):
    # Cek konfigurasi enkripsi lebih dulu: gagal cepat dengan pesan jelas,
    # sebelum ada pekerjaan database.
    cipher = _fernet()
    schema, valid, duplicates = await _check_records(product_id, records, schema)

    created_at = now_iso()
    docs = []
    for record, fingerprint in valid:
        canonical = _canonical(record)
        docs.append({
            "_id": str(uuid.uuid4()),
            "product_id": product_id,
            "fingerprint": fingerprint,
            "secret": cipher.encrypt(canonical.encode("utf-8")).decode("utf-8"),
            "status": "available",
            "reservation_id": None,
            "order_id": None,
            "user_tid": None,
            "created_at": created_at,
            "reserved_at": None,
            "sold_at": None,
        })

    created = 0
    race_duplicates = 0
    if docs:
        try:
            result = await db.inventory_items.insert_many(docs, ordered=False)
            created = len(result.inserted_ids)
        except BulkWriteError as exc:
            details = exc.details or {}
            created = int(details.get("nInserted", 0))
            errors = details.get("writeErrors") or []
            other = [err for err in errors if err.get("code") != 11000]
            race_duplicates = len(errors) - len(other)
            if other:
                logger.error(
                    "Inventory insert gagal untuk produk %s: kode=%s pesan=%s",
                    product_id, other[0].get("code"), other[0].get("errmsg"),
                )
                raise InventoryWriteError(
                    f"{len(other)} dari {len(docs)} baris gagal disimpan ke database "
                    f"(kode error {other[0].get('code')}). Lihat log backend."
                ) from exc
        except Exception as exc:
            logger.exception("Inventory insert gagal untuk produk %s", product_id)
            raise InventoryWriteError(
                f"Gagal menyimpan inventory ke database ({type(exc).__name__}). Lihat log backend."
            ) from exc

    await db.products.update_one(
        {"_id": product_id},
        {
            "$set": {
                "delivery_type": "inventory",
                "inventory_enabled": True,
                "inventory_schema": schema,
                "updated_at": now_iso(),
            }
        },
    )
    if created:
        from stock_monitor import schedule_stock_scan
        schedule_stock_scan(product_id)
    return {
        "created": created,
        "skipped": len(duplicates) + race_duplicates,
        "valid": [record for record, _ in valid],
        "duplicates": [record for record, _ in duplicates],
        "schema": schema,
    }


async def available_count(product_id: str):
    return await db.inventory_items.count_documents(
        {"product_id": product_id, "status": "available"}
    )


def _decrypt_secret(item: dict):
    cipher = _fernet()
    try:
        decoded = cipher.decrypt(item["secret"].encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise InventoryConfigError(MISMATCH_KEY_MESSAGE) from exc
    try:
        value = json.loads(decoded)
        if isinstance(value, dict):
            return value
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    # Backward compatibility with the old email:password inventory format.
    return {"value": decoded}


def decrypt_items(items):
    return [_decrypt_secret(item) for item in items]


async def reserve_items(product_id: str, quantity: int, reservation_id: str):
    if quantity < 1:
        return []

    reserved = []
    for _ in range(quantity):
        item = await db.inventory_items.find_one_and_update(
            {
                "product_id": product_id,
                "status": "available",
            },
            {
                "$set": {
                    "status": "reserved",
                    "reservation_id": reservation_id,
                    "reserved_at": now_iso(),
                }
            },
            sort=[("_id", 1)],
        )
        if not item:
            await release_items(reservation_id)
            return []
        reserved.append(item)

    return reserved


async def release_items(reservation_id: str):
    product_ids = {item["product_id"] async for item in db.inventory_items.find(
        {"reservation_id": reservation_id, "status": "reserved"}, {"product_id": 1}
    )}
    await db.inventory_items.update_many(
        {"reservation_id": reservation_id, "status": "reserved"},
        {
            "$set": {
                "status": "available",
                "reservation_id": None,
                "reserved_at": None,
            }
        },
    )
    if product_ids:
        from stock_monitor import schedule_stock_scan
        for product_id in product_ids:
            schedule_stock_scan(product_id)


async def commit_items(
    reservation_id: str,
    order_id: str,
    user_tid: int | None,
    customer_id: str | None = None,
):
    product_ids = {item["product_id"] async for item in db.inventory_items.find(
        {"reservation_id": reservation_id, "status": "reserved"}, {"product_id": 1}
    )}
    await db.inventory_items.update_many(
        {"reservation_id": reservation_id, "status": "reserved"},
        {
            "$set": {
                "status": "sold",
                "reservation_id": None,
                "order_id": order_id,
                "user_tid": user_tid,
                "customer_id": customer_id,
                "sold_at": now_iso(),
            }
        },
    )
    if product_ids:
        from stock_monitor import schedule_stock_scan
        for product_id in product_ids:
            schedule_stock_scan(product_id)
