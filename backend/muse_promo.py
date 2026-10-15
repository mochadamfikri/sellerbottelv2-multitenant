"""Claim Promo Muse state machine for the central GoPay QRIS bot flow."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from html import escape
import re
import secrets

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from db import db, get_settings
from services import now_iso
from bot_tenant_scope import get_current_scope

ACTIVE = {"AWAITING_CODE", "AWAITING_CONFIRMATION", "PAYMENT_PENDING", "PAYMENT_CONFIRMED", "WAITING_OWNER"}
TERMINAL = {"DONE", "REJECTED", "CANCELLED", "PAYMENT_EXPIRED", "FAILED"}
DEFAULTS = {
    "enabled": True,
    "button_label": "🎁 Claim Promo Muse",
    "product_title": "3B Muse Token",
    "description": "🎁 <b>3B Muse Token</b>\n\nMasukkan kode referral Muse kamu untuk diproses.\n\n⚠️ Pastikan kode referral benar. Kesalahan penulisan kode dapat menyebabkan claim gagal/hangus.",
    "base_price_idr": 15000,
    "percentage_fee": "0.7",
    "admin_fee_idr": 250,
    "warning_text": "⚠️ Pastikan kode referral benar. Kesalahan penulisan kode dapat menyebabkan claim gagal/hangus.",
    "waiting_payment_message": "Silakan scan QRIS di atas dan bayar sampai digit terakhir.",
    "processing_message": "⏳ <b>Pembayaran berhasil.</b>\n\nClaim Promo Muse kamu sedang diproses admin.\n\nMohon tunggu.",
    "success_message": "✅ <b>Claim Promo Muse selesai diproses.</b>\n\nSilakan cek akun Muse kamu.",
    "reject_message": "❌ <b>Claim Promo Muse ditolak.</b>\n\nAlasan:\nKode / akun ini sudah pernah claim promo.",
}

def settings_from(raw: dict | None) -> dict:
    value = dict(DEFAULTS)
    value.update((raw or {}).get("promo_muse") or {})
    value["enabled"] = bool(value.get("enabled"))
    value["button_label"] = str(value["button_label"]).strip() or DEFAULTS["button_label"]
    value["product_title"] = str(value["product_title"]).strip() or DEFAULTS["product_title"]
    value["base_price_idr"] = max(1, int(value["base_price_idr"]))
    value["admin_fee_idr"] = max(0, int(value["admin_fee_idr"]))
    try:
        rate = Decimal(str(value["percentage_fee"]))
    except Exception:
        rate = Decimal(DEFAULTS["percentage_fee"])
    value["percentage_fee"] = str(max(Decimal("0"), min(rate, Decimal("100"))))
    return value

async def config() -> dict:
    return settings_from(await get_settings())

def quote(raw: dict, unique_code: int) -> dict:
    base = int(raw["base_price_idr"])
    fee = int((Decimal(base) * Decimal(raw["percentage_fee"]) / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    admin = int(raw["admin_fee_idr"])
    return {"base_price_idr": base, "percentage_fee_rate": str(raw["percentage_fee"]),
            "percentage_fee_idr": fee, "admin_fee_idr": admin,
            "unique_code_idr": int(unique_code), "final_amount_idr": base + fee + admin + int(unique_code)}

def normalize_referral(value: str) -> str | None:
    code = re.sub(r"\s+", "", str(value or "")).upper()
    return code if re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{2,63}", code) else None

async def ensure_indexes():
    await db.muse_claims.create_index("claim_id", unique=True)
    await db.muse_claims.create_index([("status", 1), ("created_at", -1)])
    await db.muse_claims.create_index("payment_id", unique=True, sparse=True)
    await db.muse_active_claims.create_index("created_at")

async def create_claim(user: dict) -> dict | None:
    claim_id = secrets.token_hex(16)
    lock = {"_id": str(user["telegram_id"]), "claim_id": claim_id, "created_at": now_iso()}
    try:
        await db.muse_active_claims.insert_one(lock)
    except DuplicateKeyError:
        return None
    doc = {"_id": claim_id, "claim_id": claim_id, "telegram_user_id": user["telegram_id"],
           "telegram_chat_id": user["telegram_id"], "telegram_username": user.get("username") or "",
           "status": "AWAITING_CODE", "payment_status": "not_created", "created_at": now_iso(), "updated_at": now_iso()}
    await db.muse_claims.insert_one(doc)
    return doc

async def cancel_claim(claim_id: str, user_id: int | None = None) -> bool:
    query = {"claim_id": claim_id, "status": {"$in": list(ACTIVE)}}
    if user_id is not None:
        query["telegram_user_id"] = int(user_id)
    result = await db.muse_claims.update_one(query, {"$set": {"status": "CANCELLED", "updated_at": now_iso()}})
    if result.modified_count:
        await db.muse_active_claims.delete_one({"_id": str(user_id) if user_id is not None else None, "claim_id": claim_id})
        return True
    return False

async def save_referral(claim_id: str, user_id: int, code: str) -> dict | None:
    normalized = normalize_referral(code)
    if not normalized:
        return None
    return await db.muse_claims.find_one_and_update(
        {"claim_id": claim_id, "telegram_user_id": int(user_id), "status": "AWAITING_CODE"},
        {"$set": {"referral_code": normalized, "status": "AWAITING_CONFIRMATION", "updated_at": now_iso()}},
        return_document=ReturnDocument.AFTER,
    )

async def allocate_unique_code() -> int:
    seq = await db.counters.find_one_and_update({"_id": "muse_unique_code"}, {"$inc": {"value": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    return int(seq["value"])

async def create_payment(claim_id: str, user_id: int) -> tuple[dict, dict] | None:
    claim = await db.muse_claims.find_one_and_update(
        {"claim_id": claim_id, "telegram_user_id": int(user_id), "status": "AWAITING_CONFIRMATION"},
        {"$set": {"status": "PAYMENT_CREATING", "updated_at": now_iso()}}, return_document=ReturnDocument.AFTER,
    )
    if not claim:
        return None
    code = await allocate_unique_code()
    cfg = await config()
    pricing = quote(cfg, code)
    try:
        from gopay_provider import create_gopay_muse_payment
        payment = await create_gopay_muse_payment(claim, pricing)
    except Exception:
        await db.muse_claims.update_one({"claim_id": claim_id, "status": "PAYMENT_CREATING"}, {"$set": {"status": "FAILED", "updated_at": now_iso()}})
        await db.muse_active_claims.delete_one({"_id": str(user_id), "claim_id": claim_id})
        raise
    updated = await db.muse_claims.find_one_and_update(
        {"claim_id": claim_id, "status": "PAYMENT_CREATING"},
        {"$set": {**pricing, "product_title_snapshot": cfg["product_title"], "payment_provider": "gopay_gobiz",
                  "payment_id": payment["payment_id"], "payment_reference": payment["payment_id"], "payment_status": "pending",
                  "payment_created_at": now_iso(), "payment_expires_at": payment["expires_at"].isoformat(),
                  "status": "PAYMENT_PENDING", "updated_at": now_iso()}}, return_document=ReturnDocument.AFTER)
    return updated, payment

def _admin_ids(settings: dict) -> set[int]:
    ids = set()
    for value in [settings.get("admin_telegram_id")]:
        try:
            if value:
                ids.add(int(value))
        except (TypeError, ValueError):
            pass
    scope = get_current_scope()
    for value in getattr(scope, "admin_ids", []) if scope else []:
        try: ids.add(int(value))
        except (TypeError, ValueError): pass
    return ids

def owner_card(claim: dict) -> str:
    username = f"@{escape(str(claim.get('telegram_username') or ''))}" if claim.get("telegram_username") else "-"
    return "🎁 <b>CLAIM PROMO MUSE</b>\n\n" + f"Username: {username}\nUserID: <code>{claim['telegram_user_id']}</code>\nKode referral: <code>{escape(claim.get('referral_code') or '-')}</code>\nStatus: <b>{claim.get('status')}</b>"

def owner_keyboard(claim_id: str) -> dict:
    return {"inline_keyboard": [[{"text": "❌ Reject", "callback_data": f"muse:r:{claim_id}"}, {"text": "✅ Selesai", "callback_data": f"muse:d:{claim_id}"}]]}

async def confirm_verified_payment(payment: dict, tx_id: str) -> bool:
    claim = await db.muse_claims.find_one_and_update(
        {"payment_id": payment["_id"], "status": "PAYMENT_PENDING"},
        {"$set": {"status": "PAYMENT_CONFIRMED", "payment_status": "confirmed", "payment_confirmed_at": now_iso(), "payment_tx_id": tx_id, "updated_at": now_iso()}},
        return_document=ReturnDocument.AFTER,
    )
    if not claim:
        return False
    from tgapi import send_message
    cfg = await config()
    sent = await send_message(claim["telegram_chat_id"], cfg["processing_message"])
    processing_id = ((sent or {}).get("result") or {}).get("message_id")
    claim = await db.muse_claims.find_one_and_update({"claim_id": claim["claim_id"], "status": "PAYMENT_CONFIRMED"}, {"$set": {"status": "WAITING_OWNER", "user_processing_message_id": processing_id, "updated_at": now_iso()}}, return_document=ReturnDocument.AFTER)
    if not claim:
        return False
    for admin_id in _admin_ids(await get_settings()):
        sent = await send_message(admin_id, owner_card(claim), kb=owner_keyboard(claim["claim_id"]))
        result = (sent or {}).get("result") or {}
        await db.muse_claims.update_one({"claim_id": claim["claim_id"]}, {"$set": {"owner_message_chat_id": admin_id, "owner_message_id": result.get("message_id"), "owner_card_sent_at": now_iso()}})
    return True

async def owner_action(claim_id: str, admin_id: int, action: str) -> dict | None:
    if int(admin_id) not in _admin_ids(await get_settings()):
        return None
    status = "DONE" if action == "done" else "REJECTED" if action == "reject" else None
    if not status:
        return None
    return await db.muse_claims.find_one_and_update(
        {"claim_id": claim_id, "status": "WAITING_OWNER"},
        {"$set": {"status": status, "owner_action": action, "owner_action_by": int(admin_id), "owner_action_at": now_iso(), "updated_at": now_iso()}},
        return_document=ReturnDocument.AFTER,
    )

async def finish_owner_action(claim: dict) -> None:
    from tgapi import edit_message, send_message
    cfg = await config()
    await db.muse_active_claims.delete_one({"_id": str(claim["telegram_user_id"]), "claim_id": claim["claim_id"]})
    await send_message(claim["telegram_chat_id"], cfg["success_message"] if claim["status"] == "DONE" else cfg["reject_message"])
    if claim.get("owner_message_chat_id") and claim.get("owner_message_id"):
        await edit_message(claim["owner_message_chat_id"], claim["owner_message_id"], owner_card(claim))

async def expire_pending_claims(now: datetime) -> list[dict]:
    result = []
    async for claim in db.muse_claims.find({"status": "PAYMENT_PENDING", "payment_expires_at": {"$lte": now.isoformat()}}):
        updated = await db.muse_claims.find_one_and_update({"claim_id": claim["claim_id"], "status": "PAYMENT_PENDING"}, {"$set": {"status": "PAYMENT_EXPIRED", "payment_status": "expired", "updated_at": now_iso()}}, return_document=ReturnDocument.AFTER)
        if updated:
            await db.muse_active_claims.delete_one({"_id": str(updated["telegram_user_id"]), "claim_id": updated["claim_id"]})
            result.append(updated)
    return result
