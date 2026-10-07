"""Admin controls and webhook entry point for reseller bots."""
import asyncio
import hmac
from datetime import datetime, timezone
from html import escape

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from auth import get_current_admin
from db import db, get_settings
from reseller_service import activation_fees, configure_webhook
from reseller_contest import (contest_phase, create_contest, leaderboard,
                              settle_contest)
from services import now_iso

admin_router = APIRouter(prefix="/api/admin/resellers", dependencies=[Depends(get_current_admin)])
webhook_router = APIRouter(prefix="/api/telegram/reseller")


class ResellerSettings(BaseModel):
    enabled: bool = False
    bot_price_idr: int = Field(ge=0, le=100_000_000)
    admin_fee_idr: int = Field(ge=0, le=100_000_000)
    platform_fee_idr: int = Field(ge=0, le=100_000_000)
    wholesale_reduction_idr: int = Field(ge=0, le=100_000_000)


class PayoutDecision(BaseModel):
    transfer_reference: str = Field(default="", max_length=120)


class BlockInput(BaseModel):
    reason: str = Field(default="Pemeriksaan admin", max_length=300)


class ContestInput(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    starts_at: datetime
    ends_at: datetime
    target_sales_idr: int = Field(gt=0, le=100_000_000_000)
    prize_idr: int = Field(gt=0, le=100_000_000_000)


def contest_dates(body: ContestInput):
    if body.starts_at.tzinfo is None or body.ends_at.tzinfo is None:
        raise HTTPException(400, "Tanggal kontes harus memuat zona waktu.")
    start = body.starts_at.astimezone(timezone.utc)
    end = body.ends_at.astimezone(timezone.utc)
    if end <= start:
        raise HTTPException(400, "Waktu selesai harus setelah waktu mulai.")
    return start.isoformat(), end.isoformat()


@admin_router.get("/settings")
async def reseller_settings():
    s = await get_settings()
    return {"enabled": s.get("reseller_enabled", False),
            "bot_price_idr": s.get("reseller_bot_price_idr", 0),
            "admin_fee_idr": s.get("reseller_admin_fee_idr", 0),
            "platform_fee_idr": s.get("reseller_platform_fee_idr", 0),
            "wholesale_reduction_idr": s.get("reseller_wholesale_reduction_idr", 2000)}


@admin_router.put("/settings")
async def save_reseller_settings(body: ResellerSettings):
    if body.enabled and body.bot_price_idr + body.admin_fee_idr + body.platform_fee_idr <= 0:
        raise HTTPException(400, "Isi biaya langganan bulanan sebelum membuka pendaftaran.")
    data = {"reseller_enabled": body.enabled,
            "reseller_bot_price_idr": body.bot_price_idr,
            "reseller_admin_fee_idr": body.admin_fee_idr,
            "reseller_platform_fee_idr": body.platform_fee_idr,
            "reseller_wholesale_reduction_idr": body.wholesale_reduction_idr}
    await db.settings.update_one({"_id": "main"}, {"$set": data})
    return await reseller_settings()


async def bot_summary(bot: dict) -> dict:
    count = await db.reseller_bot_users.count_documents({"bot_id": bot["_id"]})
    orders = await db.purchases.count_documents({"reseller_bot_id": bot["_id"], "status": "delivered"})
    pipeline = [{"$match": {"reseller_bot_id": bot["_id"], "status": "delivered"}},
                {"$group": {"_id": None, "sales": {"$sum": "$total"}, "profit": {"$sum": "$reseller_margin"}}}]
    amounts = await db.purchases.aggregate(pipeline).to_list(1)
    latest_sale = await db.purchases.find_one(
        {"reseller_bot_id": bot["_id"],
         "status": {"$in": ["paid", "processing", "service_waiting", "delivered", "delivery_failed"]}},
        {"created_at": 1}, sort=[("created_at", -1)])
    return {"_id": bot["_id"], "username": bot.get("username"), "name": bot.get("name"),
            "owner_tid": bot.get("owner_tid"), "admin_tid": bot.get("admin_tid"),
            "status": bot.get("status"), "created_at": bot.get("created_at"),
            "activated_at": bot.get("activated_at"), "expires_at": bot.get("expires_at"),
            "last_cycle_paid_at": bot.get("last_cycle_paid_at"),
            "last_sale_at": (latest_sale or {}).get("created_at"),
            "inactivated_at": bot.get("inactivated_at"),
            "inactivation_reason": bot.get("inactivation_reason"),
            "blocked_reason": bot.get("blocked_reason"),
            "renewal_pending": bool(bot.get("renewal_pending")), "fees": bot.get("fees"),
            "user_count": count, "completed_orders": orders,
            "sales_idr": (amounts[0]["sales"] if amounts else 0),
            "profit_idr": (amounts[0]["profit"] if amounts else 0),
            "price_count": len(bot.get("markups") or {}),
            "default_markup_idr": bot.get("default_markup_idr", 0)}


@admin_router.get("")
async def list_resellers():
    bots = await db.reseller_bots.find({}, {"token_encrypted": 0, "webhook_secret": 0}).sort("created_at", -1).to_list(500)
    return [await bot_summary(bot) for bot in bots]


@admin_router.get("/payouts")
async def list_payouts():
    return await db.reseller_payouts.find().sort("created_at", -1).limit(200).to_list(200)


@admin_router.get("/contests")
async def list_contests():
    contests = await db.reseller_contests.find().sort("created_at", -1).limit(100).to_list(100)
    return [{**contest, "phase": contest_phase(contest)} for contest in contests]


@admin_router.post("/contests")
async def add_contest(body: ContestInput):
    start, end = contest_dates(body)
    if end <= now_iso():
        raise HTTPException(400, "Waktu selesai harus di masa depan.")
    return await create_contest(body.name.strip(), start, end,
                                body.target_sales_idr, body.prize_idr)


@admin_router.get("/contests/{contest_id}")
async def contest_detail(contest_id: str):
    contest = await db.reseller_contests.find_one({"_id": contest_id})
    if not contest:
        raise HTTPException(404, "Kontes tidak ditemukan.")
    return {**contest, "phase": contest_phase(contest),
            "leaderboard": contest.get("final_leaderboard") if contest.get("status") != "active"
            else await leaderboard(contest)}


@admin_router.post("/contests/{contest_id}/settle")
async def close_contest(contest_id: str):
    contest = await db.reseller_contests.find_one({"_id": contest_id})
    if not contest:
        raise HTTPException(404, "Kontes tidak ditemukan.")
    if contest.get("status") != "active" or contest["ends_at"] > now_iso():
        raise HTTPException(400, "Kontes belum selesai atau sudah diproses.")
    return {"ok": bool(await settle_contest(contest))}


@admin_router.post("/contests/{contest_id}/paid")
async def mark_contest_prize_paid(contest_id: str, body: PayoutDecision):
    contest = await db.reseller_contests.find_one_and_update(
        {"_id": contest_id, "status": "winner_pending_transfer"},
        {"$set": {"status": "prize_paid", "prize_paid_at": now_iso(),
                  "transfer_reference": body.transfer_reference.strip()}})
    if not contest:
        raise HTTPException(400, "Hadiah tidak ditemukan atau sudah dibayar.")
    try:
        from tgapi import send_message
        await send_message(contest["winner"]["owner_tid"],
                           f"🎁 Hadiah kontes <b>{escape(contest['name'])}</b> sebesar "
                           f"{contest['prize_idr']:,.0f} IDR sudah ditransfer oleh admin pusat.")
    except Exception:
        pass
    return {"ok": True}


@admin_router.post("/payouts/{payout_id}/paid")
async def mark_payout_paid(payout_id: str, body: PayoutDecision):
    payout = await db.reseller_payouts.find_one_and_update(
        {"_id": payout_id, "status": "pending_transfer"},
        {"$set": {"status": "paid", "paid_at": now_iso(),
                  "transfer_reference": body.transfer_reference.strip()}},
    )
    if not payout:
        raise HTTPException(400, "Pencairan tidak ditemukan atau sudah diproses.")
    await db.reseller_commissions.update_many({"payout_id": payout_id, "status": "reserved"},
                                              {"$set": {"status": "paid", "paid_at": now_iso()}})
    bot = await db.reseller_bots.find_one({"_id": payout["bot_id"]})
    if bot:
        try:
            from reseller_bot import send
            await send(bot, bot["admin_tid"],
                       f"✅ Komisi {payout.get('net_amount') or payout['amount']:,.0f} IDR telah ditransfer oleh admin pusat.\n"
                       f"Referensi: <code>{body.transfer_reference.strip() or '-'}</code>")
        except Exception:
            pass
    return {"ok": True}


@admin_router.post("/payouts/{payout_id}/cancel")
async def cancel_payout(payout_id: str):
    payout = await db.reseller_payouts.find_one_and_update(
        {"_id": payout_id, "status": "pending_transfer"},
        {"$set": {"status": "cancelled", "cancelled_at": now_iso()}},
    )
    if not payout:
        raise HTTPException(400, "Pencairan tidak ditemukan atau sudah diproses.")
    await db.reseller_commissions.update_many({"payout_id": payout_id, "status": "reserved"},
                                              {"$set": {"status": "pending_payout"},
                                               "$unset": {"payout_id": ""}})
    return {"ok": True}


@admin_router.get("/{bot_id}")
async def reseller_detail(bot_id: str):
    bot = await db.reseller_bots.find_one({"_id": bot_id}, {"token_encrypted": 0, "webhook_secret": 0})
    if not bot:
        raise HTTPException(404, "Bot reseller tidak ditemukan.")
    summary = await bot_summary(bot)
    summary["markups"] = bot.get("markups") or {}
    summary["recent_users"] = await db.reseller_bot_users.find({"bot_id": bot_id}).sort("created_at", -1).limit(20).to_list(20)
    summary["recent_orders"] = await db.purchases.find({"reseller_bot_id": bot_id},
                                                       {"_id": 1, "invoice_id": 1, "user_tid": 1,
                                                        "total": 1, "status": 1, "created_at": 1,
                                                        "reseller_margin": 1}).sort("created_at", -1).limit(20).to_list(20)
    summary["payments"] = await db.reseller_payments.find({"bot_id": bot_id}).sort("created_at", -1).limit(12).to_list(12)
    summary["payouts"] = await db.reseller_payouts.find({"bot_id": bot_id}).sort("created_at", -1).limit(20).to_list(20)
    summary["commission_balance"] = await __import__("reseller_payout").commission_balance(bot_id)
    return jsonable_encoder(summary, custom_encoder={ObjectId: str})


@admin_router.post("/{bot_id}/orders/{order_id}/complete")
async def complete_reseller_service(bot_id: str, order_id: str):
    order = await db.purchases.find_one_and_update(
        {"_id": order_id, "reseller_bot_id": bot_id, "status": "service_waiting"},
        {"$set": {"status": "delivered", "delivered_at": now_iso()}},
    )
    if not order:
        raise HTTPException(400, "Pesanan jasa tidak ditemukan atau sudah selesai.")
    bot = await db.reseller_bots.find_one({"_id": bot_id})
    if bot:
        from reseller_bot import record_commission, send
        await record_commission(bot, order)
        await send(bot, order["user_tid"], f"✅ Pesanan jasa <code>{order['invoice_id']}</code> selesai.")
    return {"ok": True}


@admin_router.post("/{bot_id}/pause")
async def pause_reseller(bot_id: str):
    result = await db.reseller_bots.update_one({"_id": bot_id, "status": "active"},
                                               {"$set": {"status": "paused", "updated_at": now_iso()}})
    if not result.modified_count:
        raise HTTPException(400, "Hanya bot aktif yang bisa dijeda.")
    return {"ok": True}


@admin_router.post("/{bot_id}/block")
async def block_reseller(bot_id: str, body: BlockInput):
    bot = await db.reseller_bots.find_one_and_update(
        {"_id": bot_id, "status": {"$in": ["active", "paused", "expired",
                                            "inactive_no_sales", "pending_payment"]}},
        {"$set": {"status": "blocked", "blocked_reason": body.reason.strip() or "Pemeriksaan admin",
                  "blocked_at": now_iso(), "updated_at": now_iso()}})
    if not bot:
        raise HTTPException(400, "Bot tidak ditemukan atau sudah diblokir.")
    try:
        from tgapi import send_message
        await send_message(bot["owner_tid"],
                           f"⛔ Bot reseller @{escape(bot.get('username') or '')} dinonaktifkan oleh admin pusat. "
                           "Hubungi admin pusat jika membutuhkan penjelasan.")
    except Exception:
        pass
    return {"ok": True}


@admin_router.post("/{bot_id}/unblock")
async def unblock_reseller(bot_id: str):
    bot = await db.reseller_bots.find_one({"_id": bot_id, "status": "blocked"})
    if not bot:
        raise HTTPException(400, "Bot tidak sedang diblokir.")
    if bot.get("expires_at") and bot["expires_at"] > now_iso():
        status = "active"
        try:
            await configure_webhook(bot)
        except Exception as exc:
            raise HTTPException(502, f"Webhook Telegram gagal: {exc}") from exc
    elif bot.get("activated_at"):
        status = "expired"
    else:
        status = "pending_payment"
    await db.reseller_bots.update_one({"_id": bot_id, "status": "blocked"},
                                      {"$set": {"status": status, "updated_at": now_iso()},
                                       "$unset": {"blocked_reason": "", "blocked_at": ""}})
    return {"ok": True, "status": status}


@admin_router.post("/{bot_id}/resume")
async def resume_reseller(bot_id: str):
    bot = await db.reseller_bots.find_one({"_id": bot_id, "status": "paused"})
    if not bot or not bot.get("expires_at") or bot["expires_at"] <= now_iso():
        raise HTTPException(400, "Langganan bot tidak aktif atau sudah kedaluwarsa.")
    try:
        await configure_webhook(bot)
    except Exception as exc:
        raise HTTPException(502, f"Webhook Telegram gagal: {exc}") from exc
    await db.reseller_bots.update_one({"_id": bot_id, "status": "paused"},
                                      {"$set": {"status": "active", "updated_at": now_iso()}})
    return {"ok": True}


@webhook_router.post("/{bot_id}/webhook")
async def reseller_webhook(bot_id: str, request: Request):
    bot = await db.reseller_bots.find_one({"_id": bot_id})
    received = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not bot or not received or not hmac.compare_digest(received, bot.get("webhook_secret") or ""):
        raise HTTPException(403, "Invalid webhook token")
    update = await request.json()
    update_id = update.get("update_id")
    if update_id is not None:
        try:
            await db.reseller_updates.insert_one({"bot_id": bot_id, "update_id": update_id,
                                                   "created_at": now_iso()})
        except Exception:
            return {"ok": True, "duplicate": True}
    from reseller_bot import process_reseller_update
    asyncio.create_task(process_reseller_update(bot, update))
    return {"ok": True}
