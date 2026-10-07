"""Sales contests for reseller owners, with manual prize transfer."""
from datetime import datetime, timezone
from html import escape
import uuid

from db import db
from services import fmt_amount, now_iso, notify_admin
from tgapi import send_message

SALE_STATUSES = ["paid", "processing", "service_waiting", "delivered", "delivery_failed"]


def contest_phase(contest):
    if contest.get("status") != "active":
        return contest.get("status")
    now = now_iso()
    if now < contest["starts_at"]:
        return "scheduled"
    if now >= contest["ends_at"]:
        return "ended"
    return "running"


async def leaderboard(contest):
    rows = await db.purchases.aggregate([
        {"$match": {"reseller_bot_id": {"$exists": True},
                    "status": {"$in": SALE_STATUSES}, "currency": "IDR",
                    "paid_at": {"$gte": contest["starts_at"], "$lt": contest["ends_at"]}}},
        {"$group": {"_id": "$reseller_bot_id", "sales_idr": {"$sum": "$total"},
                    "order_count": {"$sum": 1}}},
    ]).to_list(100000)
    owners = {}
    for row in rows:
        bot = await db.reseller_bots.find_one({"_id": row["_id"]},
                                              {"owner_tid": 1, "username": 1})
        if not bot:
            continue
        tid = bot["owner_tid"]
        item = owners.setdefault(tid, {"owner_tid": tid, "sales_idr": 0,
                                       "order_count": 0, "bots": []})
        item["sales_idr"] += int(row["sales_idr"] or 0)
        item["order_count"] += int(row["order_count"] or 0)
        item["bots"].append(bot.get("username") or row["_id"])
    ranking = sorted(owners.values(), key=lambda row: (-row["sales_idr"],
                                                        -row["order_count"], row["owner_tid"]))
    for position, item in enumerate(ranking, 1):
        item["rank"] = position
        item["eligible"] = item["sales_idr"] >= contest["target_sales_idr"]
    return ranking


async def create_contest(name, starts_at, ends_at, target_sales_idr, prize_idr):
    record = {"_id": str(uuid.uuid4()), "name": name, "starts_at": starts_at,
              "ends_at": ends_at, "target_sales_idr": target_sales_idr,
              "prize_idr": prize_idr, "status": "active", "created_at": now_iso()}
    await db.reseller_contests.insert_one(record)
    return record


async def settle_contest(contest):
    if contest.get("status") not in {"active", "settling"} or contest["ends_at"] > now_iso():
        return None
    if contest["status"] == "active":
        claimed = await db.reseller_contests.find_one_and_update(
            {"_id": contest["_id"], "status": "active", "ends_at": {"$lte": now_iso()}},
            {"$set": {"status": "settling", "settling_at": now_iso()}})
        if not claimed:
            return None
    ranking = await leaderboard(contest)
    winner = next((row for row in ranking if row["eligible"]), None)
    if winner:
        payee_bot = await db.reseller_bots.find_one(
            {"owner_tid": winner["owner_tid"], "payout_destination.number": {"$exists": True}},
            {"payout_destination": 1}, sort=[("created_at", -1)])
        winner = {**winner, "payout_destination": (payee_bot or {}).get("payout_destination")}
    update = {"status": "winner_pending_transfer" if winner else "no_winner",
              "settled_at": now_iso(), "final_leaderboard": ranking,
              "winner": winner}
    saved = await db.reseller_contests.update_one({"_id": contest["_id"], "status": "settling"},
                                                   {"$set": update})
    if not saved.modified_count:
        return None
    try:
        if winner:
            destination = winner.get("payout_destination") or {}
            destination_text = (
                f"Tujuan: {escape(destination.get('provider') or '')} "
                f"<code>{escape(destination.get('number') or '')}</code> "
                f"a.n. {escape(destination.get('name') or '')}. "
                if destination else "Tujuan belum diatur owner. "
            )
            await notify_admin(
                f"🏆 <b>Kontes reseller selesai: {escape(contest['name'])}</b>\n"
                f"Pemenang owner <code>{winner['owner_tid']}</code> · "
                f"omzet {fmt_amount(winner['sales_idr'], 'IDR')}\n"
                f"Hadiah {fmt_amount(contest['prize_idr'], 'IDR')}. "
                + destination_text +
                "Transfer manual lalu tandai dibayar di Admin Panel → Bot Reseller.")
            await send_message(winner["owner_tid"],
                               f"🏆 Selamat! Kamu menang kontes reseller "
                               f"<b>{escape(contest['name'])}</b>.\n"
                               f"Omzet: {fmt_amount(winner['sales_idr'], 'IDR')}\n"
                               f"Hadiah: {fmt_amount(contest['prize_idr'], 'IDR')}\n"
                               "Admin pusat akan memproses transfer hadiah.")
        else:
            await notify_admin(f"🏁 Kontes reseller <b>{escape(contest['name'])}</b> selesai "
                               "tanpa owner yang mencapai target omzet.")
    except Exception:
        # The settled result remains available in the panel if Telegram is unavailable.
        pass
    return update


async def scan_contests():
    expired = await db.reseller_contests.find({"status": {"$in": ["active", "settling"]},
                                               "ends_at": {"$lte": now_iso()}}).to_list(1000)
    for contest in expired:
        await settle_contest(contest)
