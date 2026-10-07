"""Daily sales recap delivery at a configured Jakarta time."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from auth import get_current_admin
from broadcast_composer import ComposeBody, configured_chats, send
from db import db, get_settings
from services import now_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/broadcasts/daily-recap", dependencies=[Depends(get_current_admin)])
JAKARTA = ZoneInfo("Asia/Jakarta")


class RecapConfig(BaseModel):
    enabled: bool = False
    time: str = Field(default="00:05", pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    target: Literal["chats", "users", "both"] = "chats"


@router.get("/config")
async def get_config():
    settings = await get_settings()
    return {"enabled": settings.get("daily_recap_enabled", False),
            "time": settings.get("daily_recap_time", "00:05"),
            "target": settings.get("daily_recap_target", "chats")}


@router.put("/config")
async def set_config(body: RecapConfig):
    await db.settings.update_one({"_id": "main"}, {"$set": {
        "daily_recap_enabled": body.enabled, "daily_recap_time": body.time,
        "daily_recap_target": body.target,
    }})
    return body.model_dump()


async def send_due_recap(now=None):
    now = now or datetime.now(JAKARTA)
    settings = await get_settings()
    if not settings.get("daily_recap_enabled", False):
        return False
    scheduled = str(settings.get("daily_recap_time") or "00:05")
    hour, minute = (int(value) for value in scheduled.split(":"))
    schedule_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Allow a short retry window after downtime without sending an old recap at startup.
    if not schedule_at <= now < schedule_at + timedelta(hours=1):
        return False
    target = settings.get("daily_recap_target") or "chats"
    if target in {"chats", "both"} and not await configured_chats("daily_recap"):
        return False
    day = (now.date() - timedelta(days=1)).isoformat()
    marker = {"_id": day, "status": "sending", "created_at": now_iso(), "target": target}
    try:
        await db.daily_recaps.insert_one(marker)
    except DuplicateKeyError:
        return False
    try:
        result = await send(ComposeBody(kind="daily_recap", day=day, target=target, image_mode="auto"))
        chat_failed = any(not row.get("ok") for row in result.get("chat_results", []))
        await db.daily_recaps.update_one({"_id": day}, {"$set": {
            "status": "partial" if chat_failed else "queued" if result.get("queued_users") else "sent",
            "broadcast_id": result["id"], "finished_at": now_iso(),
        }})
        return True
    except Exception:
        await db.daily_recaps.delete_one({"_id": day})
        raise


async def run_daily_recap(stop: asyncio.Event):
    while not stop.is_set():
        try:
            await send_due_recap()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily recap failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
