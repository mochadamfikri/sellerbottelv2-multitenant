"""Presentation-only masking. Never changes canonical identifiers."""
import re
from db import db


def purchase_source(order):
    """Checkout channel, never registration/traffic source or Telegram presence.

    Legacy QRIS scopes and storefront-only idempotency metadata are reliable
    creation-flow evidence. Ambiguous old records stay unknown; no backfill.
    """
    explicit = str(order.get("purchase_source") or "").upper()
    if explicit in {"WEB", "BOT"}:
        return explicit
    scope = str(order.get("payment_scope") or "").lower()
    if scope == "store":
        return "WEB"
    if scope in {"bot1", "bot2"} or order.get("bot2") or order.get("reseller_bot_id"):
        return "BOT"
    if order.get("customer_id") and order.get("idempotency_key"):
        return "WEB"
    return "TIDAK DIKETAHUI"


def purchase_heading(source):
    return {"WEB": "🌐 <b>Penjualan Web</b>", "BOT": "🤖 <b>Penjualan Bot</b>"}.get(source, "🛒 <b>Penjualan</b>")


def mask_telegram_id(value):
    text = str(value or "")
    if not re.fullmatch(r"[1-9][0-9]{5,19}", text):
        return "-"
    return text[:3] + "*" * (len(text) - 5) + text[-2:]


def mask_telegram_username(value):
    text = str(value or "").lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", text):
        return "-"
    return "@" + text[:2] + "*" * (len(text) - 2)


async def purchase_identity(order):
    tid = order.get("user_tid")
    if not tid and order.get("customer_id"):
        customer = await db.store_customers.find_one({"_id": order["customer_id"]}, {"telegram_id": 1})
        tid = (customer or {}).get("telegram_id")
    user = await db.bot_users.find_one({"telegram_id": tid}, {"telegram_id": 1, "username": 1}) if tid else None
    return mask_telegram_id((user or {}).get("telegram_id")), mask_telegram_username((user or {}).get("username"))
