import asyncio
import os
import re
import uuid
from datetime import datetime, timezone, timedelta

from db import db
from promo_service import now_iso
from promo_telegram import decrypt_session
from rates import get_rate
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, PeerFloodError, UserPrivacyRestrictedError

STOP_WORDS = {"stop", "berhenti", "unsubscribe", "berhentiin", "jangan"}
DEFAULT_INTERVAL = max(300, int(os.environ.get("PROMO_MIN_INTERVAL_SECONDS", "300")))
DEFAULT_DAILY_LIMIT = max(1, int(os.environ.get("PROMO_DAILY_LIMIT", "20")))

def _api():
    return int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"]

async def render_message(template: str, prospect: dict, bot_link: str = "", product: dict | None = None):
    name = (prospect.get("name") or prospect.get("username") or "Kak").strip()
    values = {
        "{nama}": name,
        "{username}": prospect.get("username") or "",
        "{bot_link}": bot_link,
        "{produk}": (product or {}).get("name") or "",
        "{harga_usd}": "$" + f"{float((product or {}).get('price_usd') or 0):,.2f}",
        "{harga_idr}": "",
    }
    if product:
        if product.get("price_idr") is not None:
            idr = round(float(product["price_idr"]))
        else:
            rate = await get_rate()
            idr = round(float(product.get("price_usd") or 0) * rate / 100) * 100
        values["{harga_idr}"] = "Rp" + f"{idr:,.0f}".replace(",", ".")
    for key, value in values.items():
        template = template.replace(key, str(value))
    return template

async def create_campaign(data: dict):
    name = str(data.get("name") or "").strip()
    template = str(data.get("template") or "").strip()
    account_ids = list(dict.fromkeys(str(x).strip() for x in (data.get("account_ids") or []) if str(x).strip()))
    if not name or not template:
        raise ValueError("Nama campaign dan template wajib diisi.")
    if not account_ids:
        raise ValueError("Minimal satu akun Telegram aktif harus dipilih.")
    active_count = await db.tg_accounts.count_documents({
        "_id": {"$in": account_ids},
        "status": "active",
        "session_encrypted": {"$type": "string"},
    })
    if active_count != len(account_ids):
        raise ValueError("Semua akun pengirim yang dipilih harus aktif dan memiliki session.")
    doc = {
        "_id": str(uuid.uuid4()), "name": name, "template": template,
        "source_code": str(data.get("source_code") or "").strip().lower(),
        "bot_link": str(data.get("bot_link") or "").strip(),
        "product_id": str(data.get("product_id") or "").strip() or None,
        "account_ids": account_ids,
        "status": "draft", "approval_required": bool(data.get("approval_required", True)),
        "daily_limit": max(1, int(data.get("daily_limit") or DEFAULT_DAILY_LIMIT)),
        "min_interval_seconds": max(300, int(data.get("min_interval_seconds") or DEFAULT_INTERVAL)),
        "send_window_start": data.get("send_window_start") or "09:00",
        "send_window_end": data.get("send_window_end") or "21:00",
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.outreach_campaigns.insert_one(doc)
    return doc

async def enqueue_campaign(campaign_id: str, statuses=("new",)):
    campaign = await db.outreach_campaigns.find_one({"_id": campaign_id})
    if not campaign:
        raise ValueError("Campaign tidak ditemukan.")
    if campaign.get("status") in {"stopped", "completed"}:
        raise ValueError("Campaign sudah dihentikan.")
    query = {"status": {"$in": list(statuses)}, "tg_user_id": {"$exists": True}, "contact_allowed": True}
    count = 0
    account_ids = campaign.get("account_ids") or []
    async for p in db.prospects.find(query).sort("created_at", 1):
        if await db.promo_suppressions.find_one({"tg_user_id": p["tg_user_id"]}):
            continue
        existing = await db.outreach_jobs.find_one({"campaign_id": campaign_id, "prospect_id": p["_id"], "status": {"$in": ["queued","approved","sending","sent"]}})
        if existing:
            continue
        job = {
            "_id": str(uuid.uuid4()), "campaign_id": campaign_id, "prospect_id": p["_id"],
            "account_id": account_ids[count % len(account_ids)],
            "status": "queued" if campaign.get("approval_required", True) else "approved",
            "scheduled_at": None, "attempts": 0, "last_error": None, "sent_at": None,
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        await db.outreach_jobs.insert_one(job)
        count += 1
    await db.outreach_campaigns.update_one({"_id": campaign_id}, {"$set": {"status": "queued", "updated_at": now_iso()}})
    return {"queued": count}

async def approve_job(job_id: str, scheduled_at: str | None = None):
    job = await db.outreach_jobs.find_one({"_id": job_id})
    if not job:
        raise ValueError("Job tidak ditemukan.")
    await db.outreach_jobs.update_one({"_id": job_id}, {"$set": {"status": "approved", "scheduled_at": scheduled_at, "updated_at": now_iso()}})
    return await db.outreach_jobs.find_one({"_id": job_id})

async def opt_out(tg_user_id: int, reason="user_request"):
    await db.promo_suppressions.update_one(
        {"tg_user_id": tg_user_id},
        {"$set": {"tg_user_id": tg_user_id, "reason": reason, "created_at": now_iso()}},
        upsert=True,
    )
    await db.prospects.update_many({"tg_user_id": tg_user_id}, {"$set": {"status": "opt_out", "updated_at": now_iso()}})
    await db.outreach_jobs.update_many({"prospect_id": {"$in": [x["_id"] async for x in db.prospects.find({"tg_user_id": tg_user_id}, {"_id": 1})]}}, {"$set": {"status": "cancelled", "last_error": "opt_out"}})
    return {"ok": True}

async def daily_sent_count(account_id: str):
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return await db.outreach_jobs.count_documents({"account_id": account_id, "status": "sent", "sent_at": {"$gte": start}})

async def send_job(job: dict):
    campaign = await db.outreach_campaigns.find_one({"_id": job["campaign_id"]})
    prospect = await db.prospects.find_one({"_id": job["prospect_id"]})
    account = await db.tg_accounts.find_one({"_id": job["account_id"]})
    product = await db.products.find_one({"_id": campaign.get("product_id"), "active": True}) if campaign.get("product_id") else None
    if not campaign or not prospect or not account or account.get("status") != "active":
        return {"status": "skipped", "reason": "missing_or_inactive"}
    if job.get("scheduled_at"):
        try:
            due = datetime.fromisoformat(job["scheduled_at"])
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < due:
                return {"status": "deferred", "reason": "scheduled_later"}
        except (TypeError, ValueError):
            pass
    if await db.promo_suppressions.find_one({"tg_user_id": prospect["tg_user_id"]}):
        await db.outreach_jobs.update_one({"_id": job["_id"]}, {"$set": {"status": "cancelled", "last_error": "opt_out"}})
        return {"status": "cancelled", "reason": "opt_out"}
    limit = int(campaign.get("daily_limit") or DEFAULT_DAILY_LIMIT)
    if await daily_sent_count(account["_id"]) >= limit:
        return {"status": "deferred", "reason": "daily_limit"}

    start, end = (campaign.get("send_window_start") or "09:00"), (campaign.get("send_window_end") or "21:00")
    now = datetime.now()
    hhmm = now.strftime("%H:%M")
    if not (start <= hhmm <= end):
        return {"status": "deferred", "reason": "outside_send_window"}

    api_id, api_hash = _api()
    client = TelegramClient(StringSession(decrypt_session(account["session_encrypted"])), api_id, api_hash)
    await client.connect()
    try:
        text = await render_message(campaign["template"], prospect, campaign.get("bot_link", ""), product)
        await client.send_message(prospect["tg_user_id"], text)
        sent = now_iso()
        await db.outreach_jobs.update_one({"_id": job["_id"]}, {"$set": {"status": "sent", "sent_at": sent, "updated_at": sent, "last_error": None}, "$inc": {"attempts": 1}})
        await db.prospects.update_one({"_id": prospect["_id"]}, {"$set": {"status": "contacted", "last_contacted_at": sent}, "$inc": {"contact_count": 1}})
        return {"status": "sent"}
    except FloodWaitError as exc:
        await db.tg_accounts.update_one({"_id": account["_id"]}, {"$set": {"status": "limited", "updated_at": now_iso(), "limit_reason": f"FloodWait {exc.seconds}s"}})
        await db.outreach_campaigns.update_one({"_id": campaign["_id"]}, {"$set": {"status": "stopped", "stop_reason": "Telegram FloodWait"}})
        return {"status": "stopped", "reason": "FloodWait"}
    except PeerFloodError:
        await db.tg_accounts.update_one({"_id": account["_id"]}, {"$set": {"status": "limited", "updated_at": now_iso(), "limit_reason": "PeerFlood"}})
        await db.outreach_campaigns.update_one({"_id": campaign["_id"]}, {"$set": {"status": "stopped", "stop_reason": "Telegram PeerFlood"}})
        return {"status": "stopped", "reason": "PeerFlood"}
    except UserPrivacyRestrictedError:
        await db.outreach_jobs.update_one({"_id": job["_id"]}, {"$set": {"status": "failed", "last_error": "privacy_restricted", "updated_at": now_iso()}, "$inc": {"attempts": 1}})
        return {"status": "failed", "reason": "privacy_restricted"}
    finally:
        await client.disconnect()

async def import_private_chats(account_id: str, limit: int = 1000):
    account = await db.tg_accounts.find_one({"_id": account_id})
    if not account or not account.get("session_encrypted"):
        raise ValueError("Akun Telegram tidak memiliki session.")
    api_id, api_hash = _api()
    client = TelegramClient(StringSession(decrypt_session(account["session_encrypted"])), api_id, api_hash)
    await client.connect()
    added = 0
    try:
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel or not dialog.is_user:
                continue
            user = dialog.entity
            if getattr(user, "bot", False) or getattr(user, "deleted", False):
                continue
            tid = int(user.id)
            if await db.bot_users.find_one({"telegram_id": tid}):
                continue
            if await db.promo_suppressions.find_one({"tg_user_id": tid}):
                continue
            exists = await db.prospects.find_one({"owner_account_id": account_id, "tg_user_id": tid})
            if exists:
                continue
            name = " ".join(filter(None, [getattr(user, "first_name", ""), getattr(user, "last_name", "")]))
            await db.prospects.insert_one({
                "_id": str(uuid.uuid4()), "tg_user_id": tid,
                "access_hash": getattr(user, "access_hash", None),
                "username": getattr(user, "username", "") or "", "name": name,
                "owner_account_id": account_id, "source": {"kind": "private_chat", "label": "Telegram"},
                "status": "new", "bot_user_tid": None, "contact_allowed": False, "contact_count": 0,
                "last_contacted_at": None, "notes": "", "created_at": now_iso(),
            })
            added += 1
            if added >= limit:
                break
    finally:
        await client.disconnect()
    return {"added": added}

async def sync_groups(account_id: str):
    account = await db.tg_accounts.find_one({"_id": account_id})
    if not account or not account.get("session_encrypted"):
        raise ValueError("Akun Telegram tidak memiliki session.")
    api_id, api_hash = _api()
    client = TelegramClient(StringSession(decrypt_session(account["session_encrypted"])), api_id, api_hash)
    await client.connect()
    count = 0
    try:
        async for dialog in client.iter_dialogs():
            if not dialog.is_group:
                continue
            entity = dialog.entity
            await db.tg_groups.update_one(
                {"account_id": account_id, "chat_id": int(entity.id)},
                {"$set": {"account_id": account_id, "chat_id": int(entity.id), "title": dialog.name, "username": getattr(entity, "username", "") or "", "access_hash": getattr(entity, "access_hash", None), "entity_type": "channel" if getattr(entity, "access_hash", None) is not None else "chat", "updated_at": now_iso()}, "$setOnInsert": {"_id": str(uuid.uuid4()), "created_at": now_iso()}},
                upsert=True,
            )
            count += 1
    finally:
        await client.disconnect()
    return {"groups": count}
