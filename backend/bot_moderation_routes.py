import asyncio
import re
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import get_current_admin
from db import db
from tgapi import tg

router = APIRouter(prefix="/api/admin/bot-moderation", dependencies=[Depends(get_current_admin)])


def _public_user(user):
    return {
        "_id": user.get("_id"),
        "telegram_id": user.get("telegram_id"),
        "username": user.get("username", ""),
        "first_name": user.get("first_name", ""),
        "silent_blocked": bool(user.get("silent_blocked")),
        "silent_blocked_at": user.get("silent_blocked_at"),
        "silent_block_reason": user.get("silent_block_reason", ""),
    }


@router.get("/users")
async def list_users(search: str = Query("", max_length=120), blocked_only: bool = False):
    query = {}
    if blocked_only:
        query["silent_blocked"] = True
    term = search.strip()
    if term:
        ors = [
            {"username": {"$regex": re.escape(term.lstrip("@")), "$options": "i"}},
            {"first_name": {"$regex": re.escape(term), "$options": "i"}},
        ]
        if term.lstrip("-").isdigit():
            ors.append({"telegram_id": int(term)})
        query["$or"] = ors
    users = await db.bot_users.find(query).sort("created_at", -1).limit(300).to_list(300)
    return [_public_user(user) for user in users]


@router.get("/users/{telegram_id}")
async def user_detail(telegram_id: int):
    user = await db.bot_users.find_one({"telegram_id": telegram_id})
    if not user:
        raise HTTPException(404, "Pengguna tidak ditemukan.")
    tracked = await db.bot_chat_messages.count_documents({"chat_id": telegram_id})
    recent = await db.bot_chat_messages.find(
        {"chat_id": telegram_id}
    ).sort("message_id", -1).limit(50).to_list(50)
    return {
        **_public_user(user),
        "tracked_messages": tracked,
        "recent_message_ids": [
            {"message_id": row["message_id"], "direction": row.get("direction"), "created_at": row.get("created_at")}
            for row in recent
        ],
    }


class BlockBody(BaseModel):
    reason: str = ""
    delete_tracked_messages: bool = True
    kick_channels: bool = False


async def _delete_tracked_private_messages(chat_id: int):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    rows = await db.bot_chat_messages.find({
        "chat_id": chat_id,
        "created_at": {"$gte": cutoff},
    }).sort("message_id", 1).to_list(5000)
    ids = sorted({int(row["message_id"]) for row in rows if row.get("message_id") is not None})
    deleted = 0
    failed_batches = 0
    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        try:
            result = await tg("deleteMessages", chat_id=chat_id, message_ids=batch)
            if result.get("ok"):
                deleted += len(batch)
                await db.bot_chat_messages.delete_many({"chat_id": chat_id, "message_id": {"$in": batch}})
            else:
                failed_batches += 1
        except Exception:
            failed_batches += 1
        await asyncio.sleep(0)
    return {"tracked": len(ids), "deleted": deleted, "failed_batches": failed_batches}


@router.post("/users/{telegram_id}/silent-block")
async def silent_block(telegram_id: int, body: BlockBody):
    user = await db.bot_users.find_one({"telegram_id": telegram_id})
    if not user:
        raise HTTPException(404, "Pengguna tidak ditemukan.")
    if body.kick_channels:
        from db import get_settings
        if not ((await get_settings()).get("post_purchase_followup") or {}).get("channel_ids"):
            raise HTTPException(400, "Simpan channel tindak lanjut terlebih dahulu.")

    deletion = {"tracked": 0, "deleted": 0, "failed_batches": 0}
    if body.delete_tracked_messages:
        deletion = await _delete_tracked_private_messages(telegram_id)

    now = datetime.now(timezone.utc)
    await db.bot_users.update_one(
        {"telegram_id": telegram_id},
        {"$set": {
            "silent_blocked": True,
            "silent_blocked_at": now,
            "silent_block_reason": body.reason.strip()[:500],
            "state": None,
            "state_data": {},
        }},
    )
    channels = []
    if body.kick_channels:
        from post_purchase import kick_channels
        from db import get_settings
        settings = await get_settings()
        channels = await kick_channels(telegram_id, (settings.get("post_purchase_followup") or {}).get("channel_ids", []))
    return {"ok": True, "silent_blocked": True, "deletion": deletion, "channel_results": channels}


@router.post("/users/{telegram_id}/unblock")
async def unblock(telegram_id: int):
    result = await db.bot_users.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"silent_blocked": False}, "$unset": {
            "silent_blocked_at": "",
            "silent_block_reason": "",
        }},
    )
    if not result.matched_count:
        raise HTTPException(404, "Pengguna tidak ditemukan.")
    return {"ok": True, "silent_blocked": False}


@router.delete("/users/{telegram_id}/messages")
async def delete_messages(telegram_id: int):
    user = await db.bot_users.find_one({"telegram_id": telegram_id}, {"_id": 1})
    if not user:
        raise HTTPException(404, "Pengguna tidak ditemukan.")
    return {"ok": True, **(await _delete_tracked_private_messages(telegram_id))}
