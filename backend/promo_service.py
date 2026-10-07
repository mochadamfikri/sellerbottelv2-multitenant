import re
import uuid
import hashlib
from datetime import datetime, timezone

from db import db


COUPON_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,31}$")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_coupon_code(code: str) -> str:
    return re.sub(r"\s+", "", str(code or "")).upper()


async def create_coupon(data: dict):
    prepared = prepare_coupon(data)
    existing = await db.promo_coupons.find_one({"code": prepared["code"]})
    if existing:
        raise ValueError("Kode kupon sudah digunakan.")

    doc = {
        "_id": str(uuid.uuid4()),
        **prepared,
        "used_count": 0,
        "created_at": now_iso(),
    }
    await db.promo_coupons.insert_one(doc)
    return doc


def coupon_is_time_valid(coupon: dict, at: datetime | None = None) -> bool:
    at = at or datetime.now(timezone.utc)
    for field, is_start in (("starts_at", True), ("ends_at", False)):
        raw = coupon.get(field)
        if not raw:
            continue
        try:
            value = datetime.fromisoformat(raw)
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return False
        if is_start and at < value:
            return False
        if not is_start and at > value:
            return False
    return True


def prepare_coupon(data: dict) -> dict:
    code = normalize_coupon_code(data.get("code"))
    if not COUPON_CODE_RE.fullmatch(code):
        raise ValueError("Kode kupon harus 3-32 karakter: A-Z, 0-9, _ atau -.")
    kind = data.get("type")
    if kind not in {"percent", "fixed"}:
        raise ValueError("Jenis kupon tidak valid.")
    value = float(data.get("value") or 0)
    if value <= 0 or (kind == "percent" and value > 100):
        raise ValueError("Nilai kupon tidak valid.")
    quota = data.get("quota_total")
    quota = None if quota in (None, "", 0) else int(quota)
    if quota is not None and quota < 1:
        raise ValueError("Kuota harus minimal 1.")
    per_user = int(data.get("per_user_limit") or 1)
    if per_user < 1:
        raise ValueError("Batas per pengguna harus minimal 1.")
    min_purchase = float(data.get("min_purchase") or 0)
    if min_purchase < 0:
        raise ValueError("Minimum pembelian tidak boleh negatif.")
    max_discount = data.get("max_discount")
    max_discount = None if max_discount in (None, "", 0) else float(max_discount)
    if max_discount is not None and max_discount <= 0:
        raise ValueError("Batas maksimum diskon harus lebih dari 0.")
    currency = data.get("currency") or "IDR"
    if currency not in {"IDR", "USD"}:
        raise ValueError("Currency kupon tidak valid.")
    dates = {}
    for field in ("starts_at", "ends_at"):
        raw = data.get(field)
        if not raw:
            dates[field] = None
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            dates[field] = parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            raise ValueError(f"Tanggal {field} tidak valid.")
    if dates["starts_at"] and dates["ends_at"] and datetime.fromisoformat(dates["ends_at"]) <= datetime.fromisoformat(dates["starts_at"]):
        raise ValueError("Tanggal berakhir harus setelah tanggal mulai.")
    return {
        "code": code, "type": kind, "value": value, "currency": currency,
        "quota_total": quota, "per_user_limit": per_user, "min_purchase": min_purchase,
        "max_discount": max_discount,
        "product_ids": list(dict.fromkeys(str(x) for x in (data.get("product_ids") or []) if str(x))),
        "starts_at": dates["starts_at"], "ends_at": dates["ends_at"],
        "active": bool(data.get("active", True)),
    }


async def update_coupon(coupon_id: str, data: dict):
    prepared = prepare_coupon(data)
    current = await db.promo_coupons.find_one({"_id": coupon_id}, {"used_count": 1})
    if not current:
        return None
    if prepared["quota_total"] is not None and prepared["quota_total"] < int(current.get("used_count") or 0):
        raise ValueError("Kuota total tidak boleh lebih kecil dari jumlah kupon yang sudah digunakan.")
    if await db.promo_coupons.find_one({"code": prepared["code"], "_id": {"$ne": coupon_id}}, {"_id": 1}):
        raise ValueError("Kode kupon sudah digunakan.")
    result = await db.promo_coupons.update_one({"_id": coupon_id}, {"$set": {**prepared, "updated_at": now_iso()}})
    return await db.promo_coupons.find_one({"_id": coupon_id}) if result.matched_count else None


def _buyer_filter(buyer):
    if isinstance(buyer, dict):
        if buyer.get("customer_id"):
            return {"customer_id": str(buyer["customer_id"])}
        return {"user_tid": buyer.get("user_tid")}
    return {"user_tid": buyer}


def _buyer_usage_id(buyer):
    identity = _buyer_filter(buyer)
    key, value = next(iter(identity.items()))
    return hashlib.sha256(f"{key}:{value}".encode()).hexdigest(), identity


async def validate_coupon(code: str, buyer, currency: str, subtotal: float, product_ids: list[str]):
    code = normalize_coupon_code(code)
    coupon = await db.promo_coupons.find_one({"code": code, "active": True})
    if not coupon:
        return None, "Kupon tidak ditemukan atau sudah tidak aktif."

    if not coupon_is_time_valid(coupon):
        return None, "Kupon belum aktif atau sudah kedaluwarsa."

    if coupon.get("currency") != currency:
        return None, "Kupon hanya berlaku untuk currency yang sesuai."

    quota = coupon.get("quota_total")
    if quota is not None and int(coupon.get("used_count") or 0) >= int(quota):
        return None, "Kuota kupon sudah habis."

    eligible = coupon.get("product_ids") or []
    if eligible and not set(product_ids).intersection(eligible):
        return None, "Kupon tidak berlaku untuk produk di keranjang."

    used = await db.promo_coupon_redemptions.count_documents({"coupon_id": coupon["_id"], **_buyer_filter(buyer)})
    if used >= int(coupon.get("per_user_limit") or 1):
        return None, "Batas penggunaan kupon untuk akun ini sudah tercapai."

    return coupon, None


def coupon_discount(coupon: dict, amount: float) -> float:
    if not coupon:
        return 0.0
    if coupon["type"] == "percent":
        discount = round(amount * float(coupon["value"]) / 100, 2)
    else:
        discount = min(round(float(coupon["value"]), 2), round(amount, 2))
    maximum = coupon.get("max_discount")
    if maximum is not None:
        discount = min(discount, float(maximum))
    return min(round(discount, 2), round(amount, 2))


async def reserve_coupon(coupon: dict, buyer, order_id: str, discount_amount: float):
    query = {"_id": coupon["_id"], "active": True}
    quota = coupon.get("quota_total")
    if quota is not None:
        query["used_count"] = {"$lt": int(quota)}

    result = await db.promo_coupons.update_one(query, {"$inc": {"used_count": 1}})
    if result.modified_count != 1:
        return False

    usage_id, buyer_query = _buyer_usage_id(buyer)
    usage = await db.promo_coupon_usage.find_one({"_id": f"{coupon['_id']}:{usage_id}"})
    if not usage:
        prior_count = await db.promo_coupon_redemptions.count_documents({"coupon_id": coupon["_id"], **buyer_query})
        try:
            await db.promo_coupon_usage.insert_one({
                "_id": f"{coupon['_id']}:{usage_id}", "coupon_id": coupon["_id"],
                **buyer_query, "count": prior_count, "reservation_ids": [],
            })
        except Exception:
            pass
    usage_result = await db.promo_coupon_usage.update_one(
        {"_id": f"{coupon['_id']}:{usage_id}", "count": {"$lt": int(coupon.get("per_user_limit") or 1)}, "reservation_ids": {"$ne": order_id}},
        {"$inc": {"count": 1}, "$addToSet": {"reservation_ids": order_id}},
    )
    if usage_result.modified_count != 1:
        await db.promo_coupons.update_one({"_id": coupon["_id"], "used_count": {"$gt": 0}}, {"$inc": {"used_count": -1}})
        return False

    try:
        await db.promo_coupon_redemptions.insert_one({
            "_id": str(uuid.uuid4()),
            "coupon_id": coupon["_id"],
            "coupon_code": coupon["code"],
            **buyer_query,
            "order_id": order_id,
            "discount_amount": discount_amount,
            "usage_id": f"{coupon['_id']}:{usage_id}",
            "created_at": now_iso(),
        })
    except Exception:
        await db.promo_coupons.update_one({"_id": coupon["_id"], "used_count": {"$gt": 0}}, {"$inc": {"used_count": -1}})
        await db.promo_coupon_usage.update_one(
            {"_id": f"{coupon['_id']}:{usage_id}", "reservation_ids": order_id},
            {"$inc": {"count": -1}, "$pull": {"reservation_ids": order_id}},
        )
        return False

    return True


async def release_coupon(order_id: str):
    redemption = await db.promo_coupon_redemptions.find_one_and_delete({"order_id": order_id})
    if not redemption:
        return False
    await db.promo_coupons.update_one(
        {"_id": redemption["coupon_id"], "used_count": {"$gt": 0}},
        {"$inc": {"used_count": -1}},
    )
    if redemption.get("usage_id"):
        await db.promo_coupon_usage.update_one(
            {"_id": redemption["usage_id"], "reservation_ids": order_id, "count": {"$gt": 0}},
            {"$inc": {"count": -1}, "$pull": {"reservation_ids": order_id}},
        )
    return True
