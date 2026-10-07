import asyncio
import base64
import json
import os
import subprocess
import uuid
import secrets
from html import escape
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from db import db, get_settings
from services import credit_deposit, notify_admin, now_iso, user_lang


NODE_DIR = os.path.join(os.path.dirname(__file__), "gobiz")


async def qris_expiry_minutes():
    """Return the admin-configured QRIS lifetime, falling back to .env / five minutes."""
    settings = await get_settings()
    raw = settings.get("gopay_qr_timeout_minutes")
    if raw is None:
        raw = os.environ.get("GOPAY_QR_TIMEOUT_MINUTES")
    try:
        if raw is None:
            raw = os.environ.get("QRIS_EXPIRY_MINUTES", "5")
        minutes = int(raw)
    except (TypeError, ValueError):
        minutes = 5
    return min(60, max(1, minutes))


def _parse_node_json(stdout):
    text = (stdout or "").strip()
    if not text:
        raise ValueError("GoPay provider tidak mengembalikan JSON.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as first_error:
        decoder = json.JSONDecoder()
        best_value = None
        best_end = -1

        # Node SDK logs may appear before the JSON payload. Find the
        # candidate JSON value that consumes the furthest part of stdout.
        # This avoids accidentally selecting a nested object/array from
        # inside the real top-level payload.
        for idx, char in enumerate(text):
            if char not in "[{":
                continue
            try:
                value, end = decoder.raw_decode(text[idx:])
            except json.JSONDecodeError:
                continue

            absolute_end = idx + end
            if text[absolute_end:].strip():
                continue
            if absolute_end > best_end:
                best_value = value
                best_end = absolute_end

        if best_value is not None:
            return best_value
        raise first_error


def _run_node(script, args=None, timeout=90):
    cmd = ["node", os.path.join(NODE_DIR, script), *(args or [])]
    env = os.environ.copy()
    env["NODE_PATH"] = os.path.join(NODE_DIR, "node_modules")

    result = subprocess.run(
        cmd,
        cwd=NODE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "GoPay provider gagal.")
    return _parse_node_json(result.stdout)


async def create_gopay_payment(user, amount, platform_code=None):
    amount = int(round(amount))
    if amount < 1:
        raise ValueError("Nominal IDR tidak valid.")

    admin_fee = int(round(amount * 0.007))
    if admin_fee < 1:
        admin_fee = 1
    deposit_total = amount + admin_fee

    deposit_id = str(uuid.uuid4())
    payment_id = str(uuid.uuid4())
    customer_id = user.get("customer_id")
    telegram_id = user.get("telegram_id")
    payment_scope = "store" if customer_id else "bot1"
    expires_in_minutes = await qris_expiry_minutes()
    expires = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)

    active_amount = None
    selected_code = None
    for _ in range(200):
        suffix = int(platform_code) if platform_code is not None else (secrets.randbelow(900) + 100)
        if not 100 <= suffix <= 999:
            suffix = secrets.randbelow(900) + 100
        candidate = deposit_total + suffix
        try:
            payment_doc = {
                "_id": payment_id,
                "payment_scope": payment_scope,
                "deposit_id": deposit_id,
                "user_tid": telegram_id,
                "customer_id": customer_id,
                "base_amount": amount,
                "payment_amount": candidate,
                "active_payment_amount": candidate,
                "status": "pending",
                "tx_id": None,
                "created_at": now_iso(),
                "expires_at": expires.isoformat(),
                "confirmed_at": None,
            }
            await db.gopay_payments.insert_one(payment_doc)
            active_amount = candidate
            selected_code = suffix
            break
        except DuplicateKeyError:
            continue

    if active_amount is None:
        raise RuntimeError("Tidak menemukan nominal QR GoPay yang unik.")

    deposit = {
        "_id": deposit_id,
        "user_tid": telegram_id,
        "customer_id": customer_id,
        "username": user.get("username", ""),
        "first_name": user.get("first_name", ""),
        "method": "gopay",
        "coin": None,
        "network": None,
        "currency": "IDR",
        "amount": amount,
        "admin_fee": admin_fee,
        "platform_code": selected_code,
        "payment_amount": active_amount,
        "credited_amount": amount,
        "tx_hash": None,
        "gopay_tx_id": None,
        "proof_file_id": None,
        "status": "pending",
        "auto_verified": True,
        "note": "Menunggu pembayaran QRIS All Payment",
        "created_at": now_iso(),
        "decided_at": None,
        "expires_at": expires.isoformat(),
    }

    try:
        await db.deposits.insert_one(deposit)
        data = await asyncio.to_thread(
            _run_node,
            "create_qris.mjs",
            [str(active_amount)],
        )
        image = base64.b64decode(data["image_base64"])
        return {
            "deposit": deposit,
            "payment_amount": active_amount,
            "admin_fee": admin_fee,
            "platform_code": selected_code,
            "image": image,
            "expires_at": expires,
            "expires_in_minutes": expires_in_minutes,
            "payment_id": payment_id,
        }
    except Exception:
        await db.gopay_payments.delete_one({"_id": payment_id})
        await db.deposits.delete_one({"_id": deposit_id})
        raise


async def _history():
    return await asyncio.to_thread(_run_node, "history.mjs", [], 90)


async def _flag_late_checkout(tx, amount):
    paid_at = _transaction_time(tx.get("transaction_time"))
    if not paid_at:
        return
    payment = await db.gopay_payments.find_one({
        "payment_scope": {"$in": ["bot1", "store"]}, "payment_type": "checkout",
        "payment_amount": amount, "status": "expired",
    }, sort=[("created_at", -1)])
    if not payment:
        return
    created_at = _transaction_time(payment.get("created_at"))
    if not created_at or paid_at < created_at:
        return
    tx_id = str(tx["tx_id"])
    try:
        await db.gopay_late_payments.insert_one({
            "_id": tx_id, "order_id": payment.get("order_id"),
            "payment_id": payment["_id"], "amount": amount,
            "transaction_time": paid_at.isoformat(), "created_at": now_iso(),
        })
    except DuplicateKeyError:
        return
    try:
        await notify_admin(
            "⚠️ <b>Pembayaran QRIS setelah invoice ditutup</b>\n"
            f"Invoice terkait: <code>{escape(str(payment.get('order_id') or '-'))}</code>\n"
            f"Nominal: Rp{amount:,}\nTX: <code>{escape(tx_id)}</code>\n"
            "Periksa transaksi merchant dan tangani pesanan/refund secara manual."
        )
    except Exception:
        pass


def _transaction_time(value):
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 10**11 else value, timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            value = value.strip()
            if value.isdigit():
                return _transaction_time(int(value))
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


async def poll_gopay_once():
    from direct_checkout import expire_qris_orders, finalize_qris_order
    async for payment in db.gopay_payments.find({
        "payment_scope": {"$in": ["bot1", "store"]}, "payment_type": "checkout",
        "status": "confirmed", "tx_id": {"$ne": None},
    }).sort("confirmed_at", -1).limit(100):
        order = await db.purchases.find_one({"_id": payment.get("order_id")}, {"status": 1})
        if order and order.get("status") == "pending_payment":
            await finalize_qris_order(payment["order_id"], payment["tx_id"])
    if os.environ.get("GOPAY_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return {"checked": False, "matched": 0}
    settings = await get_settings()
    if not settings.get("qris_enabled", False) and not await db.gopay_payments.find_one({
        "status": "pending", "payment_scope": {"$ne": "bot2"},
    }, {"_id": 1}):
        return {"checked": False, "matched": 0}

    now = datetime.now(timezone.utc)
    try:
        histories = await _history()
    except Exception:
        raise
    matched = 0

    for tx in histories:
        tx_id = tx.get("tx_id")
        tx_amount = int(round(float(tx.get("amount") or 0)))
        status = str(tx.get("status") or "").lower()
        tx_type = str(tx.get("type") or "").lower()
        if not tx_id or tx_amount <= 0:
            continue
        if tx_type and tx_type != "payin":
            continue
        if status and status not in {"settlement", "capture", "paid", "success", "successful"}:
            continue
        if await db.gopay_payments.find_one({"tx_id": tx_id, "status": "confirmed"}, {"_id": 1}):
            continue

        candidate = await db.gopay_payments.find_one({
            "status": "pending", "payment_scope": {"$ne": "bot2"},
            "active_payment_amount": tx_amount,
        })
        if not candidate:
            await _flag_late_checkout(tx, tx_amount)
            continue
        paid_at = _transaction_time(tx.get("transaction_time"))
        created_at = _transaction_time(candidate.get("created_at"))
        expires_at = _transaction_time(candidate.get("expires_at"))
        if not paid_at or not created_at or not expires_at or not (created_at <= paid_at <= expires_at):
            continue

        query = {
                "_id": candidate["_id"],
                "status": "pending",
                "payment_scope": {"$ne": "bot2"},
                "active_payment_amount": tx_amount,
            }
        payment = await db.gopay_payments.find_one_and_update(
            query,
            {
                "$set": {
                    "status": "confirmed",
                    "tx_id": tx_id,
                    "confirmed_at": now_iso(),
                },
                "$unset": {"active_payment_amount": ""},
            },
        )

        if not payment:
            continue

        if payment.get("payment_type") == "checkout" and payment.get("payment_scope") in {"bot1", "store"}:
            await finalize_qris_order(payment["order_id"], tx_id)
            matched += 1
            continue

        deposit = await db.deposits.find_one({"_id": payment["deposit_id"]})
        if not deposit or deposit.get("status") != "pending":
            continue

        deposit["credited_amount"] = float(payment["base_amount"])
        deposit["gopay_tx_id"] = tx_id
        await credit_deposit(deposit, note=f"GoPay QR terverifikasi. TX {tx_id}")
        matched += 1

    # Reconcile gateway history before expiring pending records, so payments made
    # before the deadline still succeed even when a polling cycle runs late.
    expired = await db.gopay_payments.find(
        {
            "status": "pending",
            "payment_scope": {"$ne": "bot2"},
            "payment_type": {"$ne": "checkout"},
            "expires_at": {"$lte": now.isoformat()},
            "expiry_notified_at": {"$exists": False},
        },
        {"_id": 1, "user_tid": 1, "deposit_id": 1, "payment_amount": 1, "qr_message_id": 1},
    ).to_list(500)
    await db.gopay_payments.update_many(
        {"status": "pending", "payment_scope": {"$ne": "bot2"},
         "payment_type": {"$ne": "checkout"}, "expires_at": {"$lte": now.isoformat()}},
        {"$set": {"status": "expired", "expired_at": now_iso(), "expiry_notified_at": now_iso()}, "$unset": {"active_payment_amount": ""}},
    )
    for payment in expired:
        try:
            if not payment.get("user_tid"):
                continue
            from tgapi import delete_message, send_message
            if payment.get("qr_message_id"):
                try:
                    await delete_message(payment["user_tid"], payment["qr_message_id"])
                except Exception:
                    logger.exception("Could not delete expired deposit QR message")
            await send_message(
                payment["user_tid"],
                "⌛ <b>Pembayaran deposit expired</b>\n\n"
                "Kode QR sudah tidak berlaku. Silakan request QR baru untuk melanjutkan deposit.",
            )
        except Exception:
            logger.exception("Could not notify expired deposit QR")
    await db.deposits.update_many(
        {"method": "gopay", "bot2": {"$ne": True}, "status": "pending", "expires_at": {"$lte": now.isoformat()}},
        {"$set": {"status": "expired", "decided_at": now_iso()}},
    )
    await expire_qris_orders()

    return {"checked": True, "matched": matched}


async def run_gopay_monitor(stop_event: asyncio.Event):
    interval = max(10, int(os.environ.get("GOPAY_POLL_INTERVAL", "15")))
    while not stop_event.is_set():
        try:
            result = await poll_gopay_once()
            if result.get("checked") and result.get("matched"):
                print(f"[GoPay] {result['matched']} pembayaran terverifikasi.")
        except Exception as exc:
            print(f"[GoPay] monitor error: {exc}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
