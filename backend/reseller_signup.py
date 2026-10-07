"""Reseller signup and monthly subscription flow in the central bot."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from html import escape

from db import db, get_settings
from gopay_provider import create_gopay_payment
from reseller_service import (activate_paid_bot, begin_renewal, create_draft,
                              fee_text, finalize_draft)
from services import fmt_amount, now_iso, notify_admin
from tgapi import delete_message, send_message, send_photo_bytes

logger = logging.getLogger(__name__)


def payment_keyboard(bot_id):
    return {"inline_keyboard": [
        [{"text": "💰 Bayar dari saldo IDR", "callback_data": f"reseller:pay:{bot_id}"}],
        [{"text": "📱 Bayar via QRIS SellerBottel", "callback_data": f"reseller:qris:{bot_id}"}],
        [{"text": "➕ Deposit saldo", "callback_data": "menu:deposit"}],
    ]}


async def show_entry(tid, user):
    settings = await get_settings()
    # Platform-level per-bot flag wins when a tenant scope is installed;
    # legacy single-bot mode falls back to the tenant DB setting.
    try:
        from bot_tenant_scope import get_current_scope
        scope = get_current_scope()
        enabled = (scope.reseller_enabled if scope is not None
                   else settings.get("reseller_enabled"))
    except Exception:
        enabled = settings.get("reseller_enabled")
    if not enabled:
        await send_message(tid, "🤖 Pendaftaran bot reseller belum dibuka. Silakan cek lagi nanti.")
        return
    from reseller_service import activation_fees
    fees = activation_fees(settings)
    await send_message(tid,
                       "🤖 <b>Bikin Bot Sendiri</b>\n\n"
                       "Bot reseller memakai katalog dan stok SellerBottel pusat. Kamu mengatur markup dari file .txt.\n"
                       f"Langganan bulanan: <b>{fmt_amount(fees['total'], 'IDR')}</b>\n\n"
                       "⚠️ Bot tanpa penjualan berbayar selama 14 hari akan dinonaktifkan. "
                       "Biaya langganan yang sudah dibayar tidak dikembalikan.\n\n"
                       "Buat bot melalui @BotFather, lalu siapkan token bot dan Telegram User ID adminnya.\n"
                       "⚠️ Token adalah akses penuh ke botmu. Hapus pesan token setelah diproses.",
                       {"inline_keyboard": [[{"text": "➕ Daftarkan Bot", "callback_data": "reseller:new"}],
                                            [{"text": "📋 Bot Saya", "callback_data": "reseller:mine"}]]})


async def start_registration(tid):
    from bot import set_state
    if not (await get_settings()).get("reseller_enabled"):
        await send_message(tid, "Pendaftaran bot reseller belum dibuka oleh admin pusat.")
        return
    await set_state(tid, "reseller_token")
    await send_message(tid, "Kirim <b>token bot</b> dari @BotFather. Pesan token akan saya hapus setelah diperiksa.\n"
                       "Ketik /batal untuk membatalkan.")


async def receive_token(tid, message):
    from bot import set_state
    token = (message.get("text") or "").strip()
    try:
        bot = await create_draft(tid, token)
    except ValueError as exc:
        await send_message(tid, f"⚠️ {escape(str(exc))} Coba kirim token bot yang benar.")
        return
    finally:
        if message.get("message_id"):
            try:
                await delete_message(tid, message["message_id"])
            except Exception:
                pass
    await set_state(tid, "reseller_admin", {"bot_id": bot["_id"]})
    await send_message(tid, f"✅ Bot @{escape(bot['username'])} terverifikasi.\n"
                       "Sekarang kirim <b>Telegram User ID</b> orang yang menjadi admin bot reseller. "
                       "Boleh ID milikmu sendiri.")


async def receive_admin(tid, user, text):
    from bot import set_state
    try:
        admin_tid = int(text.strip())
    except ValueError:
        admin_tid = 0
    if admin_tid <= 0:
        await send_message(tid, "User ID harus angka positif. Kirim ID Telegram admin bot.")
        return
    bot_id = (user.get("state_data") or {}).get("bot_id")
    bot = await db.reseller_bots.find_one({"_id": bot_id, "owner_tid": tid, "status": "draft"})
    if not bot:
        await set_state(tid)
        await send_message(tid, "Pendaftaran bot tidak ditemukan. Mulai kembali dari menu Bikin Bot Sendiri.")
        return
    try:
        bot = await finalize_draft(bot, admin_tid)
    except ValueError as exc:
        await send_message(tid, f"⚠️ {escape(str(exc))}")
        return
    await set_state(tid)
    result = await send_message(tid, fee_text(bot), payment_keyboard(bot["_id"]))
    if not result.get("ok"):
        logger.error("Reseller quote delivery failed for bot %s: %s", bot["_id"], result.get("description"))
    await send_subscription_qris(tid, user, bot)


async def send_subscription_qris(tid, user, bot):
    settings = await get_settings()
    if not settings.get("qris_enabled") or os.environ.get("GOPAY_ENABLED", "").lower() not in {"1", "true", "yes"}:
        await send_message(tid, "🏦 QRIS belum tersedia. Bayar dari saldo IDR atau deposit melalui rekening SellerBottel.",
                           payment_keyboard(bot["_id"]))
        return
    try:
        payment = await create_gopay_payment(user, bot["fees"]["total"])
        await db.reseller_bots.update_one({"_id": bot["_id"]},
                                          {"$set": {"activation_deposit_id": payment["deposit"]["_id"]}})
        result = await send_photo_bytes(tid, payment["image"], "reseller-subscription-qris.jpg",
                                        caption=f"📱 <b>Bayar langganan bot @{escape(bot['username'])}</b>\n"
                                                f"Biaya paket: {fmt_amount(bot['fees']['total'], 'IDR')}\n"
                                                f"Total QRIS termasuk biaya transaksi: <b>{fmt_amount(payment['payment_amount'], 'IDR')}</b>\n"
                                                f"Berlaku sampai {payment['expires_at'].strftime('%H:%M UTC')}.\n"
                                                "Bot aktif otomatis setelah pembayaran terverifikasi.")
        if not result.get("ok"):
            raise RuntimeError(result.get("description") or "Gambar QRIS gagal dikirim")
    except Exception:
        logger.exception("Reseller subscription QRIS failed for bot %s", bot["_id"])
        await send_message(tid, "⚠️ QRIS belum berhasil ditampilkan. Pilih Bayar via QRIS untuk mencoba lagi "
                           "atau gunakan saldo IDR.", payment_keyboard(bot["_id"]))


async def show_mine(tid):
    bots = await db.reseller_bots.find({"owner_tid": tid}).sort("created_at", -1).limit(30).to_list(30)
    if not bots:
        await send_message(tid, "🤖 Kamu belum punya bot reseller. Pilih Bikin Bot Sendiri untuk memulai.")
        return
    lines = ["🤖 <b>Bot Reseller Saya</b>"]
    rows = []
    for bot in bots:
        status = bot.get("status") or "draft"
        expiry = (bot.get("expires_at") or "-")[:10]
        lines.append(f"\n@{escape(bot.get('username') or '')} · {escape(status)} · aktif sampai {expiry}")
        if status == "draft":
            rows.append([{"text": f"✏️ Lanjutkan @{bot.get('username') or 'bot'}", "callback_data": f"reseller:continue:{bot['_id']}"}])
        elif status == "pending_payment" or bot.get("renewal_pending"):
            rows.append([{"text": f"💳 Bayar @{bot.get('username') or 'bot'}", "callback_data": f"reseller:quote:{bot['_id']}"}])
        elif status in {"active", "expired", "paused", "inactive_no_sales"}:
            rows.append([{"text": f"🔄 Perpanjang @{bot.get('username') or 'bot'}", "callback_data": f"reseller:renew:{bot['_id']}"}])
    await send_message(tid, "\n".join(lines), {"inline_keyboard": rows} if rows else None)


async def handle_callback(tid, data, user):
    action, _, bot_id = data.removeprefix("reseller:").partition(":")
    if action == "new":
        await start_registration(tid)
        return
    if action == "mine":
        await show_mine(tid)
        return
    bot = await db.reseller_bots.find_one({"_id": bot_id, "owner_tid": tid})
    if not bot:
        await send_message(tid, "Bot reseller tidak ditemukan.")
        return
    if action == "continue":
        if bot.get("status") != "draft":
            await send_message(tid, "Pendaftaran bot ini sudah diproses.")
            return
        from bot import set_state
        await set_state(tid, "reseller_admin", {"bot_id": bot_id})
        await send_message(tid, f"Kirim Telegram User ID admin untuk @{escape(bot['username'])}.")
        return
    if action == "renew":
        try:
            bot = await begin_renewal(bot)
        except ValueError as exc:
            await send_message(tid, f"⚠️ {escape(str(exc))}")
            return
        await send_message(tid, fee_text(bot), payment_keyboard(bot_id))
        return
    if action == "quote":
        if bot.get("status") == "blocked":
            await send_message(tid, "⛔ Bot ini dinonaktifkan admin pusat. Hubungi admin pusat.")
            return
        await send_message(tid, fee_text(bot), payment_keyboard(bot_id))
        return
    if action == "pay":
        if bot.get("status") == "blocked":
            await send_message(tid, "⛔ Bot ini dinonaktifkan admin pusat. Pembayaran tidak tersedia.")
            return
        if bot.get("status") != "pending_payment" and not bot.get("renewal_pending"):
            await send_message(tid, "✅ Bot ini sudah aktif atau belum menunggu pembayaran baru.")
            return
        try:
            activated = await activate_paid_bot(bot)
        except Exception:
            logger.exception("Reseller activation failed for bot %s", bot_id)
            await send_message(tid, "⚠️ Gagal mengaktifkan bot. Saldo aman; coba lagi atau hubungi admin.")
            return
        if activated:
            fresh = await db.reseller_bots.find_one({"_id": bot_id})
            await send_message(tid, f"✅ @{escape(bot['username'])} aktif sampai {fresh['expires_at'][:10]}.\n"
                               "Admin bot bisa ketik <code>/settharga</code> untuk mengatur harga.")
            await notify_admin(f"✅ Bot reseller @{escape(bot['username'])} aktif. Owner: <code>{tid}</code>.")
        else:
            await send_message(tid, "💰 Saldo IDR belum cukup untuk biaya langganan. "
                               "Isi saldo melalui QRIS/rekening SellerBottel atau pilih Bayar via QRIS.",
                               payment_keyboard(bot_id))
        return
    if action == "qris":
        if bot.get("status") == "blocked":
            await send_message(tid, "⛔ Bot ini dinonaktifkan admin pusat. Pembayaran tidak tersedia.")
            return
        if bot.get("status") != "pending_payment" and not bot.get("renewal_pending"):
            await send_message(tid, "✅ Bot ini sudah aktif atau belum menunggu pembayaran baru.")
            return
        await send_subscription_qris(tid, user, bot)


async def scan_subscriptions():
    now = now_iso()
    expiring = await db.reseller_bots.find({"status": {"$in": ["active", "paused"]},
                                            "expires_at": {"$lte": now}}).to_list(1000)
    for bot in expiring:
        result = await db.reseller_bots.update_one({"_id": bot["_id"], "status": {"$in": ["active", "paused"]},
                                                    "expires_at": {"$lte": now}},
                                                   {"$set": {"status": "expired", "updated_at": now}})
        if result.modified_count:
            await send_message(bot["owner_tid"], f"⏸️ Langganan @{escape(bot['username'])} berakhir. "
                               "Buka Bikin Bot Sendiri → Bot Saya untuk memperpanjang.")
    inactivity_cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    candidates = await db.reseller_bots.find({"status": {"$in": ["active", "paused"]},
                                              "last_cycle_paid_at": {"$lte": inactivity_cutoff}}).to_list(1000)
    for bot in candidates:
        recent_sale = await db.purchases.find_one({
            "reseller_bot_id": bot["_id"],
            "status": {"$in": ["paid", "processing", "service_waiting", "delivered", "delivery_failed"]},
            "created_at": {"$gte": inactivity_cutoff},
        }, {"_id": 1})
        if recent_sale:
            continue
        changed = await db.reseller_bots.update_one(
            {"_id": bot["_id"], "status": {"$in": ["active", "paused"]}},
            {"$set": {"status": "inactive_no_sales", "inactivated_at": now_iso(),
                      "inactivation_reason": "14 hari tanpa penjualan", "updated_at": now_iso()}},
        )
        if changed.modified_count:
            await send_message(bot["owner_tid"],
                               f"⏸️ Bot @{escape(bot['username'])} dinonaktifkan karena 14 hari tanpa penjualan. "
                               "Biaya langganan tidak dikembalikan. "
                               "Buka Bikin Bot Sendiri → Bot Saya untuk berlangganan lagi.")
            await notify_admin(f"⏸️ Bot reseller @{escape(bot['username'])} nonaktif: 14 hari tanpa penjualan. "
                               f"Owner <code>{bot['owner_tid']}</code>.")
    soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    reminders = await db.reseller_bots.find({"status": "active", "expires_at": {"$gt": now, "$lte": soon},
                                             "expiry_reminder_at": {"$exists": False}}).to_list(1000)
    for bot in reminders:
        await db.reseller_bots.update_one({"_id": bot["_id"], "expiry_reminder_at": {"$exists": False}},
                                          {"$set": {"expiry_reminder_at": now}})
        await send_message(bot["owner_tid"], f"⏰ Langganan @{escape(bot['username'])} berakhir {bot['expires_at'][:10]}. "
                           "Perpanjang lewat Bikin Bot Sendiri → Bot Saya.")
    pending = await db.reseller_bots.find({"activation_deposit_id": {"$exists": True},
                                           "$or": [{"status": "pending_payment"},
                                                   {"renewal_pending": True}]}).to_list(1000)
    for bot in pending:
        deposit = await db.deposits.find_one({"_id": bot["activation_deposit_id"]}, {"status": 1})
        if not deposit or deposit.get("status") != "approved":
            continue
        try:
            if await activate_paid_bot(bot):
                fresh = await db.reseller_bots.find_one({"_id": bot["_id"]})
                await db.reseller_bots.update_one({"_id": bot["_id"]},
                                                  {"$unset": {"activation_deposit_id": ""}})
                await send_message(bot["owner_tid"],
                                   f"✅ Pembayaran terverifikasi. @{escape(bot['username'])} aktif sampai {fresh['expires_at'][:10]}.")
                await notify_admin(f"✅ Langganan reseller @{escape(bot['username'])} terbayar via QRIS.")
        except Exception:
            logger.exception("Auto activation failed for bot %s", bot["_id"])
    from reseller_payout import reconcile_payouts, remind_payout
    from reseller_contest import scan_contests
    await scan_contests()
    await reconcile_payouts()
    payouts = await db.reseller_payouts.find({"status": "pending_transfer",
                                              "reminder_sent_at": {"$exists": False}}).limit(100).to_list(100)
    for payout in payouts:
        try:
            await remind_payout(payout)
        except Exception:
            logger.exception("Payout reminder retry failed for %s", payout["_id"])


async def run_subscription_monitor(stop: asyncio.Event):
    while not stop.is_set():
        try:
            await scan_subscriptions()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reseller subscription monitor failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
