"""Accrue reseller commission and request manual central payouts."""
import uuid
from datetime import datetime, timedelta, timezone
from html import escape

from db import db
from services import fmt_amount, now_iso, notify_admin


async def commission_balance(bot_id: str) -> dict:
    rows = await db.reseller_commissions.aggregate([
        {"$match": {"bot_id": bot_id}},
        {"$group": {"_id": "$status", "amount": {"$sum": "$amount"}}},
    ]).to_list(10)
    return {row["_id"]: int(row["amount"] or 0) for row in rows}


async def maybe_request_payout(bot: dict) -> dict | None:
    """Reserve accumulated commissions once threshold and destination exist."""
    threshold = max(50_000, int(bot.get("payout_threshold_idr") or 50_000))
    destination = bot.get("payout_destination") or {}
    if not destination.get("number") or not destination.get("provider") or not destination.get("name"):
        return None
    stale = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    claim = await db.reseller_bots.update_one(
        {"_id": bot["_id"],
         "$or": [{"payout_lock": {"$ne": True}}, {"payout_lock_at": {"$lte": stale}}]},
        {"$set": {"payout_lock": True, "payout_lock_at": now_iso()}},
    )
    if not claim.modified_count:
        return None
    try:
        commissions = await db.reseller_commissions.find({"bot_id": bot["_id"],
                                                          "status": "pending_payout"}).to_list(100000)
        amount = sum(int(row.get("amount") or 0) for row in commissions)
        if amount < threshold:
            return None
        payout_id = str(uuid.uuid4())
        ids = [row["_id"] for row in commissions]
        transfer_fee = 2500 if destination.get("type") == "EWALLET" else 0
        await db.reseller_commissions.update_many({"_id": {"$in": ids}, "status": "pending_payout"},
                                                  {"$set": {"status": "reserved", "payout_id": payout_id}})
        payout = {"_id": payout_id, "bot_id": bot["_id"], "owner_tid": bot["owner_tid"],
                  "bot_username": bot.get("username"), "amount": amount,
                  "transfer_fee": transfer_fee, "net_amount": amount - transfer_fee,
                  "commission_ids": ids,
                  "destination": destination, "status": "pending_transfer", "created_at": now_iso()}
        await db.reseller_payouts.insert_one(payout)
        return payout
    finally:
        await db.reseller_bots.update_one({"_id": bot["_id"]},
                                          {"$unset": {"payout_lock": "", "payout_lock_at": ""}})


async def remind_payout(payout: dict):
    dest = payout["destination"]
    await notify_admin(
        f"💸 <b>Komisi reseller siap ditransfer</b>\n"
        f"Bot: @{escape(payout.get('bot_username') or '')}\n"
        f"Owner ID: <code>{payout['owner_tid']}</code>\n"
        f"Komisi kotor: <b>{fmt_amount(payout['amount'], 'IDR')}</b>\n"
        f"Biaya e-wallet: {fmt_amount(payout.get('transfer_fee') or 0, 'IDR')}\n"
        f"Transfer bersih: <b>{fmt_amount(payout.get('net_amount') or payout['amount'], 'IDR')}</b>\n"
        f"Tujuan: {escape(dest.get('type') or '')} {escape(dest.get('provider') or '')}\n"
        f"Nomor: <code>{escape(dest.get('number') or '')}</code>\n"
        f"Nama: {escape(dest.get('name') or '')}\n"
        f"ID pencairan: <code>{payout['_id']}</code>\n\n"
        "Transfer manual, lalu tandai lunas di Admin Panel → Bot Reseller."
    )
    await db.reseller_payouts.update_one({"_id": payout["_id"]},
                                         {"$set": {"reminder_sent_at": now_iso()}})


async def reconcile_payouts():
    """Repair payout records if a process stopped between MongoDB updates."""
    reserved = await db.reseller_commissions.find({"status": "reserved", "payout_id": {"$exists": True}}).to_list(100000)
    groups = {}
    for row in reserved:
        groups.setdefault(row["payout_id"], []).append(row)
    for payout_id, rows in groups.items():
        if await db.reseller_payouts.find_one({"_id": payout_id}):
            continue
        bot = await db.reseller_bots.find_one({"_id": rows[0]["bot_id"]})
        if not bot:
            continue
        destination = bot.get("payout_destination") or {}
        amount = sum(int(row.get("amount") or 0) for row in rows)
        fee = 2500 if destination.get("type") == "EWALLET" else 0
        await db.reseller_payouts.update_one({"_id": payout_id}, {"$setOnInsert": {
            "bot_id": bot["_id"], "owner_tid": bot["owner_tid"],
            "bot_username": bot.get("username"), "amount": amount,
            "transfer_fee": fee, "net_amount": amount - fee,
            "commission_ids": [row["_id"] for row in rows], "destination": destination,
            "status": "pending_transfer", "created_at": now_iso(),
        }}, upsert=True)
    settled = await db.reseller_payouts.find({"status": {"$in": ["paid", "cancelled"]}}).to_list(100000)
    for payout in settled:
        if payout["status"] == "paid":
            await db.reseller_commissions.update_many({"payout_id": payout["_id"], "status": "reserved"},
                                                      {"$set": {"status": "paid", "paid_at": payout.get("paid_at")}})
        else:
            await db.reseller_commissions.update_many({"payout_id": payout["_id"], "status": "reserved"},
                                                      {"$set": {"status": "pending_payout"},
                                                       "$unset": {"payout_id": ""}})
