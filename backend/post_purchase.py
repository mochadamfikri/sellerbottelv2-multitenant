"""Opt-in follow-up for newly completed purchases, with explicit exemptions."""
import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError
from auth import get_current_admin
from db import db, get_settings
from product_catalog import catalog_name
from tgapi import tg

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/bot-moderation/followup", dependencies=[Depends(get_current_admin)])


class FollowupConfig(BaseModel):
    mode: Literal["none", "kick_block"] = "none"
    channel_ids: list[str] = Field(default_factory=list, max_length=20)
    exempt_user_ids: list[int] = Field(default_factory=list, max_length=1000)
    exempt_catalogs: list[str] = Field(default_factory=list, max_length=500)
    exempt_product_ids: list[str] = Field(default_factory=list, max_length=5000)
    exempt_resellers: bool = True


@router.get("/config")
async def get_config():
    return FollowupConfig(**((await get_settings()).get("post_purchase_followup") or {})).model_dump()


@router.put("/config")
async def set_config(body: FollowupConfig):
    channels = list(dict.fromkeys(value.strip() for value in body.channel_ids if value.strip()))
    if any(not re.fullmatch(r"(?:-\d+|@[A-Za-z0-9_]{5,32})", value) for value in channels):
        raise HTTPException(400, "Gunakan ID channel -100… atau @username, satu per baris.")
    if body.mode == "kick_block" and not channels:
        raise HTTPException(400, "Tentukan channel yang akan digunakan untuk auto kick.")
    old = (await get_settings()).get("post_purchase_followup") or {}
    data = {**body.model_dump(), "channel_ids": channels}
    data["enabled_since"] = (old.get("enabled_since") if old.get("mode") == "kick_block" else None) or datetime.now(timezone.utc).isoformat()
    await db.settings.update_one({"_id": "main"}, {"$set": {"post_purchase_followup": data}}, upsert=True)
    return body.model_dump() | {"channel_ids": channels}


@router.get("/history")
async def history():
    return await db.post_purchase_actions.find({}).sort("created_at", -1).limit(100).to_list(100)


async def kick_channels(telegram_id, channels):
    results = []
    for channel in channels:
        try:
            member = await tg("getChatMember", chat_id=channel, user_id=telegram_id)
            status = (member.get("result") or {}).get("status")
            if not member.get("ok"):
                result = member
            elif status in {"creator", "administrator"}:
                result = {"ok": False, "description": "Pengguna adalah admin channel; tidak dikeluarkan."}
            elif status in {"left", "kicked"}:
                result = {"ok": True}
            else:
                # Telegram unbanChatMember removes current members without a permanent ban.
                result = await tg("unbanChatMember", chat_id=channel, user_id=telegram_id, only_if_banned=False)
            results.append({"channel": channel, "ok": bool(result.get("ok")), "error": result.get("description") if not result.get("ok") else None})
        except Exception as exc:
            results.append({"channel": channel, "ok": False, "error": type(exc).__name__})
    return results


async def exemption(order, config, settings):
    tid = order.get("user_tid")
    if not tid or int(tid) <= 0:
        return "Akun tanpa Telegram"
    if str(tid) == str(settings.get("admin_telegram_id")):
        return "Admin"
    if int(tid) in config.get("exempt_user_ids", []):
        return "Pengecualian pengguna"
    if config.get("exempt_resellers", True) and (order.get("reseller_bot_id") or await db.reseller_bots.find_one({"owner_tid": int(tid)})):
        return "Pengecualian reseller"
    excluded = {str(value) for value in config.get("exempt_product_ids", [])}
    catalogs = {value.strip().lower() for value in config.get("exempt_catalogs", [])}
    for item in order.get("items") or []:
        pid = item.get("product_id") or item.get("pid")
        if str(pid) in excluded:
            return "Pengecualian produk"
        product = await db.products.find_one({"_id": pid})
        if product and catalog_name(product).lower() in catalogs:
            return "Pengecualian katalog"
    return None


async def process_completed(order, settings):
    config = settings.get("post_purchase_followup") or {}
    if config.get("mode") != "kick_block" or order.get("status") not in {"delivered", "completed"}:
        return
    if not config.get("enabled_since") or str(order.get("delivered_at") or "") < config["enabled_since"]:
        return
    if await db.post_purchase_actions.find_one({"_id": order["_id"]}):
        return
    reason = await exemption(order, config, settings)
    tid = order.get("user_tid")
    if not reason and await db.purchases.find_one({"user_tid": tid, "status": {"$in": ["pending_payment", "paid", "processing", "service_waiting"]}}):
        return  # Wait until other purchases are delivered as well.
    now = datetime.now(timezone.utc)
    marker = {"_id": order["_id"], "invoice_id": order.get("invoice_id"), "telegram_id": tid,
              "created_at": now.isoformat(), "status": "skipped" if reason else "processing", "reason": reason}
    try:
        await db.post_purchase_actions.insert_one(marker)
    except DuplicateKeyError:
        return
    if reason:
        return
    try:
        results = await kick_channels(int(tid), config.get("channel_ids", []))
        await db.bot_users.update_one({"telegram_id": int(tid)}, {"$set": {
            "silent_blocked": True, "silent_blocked_at": now,
            "silent_block_reason": f"Otomatis setelah pesanan {order.get('invoice_id') or order['_id']} selesai.",
            "state": None, "state_data": {},
        }})
        await db.post_purchase_actions.update_one({"_id": order["_id"]}, {"$set": {
            "status": "completed" if results and all(row["ok"] for row in results) else "partial",
            "channel_results": results, "bot_blocked": True, "finished_at": datetime.now(timezone.utc).isoformat(),
        }})
    except Exception as exc:
        await db.post_purchase_actions.update_one({"_id": order["_id"]}, {"$set": {"status": "failed", "reason": type(exc).__name__}})
        logger.exception("Post purchase followup failed for %s", order["_id"])


async def run_followup(stop):
    while not stop.is_set():
        try:
            settings = await get_settings()
            config = settings.get("post_purchase_followup") or {}
            if config.get("mode") == "kick_block" and config.get("enabled_since"):
                cutoff = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
                async for order in db.purchases.find({"status": {"$in": ["delivered", "completed"]},
                    "delivered_at": {"$gte": config["enabled_since"], "$lte": cutoff}}):
                    await process_completed(order, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Post purchase worker failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
