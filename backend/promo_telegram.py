import os
from datetime import datetime, timezone
from cryptography.fernet import Fernet
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

from db import db
from promo_service import now_iso

_pending = {}

def _fernet():
    key = os.environ.get("TG_SESSION_KEY", "").strip()
    if not key:
        raise RuntimeError("TG_SESSION_KEY wajib diisi untuk modul Telegram.")
    return Fernet(key.encode())

def _api():
    api_id = int(os.environ.get("TG_API_ID", "0"))
    api_hash = os.environ.get("TG_API_HASH", "").strip()
    if not api_id or not api_hash:
        raise RuntimeError("TG_API_ID dan TG_API_HASH wajib diisi.")
    return api_id, api_hash

def encrypt_session(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()

def decrypt_session(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()

def _safe_account(doc):
    if not doc:
        return None
    out = dict(doc)
    out.pop("session_encrypted", None)
    out.pop("phone", None)
    out.pop("login_phone", None)
    return out

async def list_accounts():
    return [_safe_account(x) async for x in db.tg_accounts.find({}).sort("created_at", -1)]

async def begin_login(account_id: str, phone: str):
    api_id, api_hash = _api()
    phone = phone.strip()
    if not phone.startswith("+"):
        raise ValueError("Nomor Telegram harus memakai format internasional, contoh +62812...")
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
    except Exception:
        await client.disconnect()
        raise
    _pending[account_id] = {
        "client": client,
        "phone": phone,
        "phone_code_hash": sent.phone_code_hash,
        "created_at": datetime.now(timezone.utc),
    }
    await db.tg_accounts.update_one(
        {"_id": account_id},
        {"$set": {"status": "otp_pending", "phone_masked": phone[:4] + "****" + phone[-3:], "updated_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True, "status": "otp_pending"}

async def verify_login(account_id: str, code: str, password: str | None = None):
    pending = _pending.get(account_id)
    if not pending:
        raise ValueError("Sesi OTP tidak ditemukan atau sudah kedaluwarsa.")
    client = pending["client"]
    try:
        try:
            await client.sign_in(
                pending["phone"],
                code=code.strip(),
                phone_code_hash=pending["phone_code_hash"],
            )
        except SessionPasswordNeededError:
            if not password:
                return {"ok": False, "status": "password_required"}
            await client.sign_in(password=password)
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            raise ValueError("Kode OTP Telegram tidak valid atau sudah kedaluwarsa.")

        me = await client.get_me()
        session = client.session.save()
        account = {
            "_id": account_id,
            "tg_user_id": me.id,
            "username": getattr(me, "username", "") or "",
            "name": " ".join(filter(None, [getattr(me, "first_name", ""), getattr(me, "last_name", "")])),
            "status": "active",
            "session_encrypted": encrypt_session(session),
            "phone_masked": pending["phone"][:4] + "****" + pending["phone"][-3:],
            "last_login_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.tg_accounts.update_one({"_id": account_id}, {"$set": account}, upsert=True)
        await client.disconnect()
        _pending.pop(account_id, None)
        return {"ok": True, "status": "active", "account": _safe_account(account)}
    except Exception:
        raise

async def revoke_account(account_id: str):
    doc = await db.tg_accounts.find_one({"_id": account_id})
    if not doc:
        raise ValueError("Akun Telegram tidak ditemukan.")
    await db.tg_accounts.update_one(
        {"_id": account_id},
        {"$set": {"status": "revoked", "session_encrypted": None, "updated_at": now_iso()}}
    )
    pending = _pending.pop(account_id, None)
    if pending:
        try:
            await pending["client"].disconnect()
        except Exception:
            pass
    return {"ok": True}

async def check_account(account_id: str):
    doc = await db.tg_accounts.find_one({"_id": account_id})
    if not doc or not doc.get("session_encrypted"):
        raise ValueError("Session akun tidak tersedia.")
    api_id, api_hash = _api()
    client = TelegramClient(StringSession(decrypt_session(doc["session_encrypted"])), api_id, api_hash)
    await client.connect()
    try:
        me = await client.get_me()
        status = "active" if me else "logged_out"
        await db.tg_accounts.update_one({"_id": account_id}, {"$set": {"status": status, "updated_at": now_iso()}})
        return {"status": status, "username": getattr(me, "username", "") if me else ""}
    except Exception:
        await db.tg_accounts.update_one({"_id": account_id}, {"$set": {"status": "logged_out", "updated_at": now_iso()}})
        return {"status": "logged_out"}
    finally:
        await client.disconnect()
