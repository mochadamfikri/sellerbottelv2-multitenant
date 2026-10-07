import uuid
from fastapi import APIRouter, HTTPException

from pydantic import BaseModel, Field
from db import db
from promo_campaign import create_campaign, enqueue_campaign, approve_job, opt_out, import_private_chats, sync_groups, now_iso

router = APIRouter()

class CampaignBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    template: str = Field(min_length=1, max_length=4000)
    source_code: str = ""
    bot_link: str = ""
    product_id: str | None = None
    account_ids: list[str] = []
    approval_required: bool = True
    daily_limit: int = Field(default=20, ge=1, le=100)
    min_interval_seconds: int = Field(default=300, ge=300, le=86400)
    send_window_start: str = "09:00"
    send_window_end: str = "21:00"

class OptOutBody(BaseModel):
    tg_user_id: int
    reason: str = "user_request"

class ManualPostBody(BaseModel):
    account_id: str
    group_id: int
    message: str = Field(min_length=1, max_length=4000)

class ManualUserMessageBody(BaseModel):
    account_id: str
    prospect_id: str
    message: str = Field(min_length=1, max_length=4000)

@router.get("/campaigns")
async def campaigns():
    return await db.outreach_campaigns.find({}).sort("created_at", -1).to_list(500)

@router.post("/campaigns")
async def campaign_create(body: CampaignBody):
    try: return await create_campaign(body.model_dump())
    except Exception as exc: raise HTTPException(400, str(exc))

@router.post("/campaigns/{campaign_id}/enqueue")
async def campaign_enqueue(campaign_id: str):
    try: return await enqueue_campaign(campaign_id)
    except Exception as exc: raise HTTPException(400, str(exc))

@router.post("/jobs/{job_id}/approve")
async def job_approve(job_id: str):
    try: return await approve_job(job_id)
    except Exception as exc: raise HTTPException(400, str(exc))

@router.get("/jobs")
async def jobs(status: str | None = None):
    q = {"status": status} if status else {}
    return await db.outreach_jobs.find(q).sort("created_at", -1).limit(500).to_list(500)

@router.post("/opt-out")
async def optout(body: OptOutBody):
    try: return await opt_out(body.tg_user_id, body.reason)
    except Exception as exc: raise HTTPException(400, str(exc))

@router.post("/accounts/{account_id}/import-private")
async def import_private(account_id: str):
    try: return await import_private_chats(account_id)
    except Exception as exc: raise HTTPException(400, str(exc))

@router.post("/accounts/{account_id}/sync-groups")
async def groups_sync(account_id: str):
    try: return await sync_groups(account_id)
    except Exception as exc: raise HTTPException(400, str(exc))

@router.get("/groups")
async def groups(account_id: str | None = None):
    query = {"account_id": account_id} if account_id else {}
    return await db.tg_groups.find(query).sort("title", 1).to_list(500)

@router.post("/prospects/{prospect_id}/send")
async def send_user_message(prospect_id: str, body: ManualUserMessageBody):
    from promo_telegram import decrypt_session, _api
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.types import InputPeerUser, InputPeerChat, InputPeerChannel

    prospect = await db.prospects.find_one({"_id": prospect_id})
    if not prospect:
        raise HTTPException(404, "Prospek tidak ditemukan.")
    if not prospect.get("contact_allowed"):
        raise HTTPException(403, "Prospek belum mengizinkan kontak.")
    if await db.promo_suppressions.find_one({"tg_user_id": prospect["tg_user_id"]}):
        raise HTTPException(403, "Prospek berada di suppression/opt-out list.")

    account = await db.tg_accounts.find_one({
        "_id": body.account_id,
        "status": "active",
        "session_encrypted": {"$type": "string"},
    })
    if not account:
        raise HTTPException(400, "Akun Telegram tidak aktif atau belum memiliki session.")

    api_id, api_hash = _api()
    client = TelegramClient(
        StringSession(decrypt_session(account["session_encrypted"])),
        api_id,
        api_hash,
    )
    await client.connect()
    sent_at = now_iso()
    try:
        username = (prospect.get("username") or "").strip().lstrip("@")
        access_hash = prospect.get("access_hash")
        if username:
            target = await client.get_entity(username)
        elif access_hash is not None:
            target = InputPeerUser(int(prospect["tg_user_id"]), int(access_hash))
        else:
            raise ValueError("Prospek belum memiliki access_hash/username. Sinkronkan ulang daftar prospek dari akun Telegram tersebut.")
        await client.send_message(target, body.message)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    finally:
        await client.disconnect()

    await db.outreach_jobs.insert_one({
        "_id": str(uuid.uuid4()),
        "campaign_id": None,
        "prospect_id": prospect_id,
        "account_id": body.account_id,
        "status": "sent",
        "scheduled_at": None,
        "attempts": 1,
        "last_error": None,
        "sent_at": sent_at,
        "manual": True,
        "created_at": sent_at,
        "updated_at": sent_at,
    })
    await db.prospects.update_one(
        {"_id": prospect_id},
        {"$set": {"status": "contacted", "last_contacted_at": sent_at},
         "$inc": {"contact_count": 1}},
    )
    await db.promo_events.insert_one({
        "_id": f"manual_message:{body.account_id}:{prospect_id}:{sent_at}",
        "type": "manual_message",
        "account_id": body.account_id,
        "tg_user_id": prospect["tg_user_id"],
        "prospect_id": prospect_id,
        "created_at": sent_at,
    })
    return {"ok": True, "sent_at": sent_at}

@router.get("/results/sources")
async def result_sources():
    rows = []
    async for row in db.purchases.aggregate([{"$match": {"source_code": {"$nin": [None, ""]}}}, {"$group": {"_id": "$source_code", "orders": {"$sum": 1}, "revenue": {"$sum": "$total"}}}, {"$sort": {"orders": -1}}]):
        rows.append(row)
    return rows

@router.get("/results")
async def results():
    return {
        "sent": await db.outreach_jobs.count_documents({"status": "sent"}),
        "failed": await db.outreach_jobs.count_documents({"status": "failed"}),
        "queued": await db.outreach_jobs.count_documents({"status": {"$in": ["queued","approved"]}}),
        "opt_out": await db.prospects.count_documents({"status": "opt_out"}),
        "replied": await db.prospects.count_documents({"status": "replied"}),
        "interested": await db.prospects.count_documents({"status": "interested"}),
        "customers": await db.prospects.count_documents({"status": "customer"}),
    }

@router.patch("/campaigns/{campaign_id}/stop")
async def campaign_stop(campaign_id: str):
    result = await db.outreach_campaigns.update_one({"_id": campaign_id}, {"$set": {"status": "stopped", "updated_at": now_iso(), "stop_reason": "admin"}})
    if not result.modified_count: raise HTTPException(404, "Campaign tidak ditemukan.")
    await db.outreach_jobs.update_many({"campaign_id": campaign_id, "status": {"$in": ["queued","approved"]}}, {"$set": {"status": "cancelled", "updated_at": now_iso()}})
    return {"ok": True}

@router.post("/groups/{group_id}/post")
async def post_group(body: ManualPostBody, group_id: str):
    # Manual admin-approved group posting only.
    from promo_telegram import decrypt_session, _api
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.types import InputPeerChat, InputPeerChannel
    account = await db.tg_accounts.find_one({
        "_id": body.account_id,
        "status": "active",
        "session_encrypted": {"$type": "string"},
    })
    if not account:
        raise HTTPException(400, "Akun tidak aktif atau belum memiliki session.")

    group = await db.tg_groups.find_one({
        "account_id": body.account_id,
        "chat_id": int(group_id),
    })
    if not group:
        raise HTTPException(400, "Grup tidak terdaftar untuk akun Telegram yang dipilih. Sinkronkan grup akun tersebut terlebih dahulu.")
    api_id, api_hash = _api()
    client = TelegramClient(StringSession(decrypt_session(account["session_encrypted"])), api_id, api_hash)
    await client.connect()
    try:
        username = (group.get("username") or "").strip().lstrip("@")
        access_hash = group.get("access_hash")
        entity_type = group.get("entity_type")
        if username:
            target = await client.get_entity(username)
        elif entity_type == "channel" and access_hash is not None:
            target = InputPeerChannel(int(group["chat_id"]), int(access_hash))
        elif entity_type == "chat":
            target = InputPeerChat(int(group["chat_id"]))
        else:
            raise ValueError("Grup belum memiliki access_hash/username yang valid. Klik Grup Sinkronisasi lagi menggunakan akun yang dipilih.")
        await client.send_message(target, body.message)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    finally:
        await client.disconnect()
    return {"ok": True}
