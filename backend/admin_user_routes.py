from fastapi import APIRouter, Depends, Query, Response
from typing import Literal
import re

from auth import get_current_admin
from db import db, get_settings
from promo_telegram import decrypt_session, _api
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import UserAlreadyParticipantError

router = APIRouter(prefix="/api/admin", dependencies=[Depends(get_current_admin)])


@router.get("/user-directory")
async def user_directory(response: Response, search: str = Query(default="", max_length=120),
                         source: Literal["all", "telegram", "web", "linked"] = "all",
                         page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100)):
    """Read-only unified view; linked accounts and their orders are counted once."""
    response.headers["Cache-Control"] = "no-store, private"
    fields = {key: 1 for key in ("telegram_id", "first_name", "last_name", "username", "created_at", "balance_idr", "balance_usd", "currency", "frozen", "silent_blocked", "blocked")}
    telegram = await db.bot_users.find({}, fields).to_list(None)
    customers = await db.store_customers.find({}, {key: 1 for key in ("email", "display_name", "telegram_id", "created_at", "verified_at", "balance_idr", "balance_usd", "account_disabled")}).to_list(None)
    connected = {row["tg_user_id"] for row in await db.tg_accounts.find(
        {"status": "active", "session_encrypted": {"$type": "string"}}, {"tg_user_id": 1}).to_list(None)}
    rows = {str(user["telegram_id"]): {**user, "source": "telegram", "web_account": False,
            "telegram_linked": False, "telegram_account_connected": user["telegram_id"] in connected} for user in telegram}
    for customer in customers:
        tid = customer.get("telegram_id")
        key = str(tid) if tid else "store:" + str(customer["_id"])
        bot = rows.get(key, {})
        rows[key] = {**bot, "_id": bot.get("_id") or "store:" + str(customer["_id"]),
            "customer_id": customer["_id"], "source": "linked" if tid else "web",
            "telegram_id": tid, "email": customer.get("email"), "email_verified": bool(customer.get("verified_at")),
            "first_name": customer.get("display_name") or bot.get("first_name") or customer.get("email"),
            "created_at": bot.get("created_at") or customer.get("created_at"), "web_created_at": customer.get("created_at"),
            "balance_idr": bot.get("balance_idr", customer.get("balance_idr", 0)),
            "balance_usd": bot.get("balance_usd", customer.get("balance_usd", 0)),
            "frozen": bot.get("frozen", customer.get("account_disabled", False)),
            "telegram_linked": bool(tid), "web_account": True,
            "telegram_account_connected": tid in connected if tid else False}
    groups = await db.purchases.aggregate([{"$group": {
        "_id": {"customer_id": "$customer_id", "user_tid": "$user_tid"}, "count": {"$sum": 1},
    }}]).to_list(None)
    for row in rows.values():
        row["wallet_target"] = "store:" + str(row["customer_id"]) if row.get("customer_id") else "bot:" + str(row["_id"])
        row["purchase_count"] = sum(group["count"] for group in groups if
            (row.get("customer_id") and (group["_id"] or {}).get("customer_id") == row["customer_id"]) or
            (row.get("telegram_id") and (group["_id"] or {}).get("user_tid") == row["telegram_id"]))
    term = search.strip().lstrip("@").casefold()
    found = [row for row in rows.values() if not term or any(term in str(row.get(key) or "").casefold()
             for key in ("first_name", "last_name", "username", "email", "telegram_id", "_id", "customer_id", "wallet_target"))]
    counts = {key: sum(row["source"] == key for row in found) for key in ("telegram", "web", "linked")}
    counts["all"] = len(found)
    filtered = [row for row in found if source == "all" or row["source"] == source]
    filtered.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    total = len(filtered)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    return {"items": filtered[(page - 1) * page_size:page * page_size], "total": total,
            "page": page, "pages": pages, "page_size": page_size, "source_counts": counts}


@router.get("/store-customers")
async def list_store_customers(search: str = ""):
    query = {}
    term = search.strip()[:120]
    if term:
        username_term = term[1:] if term.startswith("@") else term
        bot_clauses = [
            {"username": {"$regex": re.escape(username_term), "$options": "i"}},
            {"first_name": {"$regex": re.escape(term), "$options": "i"}},
            {"last_name": {"$regex": re.escape(term), "$options": "i"}},
        ]
        if term.isdigit():
            bot_clauses.append({"telegram_id": int(term)})
        matching_tids = [
            row["telegram_id"]
            for row in await db.bot_users.find({"$or": bot_clauses}, {"telegram_id": 1}).limit(500).to_list(500)
        ]
        customer_clauses = [{"email": {"$regex": re.escape(term), "$options": "i"}}]
        if matching_tids:
            customer_clauses.append({"telegram_id": {"$in": matching_tids}})
        if term.isdigit():
            customer_clauses.append({"telegram_id": int(term)})
        query["$or"] = customer_clauses
    customers = await db.store_customers.find(query, {"password_hash": 0}).sort("created_at", -1).limit(500).to_list(500)
    result = []
    for customer in customers:
        tid = customer.get("telegram_id")
        bot_user = await db.bot_users.find_one({"telegram_id": tid}) if tid else None
        result.append({
            "_id": "store:" + customer["_id"],
            "user_type": "store_customer",
            "email": customer.get("email"),
            "telegram_id": tid,
            "first_name": (bot_user or {}).get("first_name"),
            "username": (bot_user or {}).get("username"),
            "balance_usd": (bot_user or {}).get("balance_usd", customer.get("balance_usd", 0)),
            "balance_idr": (bot_user or {}).get("balance_idr", customer.get("balance_idr", 0)),
            "currency": (bot_user or {}).get("currency", "IDR"),
            "frozen": (bot_user or {}).get("frozen", customer.get("account_disabled", False)),
            "purchase_count": (await db.purchases.count_documents({"customer_id": customer["_id"]}) +
                               (await db.purchases.count_documents({"user_tid": tid}) if tid else 0)),
            "telegram_linked": bool(tid),
            "email_verified": bool(customer.get("verified_at")),
            "created_at": customer.get("created_at"),
        })
    return result


@router.get("/users/all")
async def list_all_users():
    purchase_counts = {
        row["_id"]: row["n"]
        for row in await db.purchases.aggregate([
            {"$group": {"_id": "$user_tid", "n": {"$sum": 1}}}
        ]).to_list(10000)
    }

    users = []
    async for user in db.bot_users.find({}).sort("created_at", -1):
        user.pop("state", None)
        user.pop("state_data", None)
        user["purchase_count"] = purchase_counts.get(user.get("telegram_id"), 0)
        user["telegram_account_connected"] = bool(await db.tg_accounts.find_one({
            "tg_user_id": user.get("telegram_id"),
            "status": "active",
            "session_encrypted": {"$type": "string"},
        }))
        users.append(user)

    return users


@router.post("/users/{tid}/join-group")
async def join_group_for_user(tid: int):
    account = await db.tg_accounts.find_one({
        "tg_user_id": tid,
        "status": "active",
        "session_encrypted": {"$type": "string"},
    })
    if not account:
        return {"ok": False, "message": "Tidak ada akun Telegram terhubung yang aktif untuk pengguna ini."}

    settings = await get_settings()
    target = str(settings.get("join_group_target") or "").strip()
    if not target:
        return {"ok": False, "message": "Target group belum dikonfigurasi di Pengaturan."}

    api_id, api_hash = _api()
    client = TelegramClient(StringSession(decrypt_session(account["session_encrypted"])), api_id, api_hash)
    await client.connect()
    try:
        if target.startswith("https://t.me/+") or target.startswith("https://t.me/joinchat/"):
            invite_hash = target.split("/")[-1].replace("+", "")
            try:
                await client(ImportChatInviteRequest(invite_hash))
            except UserAlreadyParticipantError:
                pass
        else:
            entity = await client.get_entity(target)
            try:
                await client(JoinChannelRequest(entity))
            except UserAlreadyParticipantError:
                pass
        return {"ok": True, "message": "Akun Telegram berhasil diproses untuk join group.", "target": target}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    finally:
        await client.disconnect()
