import asyncio
import os
import random
from datetime import datetime, timezone, timedelta

from db import db
from promo_campaign import send_job, render_message
from promo_telegram import decrypt_session, _api
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from tgapi import tg

_clients = {}
_task = None

async def _reply_listener(account):
    api_id, api_hash = _api()
    client = TelegramClient(StringSession(decrypt_session(account["session_encrypted"])), api_id, api_hash)
    await client.connect()

    @client.on(events.NewMessage(incoming=True))
    async def on_message(event):
        sender = await event.get_sender()
        if not sender or not getattr(sender, "id", None) or not event.is_private:
            return
        tid = int(sender.id)
        text = (event.raw_text or "").strip().lower()
        if text in {"stop", "berhenti", "unsubscribe"}:
            from promo_campaign import opt_out
            await opt_out(tid, "reply_stop")
            return
        prospect = await db.prospects.find_one({"tg_user_id": tid})
        if prospect:
            await db.prospects.update_many({"tg_user_id": tid}, {"$set": {"status": "replied", "last_reply_at": datetime.now(timezone.utc).isoformat()}})
            await db.promo_events.insert_one({"_id": f"reply:{account['_id']}:{event.id}", "type": "reply", "account_id": account["_id"], "tg_user_id": tid, "text_preview": (event.raw_text or "")[:500], "created_at": datetime.now(timezone.utc).isoformat()})
            admin_tid = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()
            bot_token = os.environ.get("TELEGRAM_TOKEN", "").strip()
            if admin_tid and bot_token:
                try:
                    await tg("sendMessage", chat_id=int(admin_tid), text=f"📩 Promo reply\nTelegram ID: {tid}\nPesan: {(event.raw_text or '').strip()[:300]}")
                except Exception:
                    pass

    _clients[account["_id"]] = client
    return client

async def load_reply_listeners():
    if os.environ.get("PROMOTION_ENABLED", "").lower() not in {"1","true","yes"}:
        return
    accounts = [x async for x in db.tg_accounts.find({"status": "active", "session_encrypted": {"$type": "string"}})]
    for account in accounts:
        try:
            await _reply_listener(account)
        except Exception:
            await db.tg_accounts.update_one({"_id": account["_id"]}, {"$set": {"status": "logged_out", "updated_at": datetime.now(timezone.utc).isoformat()}})

async def _queue_loop():
    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()
            jobs = [x async for x in db.outreach_jobs.find({
                "status": "approved",
                "$or": [
                    {"scheduled_at": None},
                    {"scheduled_at": {"$lte": now}},
                ],
            }).sort("created_at", 1).limit(20)]
            for job in jobs:
                result = await send_job(job)
                if result.get("status") == "sent":
                    interval = int((await db.outreach_campaigns.find_one({"_id": job["campaign_id"]}) or {}).get("min_interval_seconds") or 300)
                    await asyncio.sleep(random.uniform(max(300, interval), max(300, interval) * 1.5))
                elif result.get("status") in {"stopped", "cancelled", "skipped"}:
                    continue
                elif result.get("status") == "deferred":
                    # Keep a future schedule intact; if no schedule was supplied, back off
                    # instead of hammering Telegram/Mongo every few seconds.
                    if not job.get("scheduled_at"):
                        retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)
                        await db.outreach_jobs.update_one(
                            {"_id": job["_id"], "status": "approved"},
                            {"$set": {"scheduled_at": retry_at.isoformat(), "updated_at": datetime.now(timezone.utc).isoformat()}},
                        )
        except Exception:
            await asyncio.sleep(10)
        await asyncio.sleep(5)

async def start_promo_runtime():
    global _task
    if os.environ.get("PROMOTION_ENABLED", "").lower() not in {"1","true","yes"}:
        return
    await load_reply_listeners()
    _task = asyncio.create_task(_queue_loop())

async def stop_promo_runtime():
    global _task
    if _task:
        _task.cancel()
        _task = None
    for client in list(_clients.values()):
        try:
            await client.disconnect()
        except Exception:
            pass
    _clients.clear()
