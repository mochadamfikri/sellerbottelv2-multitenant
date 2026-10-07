import uuid
import logging
import math
import os
import re
import asyncio
import secrets
import base64
from html import escape
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from db import db, get_settings
from rates import get_rate
from chain import verify_tx, looks_like_tx_hash
from tgapi import (
    send_message as tg_send_message,
    edit_message as tg_edit_message,
    answer_callback,
    send_document as tg_send_document,
    delete_message,
    send_photo_bytes as tg_send_photo_bytes,
    send_photo_by_id as tg_send_photo_by_id,
    send_photo_by_url as tg_send_photo_by_url,
    send_animation_by_id as tg_send_animation_by_id,
    send_animation_by_url as tg_send_animation_by_url,
    send_animation_bytes as tg_send_animation_bytes,
    send_video_by_id as tg_send_video_by_id,
    send_video_by_url as tg_send_video_by_url,
    send_video_bytes as tg_send_video_bytes,
)
from services import credit_deposit, reject_deposit, cancel_deposit, notify_admin, notify_transaction_channel, notify_transaction_admin, fmt_amount, now_iso, user_lang
from storage import get_object
from i18n import t, LANG_NAMES
from checkout import execute_checkout, stock_for
from inventory import decrypt_items
from join_gate import check_user_membership, build_gate_keyboard, clear_cache_for_user
from gopay_provider import create_gopay_payment
from direct_checkout import create_qris_order, qris_ready, quote_items
from pricing import price_for_product
from product_catalog import catalog_slice, catalog_token
from promo_service import coupon_is_time_valid
from bot_tenant_scope import get_current_scope

logger = logging.getLogger("bot")

_EDIT_TARGETS = {}


async def _remember_bot_message(chat_id, response, flow=None):
    try:
        result = (response or {}).get("result") or {}
        message_id = result.get("message_id")
        if message_id is None:
            return
        doc = {
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "direction": "out",
            "created_at": datetime.now(timezone.utc),
        }
        if flow:
            doc["flow"] = flow
        await db.bot_chat_messages.update_one(
            {"chat_id": int(chat_id), "message_id": int(message_id)},
            {"$set": doc},
            upsert=True,
        )
    except Exception:
        logger.debug("Could not remember outgoing bot message", exc_info=True)


async def _delete_flow_messages(chat_id, message_id):
    """Delete a message plus its flow-siblings (e.g. guide video + text).

    Used by the no-pile-up rule so multi-message flows are fully replaced.
    """
    ids = [message_id]
    try:
        doc = await db.bot_chat_messages.find_one(
            {"chat_id": int(chat_id), "message_id": int(message_id)},
            {"flow": 1},
        )
        flow = (doc or {}).get("flow")
        if flow:
            async for sib in db.bot_chat_messages.find(
                {"chat_id": int(chat_id), "flow": flow}, {"message_id": 1}
            ):
                ids.append(sib["message_id"])
    except Exception:
        logger.debug("Could not look up flow siblings", exc_info=True)
    for mid in dict.fromkeys(ids):
        try:
            await delete_message(chat_id, mid)
        except Exception:
            pass


async def send_document(chat_id, data, filename, caption=None):
    result = await tg_send_document(chat_id, data, filename, caption=caption)
    await _remember_bot_message(chat_id, result)
    return result


async def send_photo_bytes(chat_id, data, filename="photo.jpg", caption=None, kb=None):
    result = await tg_send_photo_bytes(chat_id, data, filename, caption=caption, kb=kb)
    await _remember_bot_message(chat_id, result)
    return result


async def send_message(chat_id, text, kb=None):
    message_id = _EDIT_TARGETS.pop(chat_id, None)
    if message_id is not None:
        try:
            result = await tg_edit_message(chat_id, message_id, text, kb=kb)
            if result.get("ok"):
                await _remember_bot_message(chat_id, result)
                return result
        except Exception:
            logger.exception("Failed to edit callback message; falling back to sendMessage")
        # Edit failed (e.g. the target is a photo/media message): replace it
        # instead of stacking a new message below it.
        try:
            await delete_message(chat_id, message_id)
        except Exception:
            logger.debug("Could not delete replaced message", exc_info=True)
    result = await tg_send_message(chat_id, text, kb=kb)
    await _remember_bot_message(chat_id, result)
    return result


_CHECKOUT_LOCKS = {}


def _checkout_lock(tid):
    lock = _CHECKOUT_LOCKS.get(tid)
    if lock is None:
        lock = asyncio.Lock()
        _CHECKOUT_LOCKS[tid] = lock
    return lock


NET_LABELS = {"SOL": "Solana", "POL": "Polygon", "BNB": "BNB (BEP-20)", "AVAX": "Avalanche"}
CUR_FIELD = {"USD": "balance_usd", "IDR": "balance_idr"}


def _reseller_enabled() -> bool:
    """Whether the 'Bikin Bot Sendiri' reseller entry is active for this bot."""
    try:
        scope = get_current_scope()
        if scope is None:
            return True
        return bool(getattr(scope, "reseller_enabled", scope.slug == "central"))
    except Exception:
        return True


def main_menu_kb(lang):
    """Main menu in the accepted layout: full-width headers, grouped rows."""
    rows = [
        [{"text": t(lang, "btn_products"), "callback_data": "menu:products",
          "style": "success"}],
        [{"text": t(lang, "btn_deposit"), "callback_data": "menu:deposit",
          "style": "primary"},
         {"text": t(lang, "btn_stock"), "callback_data": "menu:stock",
          "style": "primary"}],
        [{"text": t(lang, "btn_settings"), "callback_data": "menu:settings",
          "style": "success"}],
        [{"text": t(lang, "btn_history"), "callback_data": "menu:history",
          "style": "primary"},
         {"text": t(lang, "btn_help"), "callback_data": "menu:help",
          "style": "primary"},
         {"text": t(lang, "btn_cart"), "callback_data": "menu:cart",
          "style": "primary"}],
    ]
    if _reseller_enabled():
        rows.append([{"text": "🤖 Bikin Bot Sendiri", "callback_data": "reseller:entry",
                      "style": "danger"}])
    return {"inline_keyboard": rows}


def back_kb(lang):
    return {"inline_keyboard": [[{"text": t(lang, "btn_main"), "callback_data": "menu:main"}]]}


def cancel_kb(lang):
    return {"inline_keyboard": [[{"text": t(lang, "btn_cancel"), "callback_data": "cancel"}]]}


async def get_user(tg_from: dict) -> dict:
    tid = tg_from["id"]
    user = await db.bot_users.find_one({"telegram_id": tid})
    if not user:
        user = {
            "_id": str(uuid.uuid4()), "telegram_id": tid,
            "username": tg_from.get("username", ""), "first_name": tg_from.get("first_name", ""),
            "currency": None, "lang": "id", "balance_usd": 0.0, "balance_idr": 0.0,
            "frozen": False, "frozen_reason": "", "cart": [],
            "state": None, "state_data": {}, "created_at": now_iso(),
        }
        await db.bot_users.insert_one(user)
    else:
        await db.bot_users.update_one({"telegram_id": tid}, {"$set": {
            "username": tg_from.get("username", ""), "first_name": tg_from.get("first_name", "")}})
        if not user.get("lang"):
            user["lang"] = "id"
    return user


async def set_state(tid, state, data=None):
    await db.bot_users.update_one({"telegram_id": tid}, {"$set": {"state": state, "state_data": data or {}}})


async def product_price(prod: dict, currency: str, quantity: int = 1) -> float:
    pricing = await price_for_product(prod, currency, quantity)
    return pricing["unit_price"]


async def stock_label(prod, lang):
    stock = await stock_for(prod)
    return "∞" if stock is None else str(int(stock))


async def has_stock(prod, qty=1):
    stock = await stock_for(prod)
    return True if stock is None else stock >= qty


def norm_cart(cart):
    out = []
    for it in cart or []:
        if isinstance(it, str):
            out.append({"pid": it, "qty": 1})
        elif isinstance(it, dict) and it.get("pid"):
            out.append({"pid": it["pid"], "qty": max(1, int(it.get("qty", 1)))})
    return out


def user_label(user):
    uname = f"@{user.get('username')}" if user.get("username") else "-"
    return f"{user.get('first_name','')} ({uname}, ID: <code>{user['telegram_id']}</code>)"


def _format_start_date(value):
    """Format a stored first-/start date without relying on a particular legacy type."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return "-"
    return parsed.strftime("%d-%m-%Y")


async def _resolve_bot_display_name(settings: dict) -> str:
    """Store/brand name for the /start greeting.

    Prefers the BotFather display name detected via getMe (cached on the
    worker scope), then the tenant settings, then the legacy fallback.
    """
    try:
        scope = get_current_scope()
        if scope is not None and scope.bot_display_name:
            return scope.bot_display_name
    except Exception:
        pass
    return str(settings.get("store_name") or settings.get("tenant_name") or "Bot Store")


async def _send_welcome_photo(chat_id, photo_ref: str, caption: str, kb,
                            animated: bool = False):
    """Send the /start banner photo (or GIF animation), falling back gracefully.

    photo_ref may be a Telegram file_id, an http(s) URL, or a local path.
    Telegram captions are limited to 1024 chars: when the welcome text is
    longer, the media goes first and the text follows as its own message.
    """
    if len(caption) <= 1024:
        short_caption: str | None = caption
        follow_up: str | None = None
    else:
        short_caption = None
        follow_up = caption
    try:
        if animated:
            send_id, send_url, send_bytes = (
                tg_send_animation_by_id, tg_send_animation_by_url,
                tg_send_animation_bytes)
        else:
            send_id, send_url, send_bytes = (
                tg_send_photo_by_id, tg_send_photo_by_url, tg_send_photo_bytes)
        if photo_ref.startswith(("http://", "https://")):
            result = await send_url(chat_id, photo_ref, caption=short_caption, kb=kb)
        elif os.path.isfile(photo_ref):
            with open(photo_ref, "rb") as f:
                data = f.read()
            result = await send_bytes(chat_id, data, caption=short_caption, kb=kb)
        else:
            result = await send_id(chat_id, photo_ref, caption=short_caption, kb=kb)
        await _remember_bot_message(chat_id, result)
        if not (result or {}).get("ok"):
            raise RuntimeError(f"welcome media not ok: {result}")
    except Exception:
        logger.exception("Welcome media failed; falling back to text welcome")
        await send_message(chat_id, caption, kb=kb)
        return
    if follow_up:
        await send_message(chat_id, follow_up, kb=kb)


def _looks_animated(ref: str) -> bool:
    return ref.lower().split("?")[0].endswith(".gif")


async def _send_welcome_flexible(chat_id, text: str, kb, store_name: str) -> bool:
    """Send the /start greeting honoring the tenant's welcome_media config.

    Returns True when a media greeting was sent, False for text fallback.
    """
    try:
        scope = get_current_scope()
        media = dict(getattr(scope, "welcome_media", None) or {})
        slug = getattr(scope, "slug", "bot") or "bot"
        display = (getattr(scope, "bot_display_name", "") or store_name)
    except Exception:
        return False
    if not media.get("enabled"):
        return False
    mode = media.get("mode") or "auto"
    try:
        if mode == "auto":
            from welcome_banner import ensure_auto_banner
            path = ensure_auto_banner(slug, display,
                                      media.get("tagline") or "DIGITAL STORE")
            await _send_welcome_photo(chat_id, path, text, kb)
            return True
        ref = media.get("file") or ""
        if not ref:
            return False
        kind = (media.get("kind") or "").lower()
        animated = kind == "animation" or (kind != "photo" and _looks_animated(ref))
        await _send_welcome_photo(chat_id, ref, text, kb, animated=animated)
        return True
    except Exception:
        logger.exception("Flexible welcome failed; falling back to text")
        return False


async def show_start_welcome(chat_id, user):
    """Send the accepted /start message using current store, order, and coupon data."""
    settings = await get_settings()
    store_name = await _resolve_bot_display_name(settings)
    currency = user.get("currency") or "IDR"
    balance = fmt_amount(user.get(CUR_FIELD[currency], 0), currency)
    username = f"@{user['username']}" if user.get("username") else "-"
    order_qty = 0
    async for order in db.purchases.find({
        "user_tid": user["telegram_id"], "status": {"$in": ["paid", "delivered"]},
    }, {"items": 1}):
        order_qty += sum(max(0, int(item.get("qty") or 0)) for item in order.get("items") or [])

    coupons = []
    for coupon in await _available_coupons():
        coupons.append(f"• <code>{escape(str(coupon['code']))}</code>")
    coupon_text = "\n".join(coupons) if coupons else "-"

    text = (
        f"🙌👋 Selamat Datang di {escape(store_name)}\n"
        f"💫 {escape(store_name)} 💫\n\n"
        "<blockquote>"
        f"📛 Nama pengguna: {escape(user.get('first_name') or '-')}\n"
        f"🪪 Username: <b>{escape(username)}</b>\n"
        f"🆔 User ID: <code>{user['telegram_id']}</code>\n"
        f"🏧 Saldo tersedia: <b>{balance}</b>\n"
        f"♻️ Bergabung: <b>{_format_start_date(user.get('first_start_at') or user.get('created_at'))}</b>\n"
        f"📠 Total pesanan: <b>{order_qty}</b> PCS"
        "</blockquote>\n\n"
        "Ketik /stock untuk melihat daftar stock tersedia\n"
        "Ketik /coupon untuk melihat daftar kupon dan cara penggunaannya\n\n"
        f"Coupon tersedia:\n{coupon_text}\n\n"
        "Silahkan pilih menu di bawah ini"
    )
    kb = main_menu_kb(user.get("lang", "id"))
    # No-pile-up rule: when navigating from a button, replace the old message
    # (plus its flow-siblings, e.g. guide video + text) instead of stacking.
    old_id = _EDIT_TARGETS.pop(chat_id, None)
    if old_id is not None:
        await _delete_flow_messages(chat_id, old_id)
    if not await _send_welcome_flexible(chat_id, text, kb, store_name):
        await tg_send_message(chat_id, text, kb=kb)


async def show_main_menu(chat_id, user):
    """Keep every return-to-main entry point on the same accepted dynamic welcome."""
    await show_start_welcome(chat_id, user)


async def show_currency_selection(chat_id, lang="id"):
    kb = {"inline_keyboard": [
        [{"text": "💵 USD (Dolar AS)", "callback_data": "cur:USD"}],
        [{"text": "🇮🇩 IDR (Rupiah)", "callback_data": "cur:IDR"}],
    ]}
    await send_message(chat_id, t(lang, "choose_currency"), kb=kb)


# ============ PRODUCTS & STOCK ============

def stock_button_style(stock) -> str:
    """Inline button color by stock availability (Bot API 9.4 `style` field).

    🔴 danger  = stock 0–4 (almost out)
    🟢 success = stock 5–9
    🔵 primary = stock 10+ or unlimited
    """
    if stock is None:
        return "primary"
    try:
        n = int(stock)
    except (TypeError, ValueError):
        return "primary"
    if n <= 4:
        return "danger"
    if n <= 9:
        return "success"
    return "primary"


async def show_products(chat_id, user, page=1, catalog=None):
    products = await db.products.find({"active": True}).to_list(None)
    group, entries, page, pages = catalog_slice(products, catalog, page)
    rows = []
    lines = ["📚 <b>Katalog produk</b>", "Pilih katalog untuk melihat varian, harga, dan stok."]
    if catalog:
        lines = ["📦 <b>" + escape(group["name"] if group else "Katalog tidak tersedia") + "</b>", ""]
        for product in entries:
            stock = await stock_for(product)
            pricing = await price_for_product(product, user["currency"], 1)
            stock_text = "∞" if stock is None else str(int(stock))
            lines.append(f"• {escape(product['name'][:100])} · <b>{fmt_amount(pricing['unit_price'], user["currency"])}</b> · Stok {stock_text}")
            rows.append([{"text": product['name'][:80], "callback_data": f"prod:{product['_id']}",
                          "style": stock_button_style(stock)}])
        lines.append(t(user.get("lang", "id"), "stock_legend"))
        callback = f"catalog:{catalog}:"
    else:
        rows = [[{"text": f"{entry['name'][:80]} · {len(entry['products'])} pilihan", "callback_data": f"catalog:{entry['token']}:1"}] for entry in entries]
        callback = "products:"
    if not entries:
        lines.append("Belum ada produk aktif.")
    nav = []
    if page > 1:
        nav.append({"text": "⬅️ Sebelumnya", "callback_data": f"{callback}{page-1}"})
    if page < pages:
        nav.append({"text": "Berikutnya ➡️", "callback_data": f"{callback}{page+1}"})
    if nav:
        rows.append(nav)
    rows.append([{"text": "🔄 Perbarui stok", "callback_data": f"{callback}{page}"}])
    if catalog:
        rows.append([{"text": "📚 Semua katalog", "callback_data": "products:1"}])
    lines.append(f"\nHalaman {page}/{pages}")
    rows.append([{"text": t(user.get("lang", "id"), "btn_main"), "callback_data": "menu:main"}])
    await send_message(chat_id, "\n".join(lines), kb={"inline_keyboard": rows})

async def show_stock(chat_id, user, edit_id=None):
    await show_stock_view(chat_id, user, 1, loading=True, edit_id=edit_id)


async def _available_coupons():
    """Coupons that are active, time-valid, and have quota left."""
    out = []
    async for coupon in db.promo_coupons.find({"active": True}):
        if not coupon.get("code"):
            continue
        if not coupon_is_time_valid(coupon):
            continue
        quota = coupon.get("quota_total")
        if quota is not None and int(coupon.get("used_count") or 0) >= int(quota):
            continue
        out.append(coupon)
    return out


def _coupon_discount_text(coupon, currency) -> str:
    if coupon.get("type") == "percent":
        try:
            val = float(coupon.get("value") or 0)
        except (TypeError, ValueError):
            val = 0
        text = f"{val:g}%"
        if coupon.get("max_discount"):
            text += f" (maks {fmt_amount(coupon['max_discount'], currency)})"
        return text
    return fmt_amount(coupon.get("value") or 0, coupon.get("currency") or currency)


async def _coupon_products_text(coupon) -> str:
    pids = [str(x) for x in (coupon.get("product_ids") or [])]
    if not pids:
        return "Semua produk"
    names = []
    async for p in db.products.find({"_id": {"$in": pids}}, {"name": 1}):
        if p.get("name"):
            names.append(str(p["name"]))
    if not names:
        return "Produk tertentu"
    text = ", ".join(names[:3])
    return text + ("..." if len(names) > 3 else "")


def _coupon_min_text(coupon, currency) -> str:
    try:
        min_p = float(coupon.get("min_purchase") or 0)
    except (TypeError, ValueError):
        min_p = 0
    return fmt_amount(min_p, currency) if min_p > 0 else "-"


COUPON_GUIDE_TEXT = (
    "❓ <b>Cara Menggunakan Kupon</b>\n\n"
    "1. Buka <b>Keranjang</b> dari menu utama\n"
    "2. Klik tombol <b>🎟️ Gunakan Kupon</b>\n"
    "3. Ketik kode kupon kamu\n"
    "4. Lanjut checkout — diskon otomatis kepotong!"
)

_GUIDE_VIDEO_PLACEHOLDER = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "runtime", "coupon_guide_placeholder.mp4"))


async def _get_coupon_guide_video() -> str:
    """Shared coupon guide video ref (central panel config for all bots).

    Falls back to the local placeholder video until the owner uploads one.
    """
    try:
        from db import client as _client
        from tenant_db import resolve_platform_database_name
        pdb = _client[resolve_platform_database_name(os.environ)]
        doc = await pdb["platform_config"].find_one({"_id": "central_bot"}) or {}
        ref = (doc.get("coupon_guide_video") or "").strip()
        if ref:
            return ref
    except Exception:
        logger.debug("Could not read coupon guide video config", exc_info=True)
    return os.path.abspath(_GUIDE_VIDEO_PLACEHOLDER)


async def _send_guide_video(chat_id, ref: str):
    """Send the guide video from a file_id, URL, or local path."""
    if ref.startswith(("http://", "https://")):
        return await tg_send_video_by_url(chat_id, ref)
    if os.path.isfile(ref):
        with open(ref, "rb") as f:
            data = f.read()
        return await tg_send_video_bytes(chat_id, data)
    return await tg_send_video_by_id(chat_id, ref)


async def show_coupons(chat_id, user):
    """List available coupons with discount/product/minimum + usage guide."""
    lang = user.get("lang", "id")
    currency = user.get("currency") or "IDR"
    coupons = await _available_coupons()
    lines = [
        "🎟️ <b>Daftar Kupon</b>",
        "",
        "Halo! Ini kupon yang bisa kamu pakai biar belanja makin hemat.",
        "",
        "<b>Cara menggunakan:</b>",
        "1. Pilih kupon yang kamu mau dari daftar",
        "2. Masukkan kodenya di <b>keranjang</b> saat checkout",
        "3. Diskon langsung kepotong otomatis",
        "",
    ]
    if not coupons:
        lines.append("Belum ada kupon tersedia saat ini.")
    for i, coupon in enumerate(coupons, 1):
        lines.extend([
            f"<b>{i}. <code>{escape(str(coupon['code']))}</code></b>",
            "<blockquote>"
            f"Potongan: {escape(_coupon_discount_text(coupon, currency))}\n"
            f"Produk: {escape(await _coupon_products_text(coupon))}\n"
            f"Minimum: {escape(_coupon_min_text(coupon, currency))}"
            "</blockquote>",
            "",
        ])
    kb = {"inline_keyboard": [
        [{"text": "❓ Cara lengkap menggunakan kupon", "callback_data": "coupon:guide"}],
        [{"text": t(lang, "btn_main"), "callback_data": "menu:main"}],
    ]}
    await send_message(chat_id, "\n".join(lines), kb=kb)


async def handle_coupon_guide(chat_id, user, edit_id=None):
    """Guide flow: loading animation -> video -> tutorial page.

    The loading animation keeps the chat feeling alive while the video
    is prepared, instead of looking stuck/hung. The old (list) message
    is replaced, not stacked.
    """
    _EDIT_TARGETS.pop(chat_id, None)  # loading helper owns the message lifecycle
    loading_id = await _loading_message(
        chat_id, "Mengambil tutorial dari database", edit_id=edit_id)
    flow = f"guide:{chat_id}:{int(datetime.now(timezone.utc).timestamp())}"
    try:
        vres = await _send_guide_video(chat_id, await _get_coupon_guide_video())
        if not (vres or {}).get("ok"):
            logger.warning("Coupon guide video not ok: %s", vres)
        else:
            await _remember_bot_message(chat_id, vres, flow=flow)
    except Exception:
        logger.exception("Coupon guide video failed")
    if loading_id:
        try:
            await delete_message(chat_id, loading_id)
        except Exception:
            logger.debug("Could not delete guide loading message", exc_info=True)
    gres = await tg_send_message(
        chat_id,
        COUPON_GUIDE_TEXT + "\n\n📹 <i>Tolong lihat video di atas ya!</i>",
        kb=back_kb(user.get("lang", "id")),
    )
    await _remember_bot_message(chat_id, gres, flow=flow)


STOCK_PAGE_SIZE = 10


def _stock_pages(groups):
    """Split catalog groups into pages: max STOCK_PAGE_SIZE products per page,
    never splitting a group across pages (a huge group gets its own page)."""
    numbered = []
    n = 0
    for gi, g in enumerate(groups):
        for p in g["products"]:
            n += 1
            numbered.append((gi, p, n))
    by_group = {}
    for gi, p, number in numbered:
        by_group.setdefault(gi, []).append((gi, p, number))
    pages, cur, cur_count = [], [], 0
    for gi, g in enumerate(groups):
        items = by_group.get(gi, [])
        if cur and cur_count + len(items) > STOCK_PAGE_SIZE:
            pages.append(cur)
            cur, cur_count = [], 0
        cur.extend(items)
        cur_count += len(items)
    if cur:
        pages.append(cur)
    return pages or [[]]


def _cart_count(user) -> int:
    return sum(int(i.get("qty") or 0) for i in norm_cart(user.get("cart")))


async def _loading_message(chat_id, label="Mengambil data dari database",
                           steps=(25, 50, 70), delay=0.25, edit_id=None):
    """Fast fetch-phase loading bar (0-70%).

    With edit_id, the existing message is reused (no chat pile-up).
    A media message (e.g. welcome photo) can't take a text edit, so it is
    replaced: deleted, then the loading runs as a fresh message.
    The caller completes the view at 70%+ by editing the returned
    message_id into the finished content.
    """
    def bar(p):
        filled = p * 10 // 100
        return "█" * filled + "░" * (10 - filled)

    async def _send_fresh():
        try:
            res = await tg_send_message(chat_id, f"⏳ {label}...\n{bar(0)} 0%")
            return (res.get("result") or {}).get("message_id")
        except Exception:
            return None

    mid = None
    if edit_id is not None:
        try:
            res = await tg_edit_message(chat_id, edit_id, f"⏳ {label}...\n{bar(0)} 0%")
            if res.get("ok"):
                mid = edit_id
            else:
                try:
                    await delete_message(chat_id, edit_id)
                except Exception:
                    pass
        except Exception:
            pass
    if mid is None:
        mid = await _send_fresh()
    if not mid:
        return None
    for p in steps:
        await asyncio.sleep(delay)
        try:
            res = await tg_edit_message(chat_id, mid, f"⏳ {label}...\n{bar(p)} {p}%")
            if not res.get("ok"):
                break
        except Exception:
            break
    return mid


async def show_stock_view(chat_id, user, page=1, *, loading=False, edit_id=None):
    """Stock overview grouped by catalog: numbered products, quick-add buttons,
    per-page group integrity, summary on the last page only."""
    from product_catalog import catalog_groups
    lang = user.get("lang", "id")
    settings = await get_settings()
    bot_name = await _resolve_bot_display_name(settings)

    products = await db.products.find({"active": True}).to_list(None)
    groups = catalog_groups(products)
    pages = _stock_pages(groups)
    total_pages = len(pages)
    page = max(1, min(int(page or 1), total_pages))
    items = pages[page - 1]

    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    def _letter(gi):
        if gi < len(letters):
            return letters[gi]
        return f"{gi + 1}"

    lines = ["Stock yang tersedia di", f"<b>{escape(bot_name)}</b>"]
    last_gi = None
    for gi, p, number in items:
        if gi != last_gi:
            lines.append(f"{_letter(gi)}. {escape(groups[gi]['name'])}")
            last_gi = gi
        stock = await stock_for(p)
        stock_text = "∞" if stock is None else str(int(stock))
        lines.append(f"    {number}. {escape(p['name'][:80])} -&gt; {stock_text}")

    if not items:
        lines.append("Belum ada produk.")

    if page == total_pages and products:
        total_stock = 0
        unlimited = 0
        for g in groups:
            for p in g["products"]:
                s = await stock_for(p)
                if s is None:
                    unlimited += 1
                else:
                    total_stock += int(s)
        stock_total_text = f"{total_stock} (+∞)" if unlimited else str(total_stock)
        lines.append("")
        lines.append("<b>RINGKASAN</b>")
        lines.append(f"Total katalog: {len(groups)}")
        lines.append(f"Total product: {len(products)}")
        lines.append(f"Total stock: {stock_total_text}")
        lines.append("")
        lines.append("<b>KETERANGAN STOK</b>")
        lines.append("🎨 🔴 1–4 · 🟢 5–9 · 🔵 10+")

    lines.append(f"\nHalaman {page}/{total_pages}")

    rows = []
    btns = []
    for gi, p, number in items:
        stock = await stock_for(p)
        btns.append({"text": str(number), "callback_data": f"stockadd:{page}:{p['_id']}",
                     "style": stock_button_style(stock)})
    for i in range(0, len(btns), 5):
        rows.append(btns[i:i + 5])
    nav = []
    if page > 1:
        nav.append({"text": "⬅️ Sebelumnya", "callback_data": f"stockpage:{page - 1}"})
    if page < total_pages:
        nav.append({"text": "Berikutnya ➡️", "callback_data": f"stockpage:{page + 1}"})
    if nav:
        rows.append(nav)
    count = _cart_count(user)
    rows.append([
        {"text": t(lang, "btn_main"), "callback_data": "menu:main"},
        {"text": f"🛒 Keranjang ({count})", "callback_data": "menu:cart"},
    ])
    if loading:
        # The loading helper owns the message lifecycle (reuse or replace),
        # so don't let send_message touch the callback message afterwards.
        _EDIT_TARGETS.pop(chat_id, None)
        loading_id = await _loading_message(
            chat_id, "Mengambil data stok dari database", edit_id=edit_id)
        if loading_id:
            try:
                res = await tg_edit_message(chat_id, loading_id, "\n".join(lines),
                                            kb={"inline_keyboard": rows})
                if res.get("ok"):
                    return
            except Exception:
                pass
            logger.debug("Loading edit failed, falling back to send", exc_info=True)
    await send_message(chat_id, "\n".join(lines), kb={"inline_keyboard": rows})


async def handle_stock_quick_add(chat_id, user, page, pid, cb_id):
    """Add one unit of a stock-listed product to the cart, refresh the view."""
    lang = user.get("lang", "id")
    p = await db.products.find_one({"_id": pid, "active": True})
    if not p:
        await show_stock_view(chat_id, user, page)
        return
    cart = norm_cart(user.get("cart"))
    existing = next((i for i in cart if i["pid"] == pid), None)
    new_qty = (existing["qty"] + 1) if existing else 1
    if not await has_stock(p, new_qty):
        await send_message(chat_id, t(lang, "qty_max", stock=await stock_label(p, lang)),
                           kb=back_kb(lang))
        return
    if existing:
        existing["qty"] = new_qty
    else:
        cart.append({"pid": pid, "qty": 1})
    await save_cart(user["telegram_id"], cart)
    user["cart"] = cart
    try:
        await answer_callback(cb_id, f"✅ {p['name'][:40]} masuk keranjang")
    except Exception:
        pass
    await show_stock_view(chat_id, user, page)


async def show_product_detail(chat_id, user, pid):
    lang = user.get("lang", "id")
    p = await db.products.find_one({"_id": pid, "active": True})
    if not p:
        await send_message(chat_id, t(lang, "product_not_found"), kb=back_kb(lang))
        return
    pricing = await price_for_product(p, user["currency"])
    price = pricing["unit_price"]
    type_label = t(lang, {"file": "type_file", "link": "type_link", "license": "type_license", "inventory": "type_inventory"}.get(p["delivery_type"], "type_file"))
    text = t(lang, "prod_detail", name=p["name"], desc=p.get("description", ""), type=type_label,
             price=fmt_amount(price, user["currency"]), stock=await stock_label(p, lang))
    if pricing["discount_per_unit"] > 0:
        text += (f"\n\n🎉 <b>Diskon aktif: {escape(str(pricing.get('discount_name') or 'Promo'))}</b>\n"
                 f"Harga normal: <s>{fmt_amount(pricing['base_unit_price'], user['currency'])}</s>\n"
                 f"Hemat: <b>{fmt_amount(pricing['discount_per_unit'], user['currency'])}</b> per unit")
    rows = []
    if await has_stock(p):
        rows.append([{"text": t(lang, "btn_buy", price=fmt_amount(price, user["currency"])), "callback_data": f"buy:{pid}"}])
        rows.append([{"text": t(lang, "btn_add_cart"), "callback_data": f"cartadd:{pid}"}])
    else:
        text += "\n\n" + t(lang, "out_of_stock")
    rows.append([{"text": "← Varian katalog", "callback_data": f"catalog:{catalog_token(p)}:1"}, {"text": t(lang, "btn_menu_short"), "callback_data": "menu:main"}])
    await send_message(chat_id, text, kb={"inline_keyboard": rows})


# ============ CART ============

async def save_cart(tid, cart):
    await db.bot_users.update_one({"telegram_id": tid}, {"$set": {"cart": cart}})


async def show_cart(chat_id, user):
    lang = user.get("lang", "id")
    cart = norm_cart(user.get("cart"))
    if not cart:
        await send_message(chat_id, t(lang, "cart_empty"), kb={"inline_keyboard": [
            [{"text": t(lang, "btn_products"), "callback_data": "menu:products"}],
            [{"text": t(lang, "btn_main"), "callback_data": "menu:main"}]]})
        return
    lines, total, total_discount, rows = [], 0.0, 0.0, []
    valid_cart = []
    for item in cart:
        p = await db.products.find_one({"_id": item["pid"], "active": True})
        if not p:
            continue
        valid_cart.append(item)
        pricing = await price_for_product(p, user["currency"], item["qty"])
        subtotal = pricing["unit_price"] * item["qty"]
        total += subtotal
        lines.append(f"• {escape(str(p['name']))} ×{item['qty']} — {fmt_amount(subtotal, user['currency'])}")
        if pricing["discount_total"] > 0:
            total_discount += pricing["discount_total"]
            lines.append(f"  🎉 {escape(str(pricing.get('discount_name') or 'Diskon'))}: hemat {fmt_amount(pricing['discount_total'], user['currency'])}")
        rows.append([
            {"text": "➖", "callback_data": f"qtydec:{item['pid']}"},
            {"text": f"{p['name'][:20]} ×{item['qty']}", "callback_data": f"prod:{item['pid']}"},
            {"text": "➕", "callback_data": f"qtyinc:{item['pid']}"},
            {"text": "🗑", "callback_data": f"cartrm:{item['pid']}"},
        ])
        rows.append([
            {"text": "🔢 Masukkan jumlah sendiri", "callback_data": f"qtycustom:{item['pid']}"},
        ])
    if len(valid_cart) != len(cart):
        await save_cart(user["telegram_id"], valid_cart)
    rows.append([{"text": "🎟️ Gunakan Kupon", "callback_data": "coupon:apply"}])
    rows.append([{"text": t(lang, "btn_checkout", total=fmt_amount(total, user["currency"])), "callback_data": "checkout"}])
    rows.append([{"text": t(lang, "btn_clear"), "callback_data": "cartclear"}, {"text": t(lang, "btn_menu_short"), "callback_data": "menu:main"}])
    text = t(lang, "cart_title") + "\n\n" + "\n".join(lines)
    if total_discount:
        text += f"\n\n💸 Total diskon: <b>{fmt_amount(total_discount, user['currency'])}</b>"
    text += "\n\n" + t(lang, "cart_total", total=fmt_amount(total, user["currency"]))
    await send_message(chat_id, text, kb={"inline_keyboard": rows})


async def change_qty(chat_id, user, pid, delta):
    lang = user.get("lang", "id")
    cart = norm_cart(user.get("cart"))
    p = await db.products.find_one({"_id": pid})
    for item in cart:
        if item["pid"] == pid:
            new_qty = item["qty"] + delta
            if new_qty < 1:
                cart = [i for i in cart if i["pid"] != pid]
            elif p and not await has_stock(p, new_qty):
                await send_message(chat_id, t(lang, "qty_max", stock=await stock_label(p, lang)))
                return
            else:
                item["qty"] = new_qty
            break
    await save_cart(user["telegram_id"], cart)
    user["cart"] = cart
    await show_cart(chat_id, user)


async def start_custom_quantity(chat_id, user, pid):
    lang = user.get("lang", "id")
    product = await db.products.find_one({"_id": pid, "active": True})
    if not product:
        await send_message(chat_id, "❌ Product tidak ditemukan atau sudah tidak aktif.", kb=back_kb(lang))
        return

    cart = norm_cart(user.get("cart"))
    if not any(item["pid"] == pid for item in cart):
        await send_message(chat_id, "⚠️ Product tersebut tidak ada di keranjang.", kb={"inline_keyboard": [
            [{"text": "🛒 Kembali ke Keranjang", "callback_data": "menu:cart"}],
            [{"text": "🏠 Menu", "callback_data": "menu:main"}],
        ]})
        return

    current_item = next((item for item in cart if item["pid"] == pid), None)
    current_qty = int(current_item.get("qty", 1)) if current_item else 1
    price = await product_price(product, user["currency"])
    stock = await stock_for(product)
    stock_text = "♾️ Unlimited" if stock is None else f"📦 Tersedia: {int(stock)}"

    await set_state(
        user["telegram_id"],
        "cart_custom_qty",
        {"pid": pid},
    )
    await send_message(
        chat_id,
        f"🔢 <b>Masukkan Jumlah Pembelian</b>\n\n"
        f"📦 Product: <b>{escape(product['name'])}</b>\n"
        f"💰 Harga satuan: <b>{fmt_amount(price, user['currency'])}</b>\n"
        f"🔢 Jumlah saat ini: <b>{current_qty}</b>\n"
        f"{stock_text}\n\n"
        "Silakan kirim <b>angka total pembelian</b> yang diinginkan.\n"
        "Contoh: <code>15</code>\n\n"
        "💡 Jumlah akan langsung diperbarui di keranjang setelah Anda memasukkan angka.",
        kb={"inline_keyboard": [
            [{"text": "❌ Batal", "callback_data": "menu:cart"}],
        ]},
    )


async def handle_custom_quantity(chat_id, user, text):
    lang = user.get("lang", "id")
    data = user.get("state_data") or {}
    pid = str(data.get("pid") or "").strip()

    if not pid:
        await set_state(user["telegram_id"], None)
        await show_cart(chat_id, user)
        return

    if not text.isdigit():
        await send_message(
            chat_id,
            "❗ <b>Input tidak valid.</b>\n\nSilakan masukkan angka bulat saja.\nContoh: <code>15</code>",
            kb={"inline_keyboard": [
                [{"text": "❌ Batal", "callback_data": "menu:cart"}],
            ]},
        )
        return

    qty = int(text)
    if qty < 1:
        await send_message(chat_id, "❗ Jumlah minimal adalah <b>1</b>.", kb={"inline_keyboard": [
            [{"text": "❌ Batal", "callback_data": "menu:cart"}],
        ]})
        return

    if qty > 10000:
        await send_message(
            chat_id,
            "⚠️ Jumlah terlalu besar. Maksimal <b>10.000</b> item per input.",
            kb={"inline_keyboard": [
                [{"text": "❌ Batal", "callback_data": "menu:cart"}],
            ]},
        )
        return

    product = await db.products.find_one({"_id": pid, "active": True})
    if not product:
        await set_state(user["telegram_id"], None)
        await send_message(chat_id, "❌ Product sudah tidak tersedia.", kb={"inline_keyboard": [
            [{"text": "🛒 Keranjang", "callback_data": "menu:cart"}],
        ]})
        return

    stock = await stock_for(product)
    if stock is not None and qty > stock:
        await send_message(
            chat_id,
            f"⚠️ <b>Jumlah melebihi stok.</b>\n\n"
            f"Product: <b>{escape(product['name'])}</b>\n"
            f"📦 Stok tersedia: <b>{int(stock)}</b>\n"
            f"🔢 Anda memasukkan: <b>{qty}</b>\n\n"
            "Silakan masukkan jumlah yang tidak melebihi stok.",
            kb={"inline_keyboard": [
                [{"text": "❌ Batal", "callback_data": "menu:cart"}],
            ]},
        )
        return

    pricing = await price_for_product(product, user["currency"], qty)
    unit_price = pricing["unit_price"]
    total = unit_price * qty

    cart = norm_cart(user.get("cart"))
    updated = False
    for item in cart:
        if item["pid"] == pid:
            item["qty"] = qty
            updated = True
            break
    if not updated:
        cart.append({"pid": pid, "qty": qty})
    await save_cart(user["telegram_id"], cart)
    user["cart"] = cart

    await set_state(
        user["telegram_id"],
        "cart_custom_confirm",
        {"pid": pid, "qty": qty},
    )

    await send_message(
        chat_id,
        "🛒 <b>Konfirmasi Pembelian</b>\n\n"
        f"📦 Anda akan membeli product: <b>{escape(product['name'])}</b>\n"
        f"💰 Harga satuan: <b>{fmt_amount(unit_price, user['currency'])}</b>\n"
        f"🔢 Total pesanan: <b>{qty}</b>\n"
        f"🧮 Perhitungan: <b>{qty} × {fmt_amount(unit_price, user['currency'])}</b>\n"
        f"💵 <b>Total harga: {fmt_amount(total, user['currency'])}</b>\n\n"
        "✅ Silakan klik <b>Bayar</b> untuk melanjutkan proses pembayaran dan pengiriman.",
        kb={"inline_keyboard": [
            [{"text": f"💳 Bayar {fmt_amount(total, user['currency'])}", "callback_data": f"custompay:{pid}:{qty}"}],
            [{"text": "✏️ Ubah Jumlah", "callback_data": f"qtycustom:{pid}"}, {"text": "🛒 Keranjang", "callback_data": "menu:cart"}],
        ]},
    )


async def add_to_cart(chat_id, user, pid):
    lang = user.get("lang", "id")
    p = await db.products.find_one({"_id": pid, "active": True})
    if not p:
        await send_message(chat_id, t(lang, "product_not_found"), kb=back_kb(lang))
        return
    cart = norm_cart(user.get("cart"))
    existing = next((i for i in cart if i["pid"] == pid), None)
    new_qty = (existing["qty"] + 1) if existing else 1
    if not await has_stock(p, new_qty):
        await send_message(chat_id, t(lang, "qty_max", stock=await stock_label(p, lang)), kb=back_kb(lang))
        return
    if existing:
        existing["qty"] = new_qty
    else:
        cart.append({"pid": pid, "qty": 1})
    await save_cart(user["telegram_id"], cart)
    await send_message(chat_id, t(lang, "added_cart"), kb={"inline_keyboard": [
        [{"text": t(lang, "btn_view_cart"), "callback_data": "menu:cart"}],
        [{"text": t(lang, "btn_continue"), "callback_data": "menu:products"}]]})


# ============ CHECKOUT & DELIVERY ============

async def deliver_product(chat_id, p, lang, send_message_fn=None, send_document_fn=None):
    send_message_fn = send_message_fn or send_message
    send_document_fn = send_document_fn or send_document
    try:
        if p["delivery_type"] == "file" and p.get("storage_path"):
            data, _ = await get_object(p["storage_path"])
            result = await send_document_fn(
                chat_id,
                data,
                p.get("original_filename", "produk.bin"),
                caption=f"📦 {p['name']}",
            )
            return bool(result.get("ok"))
        if p["delivery_type"] == "link":
            result = await send_message_fn(
                chat_id,
                t(lang, "deliver_link", name=p["name"], content=p.get("content", "")),
            )
            return bool(result.get("ok"))
        result = await send_message_fn(
            chat_id,
            t(lang, "deliver_license", name=p["name"], content=p.get("content", "")),
        )
        return bool(result.get("ok"))
    except Exception:
        logger.exception("product delivery failed")
        await send_message_fn(chat_id, t(lang, "deliver_fail", name=p["name"]))
        return False


def _normalize_inventory_field_name(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _inventory_field_value(record: dict, aliases: list[str], default="none"):
    if not isinstance(record, dict):
        return default

    normalized = {
        _normalize_inventory_field_name(key): value
        for key, value in record.items()
    }
    for alias in aliases:
        key = _normalize_inventory_field_name(alias)
        if key in normalized:
            value = normalized[key]
            if value is None or str(value).strip() == "":
                return default
            return str(value).strip()
    return default


def _account_values(record: dict):
    return {
        "email": _inventory_field_value(
            record,
            ["email", "email_address", "mail", "emailaddress"],
        ),
        "password": _inventory_field_value(
            record,
            ["password", "pass", "passwd", "pwd"],
        ),
        "recovery": _inventory_field_value(
            record,
            ["recovery", "recovery_email", "recoveryemail", "recovery_mail"],
        ),
        "2fa": _inventory_field_value(
            record,
            ["2fa", "2fa_key", "2fa_secret", "authenticator", "otp_secret", "totp", "totp_secret"],
        ),
    }


def _looks_like_account_record(record: dict):
    if not isinstance(record, dict):
        return False
    keys = {_normalize_inventory_field_name(key) for key in record.keys()}
    aliases = {
        "email", "email_address", "mail", "emailaddress",
        "password", "pass", "passwd", "pwd",
        "recovery", "recovery_email", "recoveryemail", "recovery_mail",
        "2fa", "2fa_key", "2fa_secret", "authenticator", "otp_secret", "totp", "totp_secret",
    }
    return bool(keys & aliases)


def _inventory_record_lines(record: dict, schema: list[str]):
    if not isinstance(record, dict):
        return [str(record)]

    if _looks_like_account_record(record):
        values = _account_values(record)
        return [
            f"email: {values['email']}",
            f"password: {values['password']}",
            f"recovery: {values['recovery']}",
            f"2fa: {values['2fa']}",
        ]

    fields = schema or list(record.keys())
    return [
        f"{field}: {record.get(field, '')}"
        for field in fields
        if str(record.get(field, "")).strip() != ""
    ]


def _account_txt_line(record: dict):
    values = _account_values(record)
    return ":".join([
        values["email"].replace("\n", " ").replace("\r", " "),
        values["password"].replace("\n", " ").replace("\r", " "),
        values["recovery"].replace("\n", " ").replace("\r", " "),
        values["2fa"].replace("\n", " ").replace("\r", " "),
    ])


def _safe_filename_part(value):
    value = re.sub(r"[^\w.-]+", "_", str(value or "").strip(), flags=re.UNICODE)
    return value.strip("._") or "product"


async def deliver_inventory(chat_id, product, records, send_message_fn=None, send_document_fn=None):
    send_message_fn = send_message_fn or send_message
    send_document_fn = send_document_fn or send_document
    if not records:
        return False

    # Binary/file inventory: send the original file instead of rendering
    # base64 or metadata to the buyer.
    file_records = [
        record for record in records
        if isinstance(record, dict) and record.get("__file_data_b64")
    ]
    if file_records:
        all_ok = True
        for index, record in enumerate(file_records, 1):
            try:
                data = base64.b64decode(record["__file_data_b64"], validate=True)
                filename = str(record.get("__file_name") or record.get("file") or f"inventory_{index}.bin")
                result = await send_document_fn(
                    chat_id,
                    data,
                    filename,
                    caption=f"📦 {product['name']}" + (f" — {index}/{len(file_records)}" if len(file_records) > 1 else ""),
                )
                all_ok = all_ok and bool(result.get("ok"))
            except Exception:
                logger.exception("file inventory delivery failed for product %s", product.get("_id"))
                all_ok = False
        if not all_ok:
            await send_message_fn(
                chat_id,
                f"❌ Pengiriman {product['name']} gagal. Silakan hubungi admin."
            )
        return all_ok

    schema = product.get("inventory_schema") or ["value"]
    account_mode = all(_looks_like_account_record(record) for record in records)
    plain_records = [
        _inventory_record_lines(record, schema)
        for record in records
    ]

    if len(records) > 20:
        if account_mode:
            detail_lines = [
                f"{index}. {_account_txt_line(record)}"
                for index, record in enumerate(records, 1)
            ]
            payload_text = (
                "format akun= email:password:recovery:2fa_key\n"
                "note: recovery jika none berarti tidak ada opsi pemulihan yang tertanam di akun\n\n"
                + "\n".join(detail_lines)
            )
        else:
            detail_lines = [
                f"{index}.\n" + "\n".join(lines)
                for index, lines in enumerate(plain_records, 1)
            ]
            payload_text = "\n\n".join(detail_lines)

        filename = (
            f"invoice_{_safe_filename_part(product.get('name'))}_{len(records)}.txt"
        )
        result = await send_document_fn(
            chat_id,
            payload_text.encode("utf-8"),
            filename,
            caption=f"📦 {product['name']} — {len(records)} item",
        )
        return bool(result.get("ok"))

    blocks = []
    for index, record in enumerate(records, 1):
        if _looks_like_account_record(record):
            values = _account_values(record)
            body = "\n".join([
                f"email: <code>{escape(values['email'])}</code>",
                f"password: <code>{escape(values['password'])}</code>",
                f"recovery: <code>{escape(values['recovery'])}</code>",
                f"2fa: <code>{escape(values['2fa'])}</code>",
            ])
        else:
            record_lines = plain_records[index - 1]
            body = "\n".join(
                f"<b>{escape(line.split(':', 1)[0])}:</b> <code>{escape(line.split(':', 1)[1].strip())}</code>"
                if ":" in line else f"<code>{escape(line)}</code>"
                for line in record_lines
            )
        blocks.append(f"<b>#{index}</b>\n{body}")

    result = await send_message_fn(
        chat_id,
        "<b>📦 " + escape(product["name"]) + "</b>\n\n" + "\n\n".join(blocks),
    )
    return bool(result.get("ok"))


def build_invoice_text(order):
    currency = order.get("currency", "IDR")
    lines = [
        f"Invoice {order.get('invoice_id', '-')}",
        f"tanggal transaksi: {order.get('created_at', '-')}",
        f"status: {order.get('status', 'pending')}",
        f"metode pembayaran: {order.get('payment_method', 'balance')}",
        "",
        "Detail pembelian:",
    ]
    for item in order.get("items", []):
        name = str(item.get("name", "Produk"))
        qty = int(item.get("qty") or 0)
        unit = fmt_amount(item.get("unit_price", 0), currency)
        subtotal = fmt_amount(item.get("subtotal", 0), currency)
        lines.append(f"• {name}")
        lines.append(f"  quantity: {qty} akun/item")
        lines.append(f"  harga/unit: {unit}")
        lines.append(f"  subtotal: {subtotal}")
        if float(item.get("discount_total") or 0) > 0:
            lines.append(f"  diskon: {fmt_amount(item.get('discount_total'), currency)}")

    lines.extend([
        "",
        f"total diskon: {fmt_amount(order.get('discount_total', 0), currency)}",
        f"total transaksi: {fmt_amount(order.get('total', 0), currency)}",
        "",
        "terimakasih telah membeli.",
    ])
    return "<pre>" + escape("\n".join(lines)) + "</pre>"


_SERVICE_TASKS = {}

def _service_remaining_text(seconds: int) -> str:
    minutes = max(0, int((seconds + 59) // 60))
    return f"{minutes} menit" if minutes != 1 else "1 menit"


def _service_template(product: dict) -> str:
    return (
        product.get("service_message_template")
        or "Jasa {product_name} sedang dalam antrean, harap tunggu {wait_minutes} untuk dapat menghubungi admin."
    )


async def _run_service_wait(order_id: str, user_tid: int, chat_id: int, product: dict, lang: str, ready_at: str, message_id: int | None = None):
    task_key = f"{order_id}:{product['_id']}"
    try:
        ready = datetime.fromisoformat(ready_at)
        while True:
            remaining = (ready - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                break
            await asyncio.sleep(min(60, max(1, remaining)))
            if message_id:
                left = (ready - datetime.now(timezone.utc)).total_seconds()
                if left > 0:
                    try:
                        await tg_edit_message(
                            chat_id,
                            message_id,
                            f"⏳ <b>{escape(product['name'])}</b> masih dalam antrean.\nWaktu tersisa: <b>{_service_remaining_text(int(left))}</b>.",
                            kb={"inline_keyboard": [[{"text": "🔒 Hubungi Admin", "callback_data": f"service:wait:{order_id}"}]]},
                        )
                    except Exception:
                        logger.exception("Gagal memperbarui countdown jasa %s", order_id)

        order = await db.purchases.find_one({"_id": order_id, "user_tid": user_tid})
        if not order or order.get("status") not in {"service_waiting", "paid"}:
            return

        admin_settings = await get_settings()
        admin_id = str(admin_settings.get("admin_telegram_id") or "").strip()
        admin_kb = None
        if admin_id:
            admin_kb = {"inline_keyboard": [[{"text": "💬 Hubungi Customer", "url": f"tg://user?id={user_tid}"}]]}

        try:
            await notify_admin(
                f"🛎️ <b>Jasa siap dihubungi</b>\n"
                f"Produk: <b>{escape(product['name'])}</b>\n"
                f"Order: <code>{escape(str(order.get('invoice_id', order_id)))}</code>\n"
                f"Customer ID: <code>{user_tid}</code>",
                kb=admin_kb,
            )
        except Exception:
            logger.exception("Notifikasi admin jasa gagal untuk order %s", order_id)

        if message_id:
            try:
                await tg_edit_message(
                    chat_id,
                    message_id,
                    f"✅ <b>{escape(product['name'])}</b> sudah selesai antre.\nSilakan hubungi admin untuk melanjutkan.",
                    kb={"inline_keyboard": [[{"text": "💬 Chat Admin", "url": f"tg://user?id={admin_id}"}]]} if admin_id else None,
                )
            except Exception:
                logger.exception("Gagal membuka tombol admin untuk order %s", order_id)

        await db.purchases.update_one(
            {"_id": order_id, "status": {"$in": ["paid", "service_waiting"]}},
            {"$inc": {"service_pending_count": -1}},
        )
        fresh = await db.purchases.find_one({"_id": order_id})
        if fresh and int(fresh.get("service_pending_count") or 0) <= 0:
            await db.purchases.update_one(
                {"_id": order_id, "status": "service_waiting"},
                {"$set": {"status": "delivered", "delivered_at": now_iso(), "delivery_error": None}},
            )
            latest = await db.purchases.find_one({"_id": order_id})
            if latest and latest.get("status") == "delivered":
                if latest.get("customer_email") or latest.get("customer_id"):
                    try:
                        from storefront_routes import send_order_completion_email
                        await send_order_completion_email(order_id)
                    except Exception:
                        logger.exception("Order completion email failed for %s", order_id)
                u = await db.bot_users.find_one({"telegram_id": user_tid})
                if u:
                    await send_message(
                        chat_id,
                        t(
                            u.get("lang") or lang,
                            "delivered_all",
                            balance=fmt_amount(
                                u.get(CUR_FIELD[latest.get("currency", "IDR")], 0),
                                latest.get("currency", "IDR"),
                            ),
                        ),
                        kb=back_kb(u.get("lang") or lang),
                    )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Service wait failed for order %s product %s", order_id, product.get("_id"))
    finally:
        _SERVICE_TASKS.pop(task_key, None)


async def queue_service_delivery(chat_id: int, user: dict, product: dict, order: dict, lang: str):
    wait_minutes = int(product.get("service_wait_minutes") or 5)
    ready_at = (datetime.now(timezone.utc) + timedelta(minutes=wait_minutes)).isoformat()
    template = _service_template(product)
    try:
        text = template.format(
            product_name=escape(str(product.get("name") or "Produk Jasa")),
            wait_minutes=wait_minutes,
        )
    except Exception:
        text = (
            f"Jasa <b>{escape(str(product.get('name') or 'Produk Jasa'))}</b> sedang dalam antrean, "
            f"harap tunggu <b>{wait_minutes} menit</b> untuk dapat menghubungi admin."
        )
    text = f"⏳ {text}\n\nWaktu tersisa: <b>{wait_minutes} menit</b>."
    result = await send_message(
        chat_id,
        text,
        kb={"inline_keyboard": [[{"text": "🔒 Hubungi Admin", "callback_data": f"service:wait:{order['_id']}"}]]},
    )
    message_id = ((result or {}).get("result") or {}).get("message_id")
    await db.purchases.update_one(
        {"_id": order["_id"]},
        {
            "$set": {
                "status": "service_waiting",
                "service_waiting": True,
                "service_ready_at": ready_at,
                "service_message_id": message_id,
            },
            "$inc": {"service_pending_count": 1},
        },
    )
    task_key = f"{order['_id']}:{product['_id']}"
    _SERVICE_TASKS[task_key] = asyncio.create_task(
        _run_service_wait(
            order["_id"],
            user["telegram_id"],
            chat_id,
            product,
            lang,
            ready_at,
            message_id,
        )
    )


async def resume_service_waiters():
    orders = await db.purchases.find({"status": "service_waiting", "service_ready_at": {"$exists": True}}).to_list(200)
    for order in orders:
        for item in order.get("items", []):
            if item.get("delivery_type") != "service":
                continue
            product = await db.products.find_one({"_id": item.get("product_id")})
            if not product:
                continue
            task_key = f"{order['_id']}:{product['_id']}"
            if task_key in _SERVICE_TASKS:
                continue
            _SERVICE_TASKS[task_key] = asyncio.create_task(
                _run_service_wait(
                    order["_id"],
                    order["user_tid"],
                    order["user_tid"],
                    product,
                    (await user_lang(order["user_tid"])),
                    order.get("service_ready_at") or now_iso(),
                    order.get("service_message_id"),
                )
            )


async def _do_checkout(chat_id, user, cart_items, preserve_cart=False, order_metadata=None):
    if user.get("telegram_id") and not user.get("customer_id"):
        linked_customer = await db.store_customers.find_one(
            {"telegram_id": user["telegram_id"]}, {"_id": 1, "email": 1}
        )
        if linked_customer:
            user = {**user, "customer_id": linked_customer["_id"], "email": linked_customer.get("email")}
    lang = user.get("lang", "id")

    coupon_code = str(user.get("pending_coupon") or "").strip() or None
    result = await execute_checkout(user, cart_items, preserve_cart=preserve_cart, coupon_code=coupon_code,
                                   order_metadata=order_metadata)
    if not result["ok"]:
        if result["error"] == "minimum_qty":
            p = result["product"]
            message = f"Minimum pembelian {result['minimum_qty']} pcs untuk {escape(p['name'])}."
            await send_message(chat_id, message, kb=back_kb(lang))
            return result
        if result["error"] == "stock":
            p = result["product"]
            await send_message(
                chat_id,
                t(
                    lang,
                    "stock_insufficient",
                    name=p["name"],
                    stock=result["stock"],
                ),
                kb=back_kb(lang),
            )
            return result

        if result["error"] == "empty":
            await send_message(chat_id, t(lang, "no_valid_products"), kb=back_kb(lang))
            return result

        if result["error"] == "checkout" and "Saldo" in result.get("message", ""):
            ptotal = 0.0
            for item in cart_items:
                p = await db.products.find_one({"_id": item["pid"], "active": True})
                if p:
                    qty = max(1, int(item.get("qty", 1)))
                    pricing = await price_for_product(p, user["currency"], qty)
                    ptotal += pricing["unit_price"] * qty
            balance = float(user.get(CUR_FIELD[user["currency"]], 0))
            await send_message(
                chat_id,
                t(
                    lang,
                    "insufficient",
                    total=fmt_amount(ptotal, user["currency"]),
                    balance=fmt_amount(balance, user["currency"]),
                    short=fmt_amount(max(0, ptotal - balance), user["currency"]),
                ),
                kb={
                    "inline_keyboard": [
                        [{"text": t(lang, "btn_deposit_now"), "callback_data": "menu:deposit"}],
                        [{"text": t(lang, "btn_main"), "callback_data": "menu:main"}],
                    ]
                },
            )
            return result

        await send_message(chat_id, t(lang, "checkout_failed"), kb=back_kb(lang))
        return result

    order = result["order"]
    if coupon_code:
        await db.bot_users.update_one({"telegram_id": user["telegram_id"]}, {"$unset": {"pending_coupon": ""}})
    await send_message(chat_id, build_invoice_text(order))
    await send_message(
        chat_id,
        t(lang, "pay_success", total=fmt_amount(order["total"], order["currency"])),
    )

    all_delivered = True
    service_count = 0
    allocation_by_product = {
        item["product_id"]: item
        for item in result.get("allocations", [])
    }

    for item in result["items"]:
        product = item["product"]
        qty = item["qty"]

        if product.get("product_kind") == "digital" or product.get("delivery_type") == "inventory" or product.get("inventory_enabled"):
            allocation = allocation_by_product.get(product["_id"])
            inventory_items = allocation.get("items", []) if allocation else []
            ok = await deliver_inventory(
                chat_id,
                product,
                decrypt_items(inventory_items),
            )
            all_delivered = all_delivered and ok
        elif product.get("product_kind") == "service" or product.get("delivery_type") == "service":
            service_count += 1
            await queue_service_delivery(chat_id, user, product, order, lang)
        else:
            ok = True
            for _ in range(qty):
                one = await deliver_product(chat_id, product, lang)
                ok = ok and one
            all_delivered = all_delivered and ok

    if service_count:
        if not all_delivered:
            await db.purchases.update_one(
                {"_id": order["_id"]},
                {"$set": {"status": "delivery_failed", "delivery_error": "Satu atau lebih produk gagal dikirim."}},
            )
            await send_message(
                chat_id,
                t(lang, "delivery_attention", invoice=order["invoice_id"]),
                kb=back_kb(lang),
            )
        sale = {**order, "status": "service_waiting" if all_delivered else "delivery_failed"}
        for notify, args in ((notify_transaction_admin, (sale, user_label(user))),
                             (notify_transaction_channel, (sale,))):
            try:
                await notify(*args)
            except Exception:
                logger.exception("Central service sale notification failed")
        return {**result, "ok": all_delivered, "status": "service_waiting" if all_delivered else "delivery_failed"}

    final_status = "delivered" if all_delivered else "delivery_failed"
    await db.purchases.update_one(
        {"_id": order["_id"]},
        {
            "$set": {
                "status": final_status,
                "delivered_at": now_iso() if all_delivered else None,
                "delivery_error": None if all_delivered else "Satu atau lebih produk gagal dikirim.",
            }
        },
    )

    if all_delivered:
        if order.get("customer_email") or order.get("customer_id"):
            try:
                from storefront_routes import send_order_completion_email
                await send_order_completion_email(order["_id"])
            except Exception:
                logger.exception("Order completion email failed for %s", order["_id"])
        await send_message(
            chat_id,
            t(
                lang,
                "delivered_all",
                balance=fmt_amount(result["remaining_balance"], order["currency"]),
            ),
            kb=back_kb(lang),
        )
    else:
        await send_message(
            chat_id,
            t(lang, "delivery_attention", invoice=order["invoice_id"]),
            kb=back_kb(lang),
        )

    sale = {**order, "status": final_status}
    for notify, args in ((notify_transaction_admin, (sale, user_label(user))),
                         (notify_transaction_channel, (sale,))):
        try:
            await notify(*args)
        except Exception:
            logger.exception("Central sale notification failed")
    return {**result, "ok": all_delivered, "status": final_status}


async def do_checkout(chat_id, user, cart_items, preserve_cart=False, order_metadata=None):
    lock = _checkout_lock(user["telegram_id"])
    if lock.locked():
        await send_message(chat_id, t(user.get("lang", "id"), "checkout_in_progress"), kb=back_kb(user.get("lang", "id")))
        return {"ok": False, "error": "busy", "message": "Checkout sedang diproses."}

    async with lock:
        return await _do_checkout(chat_id, user, cart_items, preserve_cart=preserve_cart,
                                  order_metadata=order_metadata)


async def show_payment_methods(chat_id, user, cart_items, preserve_cart=False):
    lang = user.get("lang", "id")
    if not cart_items:
        await send_message(chat_id, "🛒 Keranjang kosong.", kb=back_kb(lang))
        return
    qr_available = await qris_ready()
    qr_total = None
    if qr_available:
        quote = await quote_items(user, cart_items,
            user.get("pending_coupon") if user.get("currency") == "IDR" else None)
        if quote.get("error"):
            await send_message(chat_id, f"⚠️ {escape(quote['error'])}", kb=back_kb(lang))
            return
        qr_total = quote["total"]
    if user.get("currency") == "IDR" and qr_total is not None:
        total = qr_total
    else:
        total = 0
        for item in cart_items:
            product = await db.products.find_one({"_id": item["pid"], "active": True})
            if not product:
                await send_message(chat_id, "⚠️ Produk sudah tidak tersedia.", kb=back_kb(lang))
                return
            qty = max(1, int(item.get("qty") or 1))
            stock = await stock_for(product)
            if stock is not None and stock < qty:
                await send_message(chat_id, f"⚠️ Stok {escape(product['name'])} berubah. Tersedia {stock}.", kb=back_kb(lang))
                return
            total += (await price_for_product(product, user["currency"], qty))["unit_price"] * qty
    await set_state(user["telegram_id"], "checkout_method", {
        "cart_items": cart_items, "preserve_cart": bool(preserve_cart),
    })
    rows = [[{"text": f"💰 Saldo — {fmt_amount(total, user['currency'])}", "callback_data": "pay:balance"}]]
    if qr_available:
        rows.append([{"text": f"📱 QRIS — {fmt_amount(qr_total, 'IDR')}", "callback_data": "pay:qris"}])
    rows.append([{"text": "⬅️ Kembali", "callback_data": "menu:cart"}])
    await send_message(chat_id,
        "🧾 <b>Pilih Metode Pembayaran</b>\n\n"
        f"Total produk: <b>{fmt_amount(total, user['currency'])}</b>\n"
        + ("QRIS akan menambahkan biaya admin dan kode unik; jumlah akhir terlihat pada QR. "
           "Stok ditahan 10 menit saat QR dibuat.\n\n" if qr_available else "\n")
        + ("Kupon USD hanya berlaku untuk pembayaran saldo USD.\n\n"
           if qr_available and user.get("currency") == "USD" and user.get("pending_coupon") else "")
        + "Pilih metode pembayaran:", kb={"inline_keyboard": rows})


async def handle_payment_method(chat_id, user, method):
    if user.get("state") != "checkout_method":
        await send_message(chat_id, "⚠️ Pilihan pembayaran sudah tidak aktif. Mulai checkout lagi.",
                           kb=back_kb(user.get("lang", "id")))
        return
    data = user.get("state_data") or {}
    cart_items = norm_cart(data.get("cart_items"))
    preserve_cart = bool(data.get("preserve_cart"))
    if not cart_items:
        await set_state(user["telegram_id"], None)
        await send_message(chat_id, "🛒 Keranjang kosong.", kb=back_kb(user.get("lang", "id")))
        return
    claimed = await db.bot_users.update_one(
        {"telegram_id": user["telegram_id"], "state": "checkout_method"},
        {"$set": {"state": "checkout_processing"}},
    )
    if claimed.modified_count != 1:
        await send_message(chat_id, "⏳ Checkout ini sudah diproses. Lihat riwayat transaksi.",
                           kb=back_kb(user.get("lang", "id")))
        return
    if method == "balance":
        await set_state(user["telegram_id"], None)
        await do_checkout(chat_id, user, cart_items, preserve_cart=preserve_cart)
        return
    if method != "qris":
        await set_state(user["telegram_id"], "checkout_method", data)
        return
    lock = _checkout_lock(user["telegram_id"])
    if lock.locked():
        await send_message(chat_id, "⏳ Checkout sedang diproses.")
        await set_state(user["telegram_id"], "checkout_method", data)
        return
    async with lock:
        try:
            result = await create_qris_order(user, cart_items,
                coupon_code=user.get("pending_coupon") if user.get("currency") == "IDR" else None,
                preserve_cart=preserve_cart)
            if result.get("error"):
                await set_state(user["telegram_id"], "checkout_method", data)
                await send_message(chat_id, f"⚠️ {escape(result['error'])}",
                    kb=back_kb(user.get("lang", "id")))
                return
            order, payment = result["order"], result["payment"]
            expiry_wib = datetime.fromisoformat(order["expires_at"]).astimezone(
                ZoneInfo("Asia/Jakarta")).strftime("%d %b %Y %H:%M WIB")
            expires_in_minutes = int(order.get("expires_in_minutes") or 5)
            caption = ("🧾 <b>QRIS All Payment</b>\n\n"
                f"Invoice: <code>{escape(order['invoice_id'])}</code>\n"
                f"Total produk: <b>{fmt_amount(order['total'], 'IDR')}</b>\n"
                f"Biaya admin: {fmt_amount(payment['admin_fee'], 'IDR')}\n"
                f"Kode unik: {fmt_amount(payment['platform_code'], 'IDR')}\n"
                f"<b>Bayar tepat {fmt_amount(payment['payment_amount'], 'IDR')}</b>\n"
                f"Berlaku sampai: {expiry_wib}\n"
                f"⏳ QR hanya berlaku {expires_in_minutes} menit.\n\n"
                "Cara bayar: pindai QR ini melalui aplikasi e-wallet atau mobile banking yang mendukung QRIS.\n"
                "Setelah pembayaran terverifikasi, produk dikirim otomatis. "
                "Ini pembayaran invoice, bukan deposit.")
            sent_qr = await send_photo_bytes(chat_id, result["image"], "qris-all-payment.jpg",
                caption=caption, kb={"inline_keyboard": [
                    [{"text": "🧾 Riwayat", "callback_data": "menu:history"}],
                ]})
            if not sent_qr.get("ok"):
                raise RuntimeError(f"Telegram menolak foto QRIS: {sent_qr.get('description', 'unknown')}")
            qr_message_id = (sent_qr.get("result") or {}).get("message_id")
            if qr_message_id:
                await db.purchases.update_one({"_id": order["_id"]}, {"$set": {"qr_message_id": qr_message_id}})
                await db.gopay_payments.update_one({"_id": payment["_id"]}, {"$set": {"qr_message_id": qr_message_id}})
            await set_state(user["telegram_id"], None)
        except ValueError as exc:
            await set_state(user["telegram_id"], "checkout_method", data)
            await send_message(chat_id, f"⚠️ {escape(str(exc))}",
                               kb=back_kb(user.get("lang", "id")))
        except Exception:
            logger.exception("QRIS checkout creation failed")
            await set_state(user["telegram_id"], "checkout_method", data)
            await send_message(chat_id, "⚠️ QRIS gagal dibuat. Silakan coba lagi atau pilih saldo.",
                               kb=back_kb(user.get("lang", "id")))


# ============ DEPOSIT ============

async def ensure_join_gate(chat_id, user, force_refresh=False):
    joined, missing = await check_user_membership(user["telegram_id"], force_refresh=force_refresh)
    if joined:
        return True
    lang = user.get("lang", "id")
    await send_message(
        chat_id,
        "📢 <b>Akses bot membutuhkan join channel terlebih dahulu.</b>\n\n"
        "Silakan join semua channel di bawah, lalu tekan tombol <b>Saya sudah join</b>.",
        kb=build_gate_keyboard(missing),
    )
    return False


async def show_deposit_menu(chat_id, user):
    lang = user.get("lang", "id")
    s = await get_settings()

    if user["currency"] == "USD":
        kb = {"inline_keyboard": [
            [{"text": "💎 USDT", "callback_data": "depcoin:USDT"}, {"text": "🔵 USDC", "callback_data": "depcoin:USDC"}],
            [{"text": t(lang, "btn_main"), "callback_data": "menu:main"}],
        ]}
        await send_message(
            chat_id,
            t(lang, "dep_usd_title", min=float(s.get("min_deposit_usd", 15))),
            kb=kb,
        )
        return

    import os
    qris_ready = bool(s.get("qris_enabled", False)) and os.environ.get("GOPAY_ENABLED", "").lower() in {"1", "true", "yes"}
    bank_ready = bool(s.get("bank_enabled", False)) and bool(s.get("bank_account_number"))

    if qris_ready and bank_ready:
        await send_message(chat_id, t(lang, "dep_idr_method_title"), kb={
            "inline_keyboard": [
                [{"text": t(lang, "btn_gopay_qris"), "callback_data": "depmethod:qris"}],
                [{"text": t(lang, "btn_bank_transfer"), "callback_data": "depmethod:bank"}],
                [{"text": t(lang, "btn_main"), "callback_data": "menu:main"}],
            ]
        })
        return

    if qris_ready:
        await start_idr_deposit(chat_id, user, "qris")
        return

    if bank_ready:
        await start_idr_deposit(chat_id, user, "bank")
        return

    await send_message(chat_id, t(lang, "dep_gateway_offline"), kb=back_kb(lang))


async def start_idr_deposit(chat_id, user, method):
    lang = user.get("lang", "id")
    s = await get_settings()
    min_idr = float(s.get("min_deposit_idr", 50000))
    import os

    if method == "qris":
        qris_ready = bool(s.get("qris_enabled", False)) and os.environ.get("GOPAY_ENABLED", "").lower() in {"1", "true", "yes"}
        if not qris_ready:
            await send_message(chat_id, t(lang, "dep_gateway_offline"), kb=back_kb(lang))
            return
        await set_state(user["telegram_id"], "dep_idr_amount", {"method": "qris"})
        prompt = await send_message(
            chat_id,
            t(lang, "dep_idr_gopay_title", min=fmt_amount(min_idr, "IDR")),
            kb=cancel_kb(lang),
        )
        if prompt.get("message_id"):
            await db.bot_users.update_one(
                {"telegram_id": user["telegram_id"]},
                {"$set": {"state_data.prompt_message_id": prompt["message_id"]}},
            )
        return

    if method == "bank":
        if not s.get("bank_enabled") or not s.get("bank_account_number"):
            await send_message(chat_id, t(lang, "dep_no_bank"), kb=back_kb(lang))
            return
        await set_state(user["telegram_id"], "dep_idr_amount", {"method": "bank"})
        await send_message(
            chat_id,
            t(
                lang,
                "dep_idr_title",
                bank=s.get("bank_name", ""),
                account=s.get("bank_account_number", ""),
                holder=s.get("bank_account_holder", ""),
                min=fmt_amount(min_idr, "IDR"),
            ),
            kb=cancel_kb(lang),
        )
        return

    await send_message(chat_id, t(lang, "dep_gateway_offline"), kb=back_kb(lang))

async def show_network_selection(chat_id, user, coin):
    lang = user.get("lang", "id")
    kb = {"inline_keyboard": [
        [{"text": "◎ Solana", "callback_data": f"depnet:{coin}:SOL"}, {"text": "🟣 Polygon", "callback_data": f"depnet:{coin}:POL"}],
        [{"text": "🟡 BNB (BEP-20)", "callback_data": f"depnet:{coin}:BNB"}, {"text": "🔺 Avalanche", "callback_data": f"depnet:{coin}:AVAX"}],
        [{"text": t(lang, "btn_back"), "callback_data": "menu:deposit"}],
    ]}
    await send_message(chat_id, t(lang, "choose_network", coin=coin), kb=kb)


async def show_deposit_address(chat_id, user, coin, network):
    lang = user.get("lang", "id")
    s = await get_settings()
    address = (s.get("crypto_addresses") or {}).get(f"{coin}_{network}", "")
    if not address:
        await send_message(chat_id, t(lang, "dep_no_address", coin=coin, network=NET_LABELS[network]),
            kb={"inline_keyboard": [[{"text": t(lang, "btn_other_network"), "callback_data": f"depcoin:{coin}"}],
                                     [{"text": t(lang, "btn_main"), "callback_data": "menu:main"}]]})
        return
    await set_state(user["telegram_id"], "dep_usd_amount", {"coin": coin, "network": network})
    await send_message(chat_id,
        t(lang, "dep_address", coin=coin, network=NET_LABELS[network], address=address, min=float(s.get("min_deposit_usd", 15))),
        kb=cancel_kb(lang))


async def handle_dep_usd_amount(chat_id, user, text):
    lang = user.get("lang", "id")
    s = await get_settings()
    min_usd = float(s.get("min_deposit_usd", 15))
    try:
        amount = float(text.strip().replace("$", "").replace(",", ""))
    except ValueError:
        await send_message(chat_id, t(lang, "invalid_amount"), kb=cancel_kb(lang))
        return
    if amount < min_usd:
        await send_message(chat_id, t(lang, "min_deposit", min=f"${min_usd:,.2f}"), kb=cancel_kb(lang))
        return
    if not math.isfinite(amount) or amount > float(s.get("max_deposit_usd", 100000)):
        await send_message(chat_id, t(lang, "invalid_amount"), kb=cancel_kb(lang))
        return
    data = user.get("state_data", {})
    data["amount"] = amount
    await set_state(user["telegram_id"], "dep_usd_wallet", data)
    await send_message(chat_id, t(lang, "wallet_prompt", network=NET_LABELS.get(data.get("network"), data.get("network", ""))), kb=cancel_kb(lang))


def valid_sender_wallet(network, wallet):
    wallet = wallet.strip()
    if network in {"POL", "BNB", "AVAX"}:
        return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", wallet))
    return 32 <= len(wallet) <= 44 and bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]+", wallet))


async def handle_dep_usd_wallet(chat_id, user, text):
    lang = user.get("lang", "id")
    data = user.get("state_data", {})
    network = data.get("network")
    wallet = text.strip()

    if not valid_sender_wallet(network, wallet):
        await send_message(chat_id, t(lang, "wallet_invalid"), kb=cancel_kb(lang))
        return

    data["sender_wallet"] = wallet
    await set_state(user["telegram_id"], "dep_usd_proof", data)
    await send_message(chat_id, t(lang, "amount_set_usd", amount=data.get("amount", 0)), kb=cancel_kb(lang))


async def handle_dep_idr_amount(chat_id, user, text):
    lang = user.get("lang", "id")
    s = await get_settings()
    data = user.get("state_data", {})
    method = data.get("method") or "bank"
    min_idr = float(s.get("min_deposit_idr", 50000))
    try:
        amount = float(
            text.strip()
            .replace("Rp", "")
            .replace(".", "")
            .replace(",", "")
            .replace(" ", "")
        )
    except ValueError:
        await send_message(chat_id, t(lang, "invalid_amount"), kb=cancel_kb(lang))
        return

    if not math.isfinite(amount) or amount > float(s.get("max_deposit_idr", 100000000)):
        await send_message(chat_id, t(lang, "invalid_amount"), kb=cancel_kb(lang))
        return

    if amount < min_idr:
        await send_message(
            chat_id,
            t(lang, "min_deposit", min=fmt_amount(min_idr, "IDR")),
            kb=cancel_kb(lang),
        )
        return

    import os
    qris_ready = bool(s.get("qris_enabled", False)) and os.environ.get("GOPAY_ENABLED", "").lower() in {"1", "true", "yes"}
    bank_ready = bool(s.get("bank_enabled", False)) and bool(s.get("bank_account_number"))

    if method == "qris":
        if not qris_ready:
            await set_state(user["telegram_id"], None)
            await send_message(chat_id, t(lang, "dep_gateway_offline"), kb=back_kb(lang))
            return
        old_prompt_id = data.get("prompt_message_id")
        if old_prompt_id:
            try:
                await delete_message(chat_id, old_prompt_id)
            except Exception:
                pass
        admin_fee = max(1, int(round(amount * 0.007)))
        platform_code = secrets.randbelow(900) + 100
        total_payment = int(amount + admin_fee + platform_code)
        await set_state(
            user["telegram_id"],
            "dep_idr_confirm",
            {
                "method": "qris",
                "amount": int(amount),
                "admin_fee": admin_fee,
                "platform_code": platform_code,
                "total_payment": total_payment,
            },
        )
        await send_message(
            chat_id,
            t(
                lang,
                "gopay_deposit_confirm",
                amount=fmt_amount(amount, "IDR"),
                fee=fmt_amount(admin_fee, "IDR"),
                platform_code=platform_code,
                total=fmt_amount(total_payment, "IDR"),
            ),
            kb={
                "inline_keyboard": [
                    [{"text": t(lang, "btn_deposit_agree"), "callback_data": "gopay:yes"}],
                    [{"text": t(lang, "btn_deposit_cancel"), "callback_data": "gopay:no"}],
                ]
            },
        )
        return

    if not bank_ready:
        await set_state(user["telegram_id"], None)
        await send_message(chat_id, t(lang, "dep_gateway_offline"), kb=back_kb(lang))
        return

    await set_state(user["telegram_id"], "dep_idr_proof", {"method": "bank", "amount": amount})
    await send_message(
        chat_id,
        t(lang, "amount_set_idr", amount=fmt_amount(amount, "IDR")),
        kb=cancel_kb(lang),
    )

async def confirm_gopay_deposit(chat_id, user):
    lang = user.get("lang", "id")
    data = user.get("state_data", {})
    s = await get_settings()
    import os
    qris_ready = bool(s.get("qris_enabled", False)) and os.environ.get("GOPAY_ENABLED", "").lower() in {"1", "true", "yes"}
    if not qris_ready:
        await set_state(user["telegram_id"], None)
        await send_message(chat_id, t(lang, "dep_gateway_offline"), kb=back_kb(lang))
        return
    amount = int(data.get("amount") or 0)
    admin_fee = int(data.get("admin_fee") or 0)
    platform_code = int(data.get("platform_code") or 0)
    if amount < 1 or admin_fee < 1 or not 100 <= platform_code <= 999:
        await set_state(user["telegram_id"], None)
        await send_message(chat_id, t(lang, "gopay_unavailable"), kb=back_kb(lang))
        return

    try:
        payment = await create_gopay_payment(user, amount, platform_code=platform_code)
        await set_state(user["telegram_id"], None)
        caption = t(
            lang,
            "gopay_qr_created",
            amount=fmt_amount(amount, "IDR"),
            fee=fmt_amount(payment["admin_fee"], "IDR"),
            platform_code=payment["platform_code"],
            payment_amount=fmt_amount(payment["payment_amount"], "IDR"),
            expires=payment.get("expires_in_minutes", 5),
        )
        sent_qr = await send_photo_bytes(
            chat_id,
            payment["image"],
            "qris-all-payment.jpg",
            caption=caption,
            kb=back_kb(lang),
        )
        if sent_qr.get("ok"):
            qr_message_id = (sent_qr.get("result") or {}).get("message_id")
            if qr_message_id:
                await db.gopay_payments.update_one({"_id": payment["payment_id"]}, {"$set": {"qr_message_id": qr_message_id}})
                await db.deposits.update_one({"_id": payment["deposit"]["_id"]}, {"$set": {"qr_message_id": qr_message_id}})
    except Exception:
        logger.exception("GoPay QR creation failed")
        await set_state(user["telegram_id"], None)
        await send_message(chat_id, t(lang, "gopay_unavailable"), kb=back_kb(lang))

async def create_pending_deposit(user, data, tx_hash=None, proof_file_id=None, credited_amount=None, auto_verified=False):
    dep = {
        "_id": str(uuid.uuid4()), "user_tid": user["telegram_id"], "username": user.get("username", ""),
        "first_name": user.get("first_name", ""),
        "method": "crypto" if data.get("coin") else "bank",
        "coin": data.get("coin"), "network": data.get("network"),
        "currency": "USD" if data.get("coin") else "IDR",
        "amount": data["amount"], "credited_amount": credited_amount,
        "sender_wallet": data.get("sender_wallet"),
        "tx_hash": tx_hash, "proof_file_id": proof_file_id,
        "status": "pending", "auto_verified": auto_verified, "note": "",
        "created_at": now_iso(), "decided_at": None,
    }
    await db.deposits.insert_one(dep)
    return dep


def admin_decision_kb(dep_id):
    return {"inline_keyboard": [[
        {"text": "✅ Setujui", "callback_data": f"adm:app:{dep_id}"},
        {"text": "❌ Tolak", "callback_data": f"adm:rej:{dep_id}"},
    ]]}


async def handle_usd_proof(chat_id, user, message):
    lang = user.get("lang", "id")
    data = user.get("state_data", {})
    coin, network, amount = data.get("coin"), data.get("network"), data.get("amount")
    sender_wallet = data.get("sender_wallet")
    s = await get_settings()
    address = (s.get("crypto_addresses") or {}).get(f"{coin}_{network}", "")
    text = message.get("text", "")
    photo = message.get("photo")

    if photo:
        file_id = photo[-1]["file_id"]
        dep = await create_pending_deposit(user, data, proof_file_id=file_id)
        await set_state(user["telegram_id"], None)
        await send_message(chat_id, t(lang, "proof_received"), kb=back_kb(lang))
        await notify_admin(
            f"💰 <b>Deposit Baru — Perlu Verifikasi</b>\n\nDari: {user_label(user)}\n"
            f"Metode: {coin} / {NET_LABELS[network]}\nJumlah klaim: {amount:,.2f}\nBukti: screenshot 👆",
            kb=admin_decision_kb(dep["_id"]), photo_file_id=file_id)
        return

    tx_hash = text.strip()
    if not sender_wallet or not valid_sender_wallet(network, sender_wallet):
        await send_message(chat_id, t(lang, "wallet_invalid"), kb=cancel_kb(lang))
        return
    if not looks_like_tx_hash(tx_hash, network):
        await send_message(chat_id, t(lang, "invalid_txhash"), kb=cancel_kb(lang))
        return

    existing = await db.deposits.find_one({"tx_hash": tx_hash})
    if existing:
        await send_message(chat_id, t(lang, "tx_used"), kb=back_kb(lang))
        await set_state(user["telegram_id"], None)
        return

    await send_message(chat_id, t(lang, "checking"))
    verified, onchain_amount, reason = await verify_tx(
        network,
        coin,
        address,
        tx_hash,
        expected_sender=sender_wallet,
    )
    min_usd = float(s.get("min_deposit_usd", 15))

    if verified and onchain_amount >= min_usd:
        dep = await create_pending_deposit(
            user,
            data,
            tx_hash=tx_hash,
            credited_amount=onchain_amount,
            auto_verified=True,
        )
        await credit_deposit(dep, note="Verifikasi on-chain otomatis")
        fresh = await db.bot_users.find_one({"telegram_id": user["telegram_id"]})
        new_bal = float((fresh or {}).get("balance_usd", 0))
        await set_state(user["telegram_id"], None)
        await send_message(
            chat_id,
            t(
                lang,
                "auto_ok",
                coin=coin,
                network=NET_LABELS[network],
                amount=onchain_amount,
                balance=new_bal,
            ),
            kb=back_kb(lang),
        )
        await notify_admin(
            f"✅ <b>Deposit Otomatis Terverifikasi</b>\n\nDari: {user_label(user)}\n"
            f"Koin: {coin} / {NET_LABELS[network]}\nWallet: <code>{sender_wallet}</code>\n"
            f"Jumlah on-chain: {onchain_amount:,.2f}\nTX: <code>{tx_hash}</code>",
            kb={"inline_keyboard": [[{"text": "🚫 Batalkan Deposit Ini", "callback_data": f"adm:cxl:{dep['_id']}"}]]})
    else:
        dep = await create_pending_deposit(user, data, tx_hash=tx_hash)
        await set_state(user["telegram_id"], None)
        if verified:
            why = f"Jumlah on-chain ({onchain_amount:,.2f}) di bawah minimum"
        else:
            why = reason or "Tidak dapat diverifikasi"
        await send_message(chat_id, t(lang, "pending_manual", reason=why), kb=back_kb(lang))
        await notify_admin(
            f"💰 <b>Deposit Baru — Perlu Verifikasi Manual</b>\n\nDari: {user_label(user)}\n"
            f"Koin: {coin} / {NET_LABELS[network]}\nWallet: <code>{sender_wallet}</code>\n"
            f"Jumlah klaim: {amount:,.2f}\nTX: <code>{tx_hash}</code>\n⚠️ Auto-verify gagal: {why}",
            kb=admin_decision_kb(dep["_id"]))



async def handle_idr_proof(chat_id, user, message):
    lang = user.get("lang", "id")
    data = user.get("state_data", {})
    s = await get_settings()
    if not s.get("bank_enabled") or not s.get("bank_account_number"):
        await set_state(user["telegram_id"], None)
        await send_message(chat_id, t(lang, "dep_gateway_offline"), kb=back_kb(lang))
        return
    amount = data.get("amount")
    photo = message.get("photo")
    if not photo:
        await send_message(chat_id, t(lang, "send_photo_please"), kb=cancel_kb(lang))
        return
    file_id = photo[-1]["file_id"]
    dep = await create_pending_deposit(user, {"amount": amount}, proof_file_id=file_id)
    await set_state(user["telegram_id"], None)
    await send_message(chat_id, t(lang, "proof_received"), kb=back_kb(lang))
    await notify_admin(
        f"💰 <b>Deposit IDR Baru — Perlu Verifikasi</b>\n\nDari: {user_label(user)}\n"
        f"Metode: Transfer Bank\nJumlah: <b>{fmt_amount(amount, 'IDR')}</b>\nBukti: 👆",
        kb=admin_decision_kb(dep["_id"]), photo_file_id=file_id)


# ============ OTHER MENUS ============

async def show_balance(chat_id, user):
    lang = user.get("lang", "id")
    rate = await get_rate()
    await send_message(chat_id,
        t(lang, "balance_view", usd=float(user.get("balance_usd", 0)), idr=fmt_amount(user.get("balance_idr", 0), "IDR"),
          cur=user["currency"], rate=fmt_amount(rate, "IDR")), kb=back_kb(lang))


def history_button_style(status) -> str:
    """History detail button color by transaction status (Bot API 9.4 `style`).

    🟢 success = delivered / paid / approved
    🔴 danger  = failed / rejected / cancelled / expired / delivery_failed
    🔵 primary = pending / in-progress / refunded
    """
    s = str(status or "").lower()
    if s in {"delivered", "paid", "approved"}:
        return "success"
    if s in {"failed", "rejected", "cancelled", "expired", "delivery_failed"}:
        return "danger"
    return "primary"


async def show_history(chat_id, user, page=1, *, loading=False, edit_id=None):
    lang = user.get("lang", "id")
    if loading:
        # The loading helper owns the message lifecycle (reuse or replace),
        # so don't let send_message touch the callback message afterwards.
        _EDIT_TARGETS.pop(chat_id, None)
        loading_id = await _loading_message(
            chat_id, "Mengambil riwayat dari database", edit_id=edit_id)
    else:
        loading_id = None

    async def _deliver(text, kb):
        if loading_id:
            try:
                res = await tg_edit_message(chat_id, loading_id, text, kb=kb)
                if res.get("ok"):
                    return
            except Exception:
                pass
            logger.debug("History loading edit failed, falling back to send",
                         exc_info=True)
        await send_message(chat_id, text, kb=kb)

    tid = user["telegram_id"]
    deps = await db.deposits.find({"user_tid": tid}).sort("created_at", -1).limit(50).to_list(50)
    purs = await db.purchases.find({"user_tid": tid}).sort("created_at", -1).limit(50).to_list(50)

    events = []
    for d in deps:
        events.append(("deposit", d.get("created_at") or "", d))
    for o in purs:
        events.append(("order", o.get("created_at") or "", o))
    events.sort(key=lambda x: x[1], reverse=True)

    per_page = 10
    total_pages = max(1, (len(events) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    page_events = events[(page - 1) * per_page:page * per_page]

    if not page_events:
        await _deliver(t(lang, "hist_header") + "\n\nBelum ada transaksi.", back_kb(lang))
        return

    lines = [t(lang, "hist_header"), ""]
    num_btns = []
    status_emoji = {"success": "✅", "danger": "❌", "primary": "⏳"}
    for idx, (kind, _, item) in enumerate(page_events, (page - 1) * per_page + 1):
        status = item.get("status")
        emoji = status_emoji[history_button_style(status)]
        if kind == "order":
            invoice = item.get("invoice_id", "-")
            lines.append(
                f"<u>{idx}. 🧾 <code>{escape(str(invoice))}</code> — "
                f"{fmt_amount(item.get('total', 0), item.get('currency', 'IDR'))} {emoji}</u>"
            )
            num_btns.append({"text": str(idx), "callback_data": f"hist:ord:{item['_id']}",
                             "style": history_button_style(status)})
        else:
            dep_id = item.get("_id", "")
            amount = item.get("payment_amount") or item.get("amount") or 0
            method = "QRIS All Payment" if item.get("method") == "gopay" else (item.get("method") or "Deposit")
            lines.append(
                f"<u>{idx}. 💰 {escape(str(method))} — "
                f"{fmt_amount(amount, item.get('currency', 'IDR'))} {emoji}</u>"
            )
            num_btns.append({"text": str(idx), "callback_data": f"hist:dep:{dep_id}",
                             "style": history_button_style(status)})
    lines.append("")
    lines.append("Tekan tombol nomor di bawah untuk melihat detail transaksi.")
    lines.append("")
    lines.append("🟢 Sukses · 🔴 Gagal · 🔵 Pending")
    lines.append(f"\nHalaman {page}/{total_pages}")
    rows = []
    for i in range(0, len(num_btns), 5):
        rows.append(num_btns[i:i + 5])
    nav = []
    if page > 1:
        nav.append({"text": "⬅️ Sebelumnya", "callback_data": f"histpage:{page - 1}"})
    if page < total_pages:
        nav.append({"text": "Berikutnya ➡️", "callback_data": f"histpage:{page + 1}"})
    if nav:
        rows.append(nav)

    rows.append([{"text": t(lang, "btn_main"), "callback_data": "menu:main"}])
    await _deliver("\n".join(lines), {"inline_keyboard": rows})


async def show_order_history_detail(chat_id, user, order_id):
    lang = user.get("lang", "id")
    order = await db.purchases.find_one({"_id": order_id, "user_tid": user["telegram_id"]})
    if not order:
        await send_message(chat_id, "Transaksi tidak ditemukan.", kb=back_kb(lang))
        return

    status_labels = {
        "pending": "⏳ Pending", "pending_payment": "📱 Menunggu QRIS", "expired": "⌛ Kedaluwarsa", "paid": "💳 Dibayar", "processing": "⚙️ Diproses",
        "delivered": "✅ Selesai", "delivery_failed": "⚠️ Gagal Kirim",
        "failed": "❌ Gagal", "refunded": "↩️ Refund",
    }
    lines = [
        "🧾 <b>Detail Invoice</b>",
        f"Invoice: <code>{escape(str(order.get('invoice_id','-')))}</code>",
        f"Order ID: <code>{escape(str(order.get('_id','-')))}</code>",
        f"Tanggal transaksi: <b>{escape(str(order.get('created_at','-')))}</b>",
        f"Status: <b>{status_labels.get(order.get('status'), order.get('status','-'))}</b>",
        f"Metode pembayaran: <b>{escape(str(order.get('payment_method','balance')))}</b>",
        "",
        "<b>Produk yang dibeli:</b>",
    ]
    for item in order.get("items", []):
        name = escape(str(item.get("name", "Produk")))
        qty = int(item.get("qty") or 0)
        unit = fmt_amount(item.get("unit_price", 0), order.get("currency", "IDR"))
        subtotal = fmt_amount(item.get("subtotal", 0), order.get("currency", "IDR"))
        discount = fmt_amount(item.get("discount_total", 0), order.get("currency", "IDR"))
        lines.append(f"• <b>{name}</b> ×{qty}")
        lines.append(f"  Harga/unit: {unit} | Subtotal: {subtotal}")
        if float(item.get("discount_total") or 0) > 0:
            lines.append(f"  Diskon: {discount}" + (f" ({escape(str(item.get('discount_name')) )})" if item.get("discount_name") else ""))
    lines.extend([
        "",
        f"Total diskon: <b>{fmt_amount(order.get('discount_total',0), order.get('currency','IDR'))}</b>",
        f"Coupon: <b>{escape(str(order.get('coupon_code') or '-'))}</b>",
        f"Total transaksi: <b>{fmt_amount(order.get('total',0), order.get('currency','IDR'))}</b>",
    ])
    if order.get("paid_at"):
        lines.append(f"Dibayar: {escape(str(order['paid_at']))}")
    if order.get("delivered_at"):
        lines.append(f"Dikirim: {escape(str(order['delivered_at']))}")
    if order.get("delivery_error"):
        lines.append(f"Catatan: <b>{escape(str(order['delivery_error']))}</b>")
    await send_message(chat_id, "\n".join(lines), kb={"inline_keyboard": [
        [{"text": t(lang, "hist_back"), "callback_data": "menu:history"}],
        [{"text": t(lang, "btn_main"), "callback_data": "menu:main"}],
    ]})


async def show_deposit_history_detail(chat_id, user, dep_id):
    lang = user.get("lang", "id")
    dep = await db.deposits.find_one({"_id": dep_id, "user_tid": user["telegram_id"]})
    if not dep:
        await send_message(chat_id, "Deposit tidak ditemukan.", kb=back_kb(lang))
        return

    status_labels = {
        "pending": "⏳ Pending", "approved": "✅ Disetujui", "rejected": "❌ Ditolak",
        "cancelled": "🚫 Dibatalkan", "expired": "⌛ Kedaluwarsa",
    }
    lines = [
        "💰 <b>Detail Deposit</b>",
        f"Deposit ID: <code>{escape(str(dep.get('_id','-')))}</code>",
        f"Tanggal: <b>{escape(str(dep.get('created_at','-')))}</b>",
        f"Metode: <b>{escape(str(dep.get('method','-')))}</b>",
        f"Status: <b>{status_labels.get(dep.get('status'), dep.get('status','-'))}</b>",
        f"Deposit: <b>{fmt_amount(dep.get('amount',0), dep.get('currency','IDR'))}</b>",
    ]
    if dep.get("admin_fee") is not None:
        lines.append(f"Admin fee 0.7%: <b>{fmt_amount(dep.get('admin_fee'), dep.get('currency','IDR'))}</b>")
    if dep.get("platform_code") is not None:
        lines.append(f"Admin platform: <b>{dep.get('platform_code')}</b>")
    if dep.get("payment_amount") is not None:
        lines.append(f"Total dibayarkan: <b>{fmt_amount(dep.get('payment_amount'), dep.get('currency','IDR'))}</b>")
    if dep.get("credited_amount") is not None:
        lines.append(f"Saldo dikreditkan: <b>{fmt_amount(dep.get('credited_amount'), dep.get('currency','IDR'))}</b>")
    if dep.get("coin"):
        lines.append(f"Koin/Jaringan: <b>{escape(str(dep.get('coin')))} / {escape(str(dep.get('network')))}</b>")
    if dep.get("tx_hash"):
        lines.append(f"TX: <code>{escape(str(dep.get('tx_hash')))}</code>")
    if dep.get("gopay_tx_id"):
        lines.append(f"GoPay TX: <code>{escape(str(dep.get('gopay_tx_id')))}</code>")
    if dep.get("decided_at"):
        lines.append(f"Diproses: {escape(str(dep.get('decided_at')))}")
    await send_message(chat_id, "\n".join(lines), kb={"inline_keyboard": [
        [{"text": t(lang, "hist_back"), "callback_data": "menu:history"}],
        [{"text": t(lang, "btn_main"), "callback_data": "menu:main"}],
    ]})


async def show_settings(chat_id, user):
    lang = user.get("lang", "id")
    other = "IDR" if user["currency"] == "USD" else "USD"
    rows = [
        [{"text": t(lang, "btn_change_currency", cur=other), "callback_data": f"setcur:{other}"}],
        [{"text": t(lang, "btn_language"), "callback_data": "langmenu"}],
    ]
    if await is_bot_admin(user):
        rows.append([{"text": "🎨 Custom Welcome Picture", "callback_data": "wmedia:menu"}])
    rows.append([{"text": t(lang, "btn_main"), "callback_data": "menu:main"}])
    kb = {"inline_keyboard": rows}
    await send_message(chat_id, t(lang, "settings_title", cur=user["currency"], lang=LANG_NAMES.get(lang, lang)), kb=kb)


def is_bot_admin_sync(user) -> bool:
    """Check whether this Telegram user is a bot admin/owner (no I/O)."""
    try:
        scope = get_current_scope()
        admin_ids = [int(x) for x in (getattr(scope, "admin_ids", None) or [])]
    except Exception:
        admin_ids = []
    try:
        return int(user.get("telegram_id")) in admin_ids
    except (TypeError, ValueError):
        return False


async def is_bot_admin(user) -> bool:
    """Admin = listed in the bot's admin_ids, else legacy settings admin."""
    if is_bot_admin_sync(user):
        return True
    try:
        settings = await get_settings()
        legacy = settings.get("admin_telegram_id")
        return bool(legacy) and str(user.get("telegram_id")) == str(legacy)
    except Exception:
        return False


async def _save_welcome_media(patch: dict) -> dict:
    """Persist a welcome_media patch to the platform registry and scope.

    Tenant bots: sellerbottel_platform.tenants.metadata.bot_config.
    Central bot: sellerbottel_platform.platform_config central_bot doc.
    """
    from db import client as _client
    from tenant_db import resolve_platform_database_name
    scope = get_current_scope()
    slug = (scope.slug if scope is not None else "central") or "central"
    pdb = _client[resolve_platform_database_name(os.environ)]
    if slug == "central":
        coll = pdb["platform_config"]
        doc = await coll.find_one({"_id": "central_bot"}) or {}
        current = dict(doc.get("welcome_media") or {})
        current.update(patch)
        await coll.update_one({"_id": "central_bot"},
                              {"$set": {"welcome_media": current}}, upsert=True)
    else:
        coll = pdb["tenants"]
        doc = await coll.find_one({"slug": slug}) or {}
        metadata = dict(doc.get("metadata") or {})
        bot_config = dict(metadata.get("bot_config") or {})
        current = dict(bot_config.get("welcome_media") or {})
        current.update(patch)
        bot_config["welcome_media"] = current
        metadata["bot_config"] = bot_config
        await coll.update_one({"slug": slug}, {"$set": {"metadata": metadata}})
    if scope is not None:
        scope.welcome_media.update(patch)
        current = dict(scope.welcome_media)
    return current


async def handle_panel_pw_reset(chat_id, user, message, text):
    """Owner-only platform panel password reset (central bot).

    The new password is typed directly to the bot, bcrypt-hashed with the
    backend's own hasher, and stored in the platform DB. It is never logged
    or echoed back. The user's message is deleted afterwards (best effort).
    """
    new_pw = (text or "").strip()
    # The user might tap /batal mid-flow; the dispatcher already clears state
    # for /batal before reaching here, so any text here is a password attempt.
    if len(new_pw) < 8:
        await send_message(chat_id,
                           "❌ Password minimal 8 karakter ya. Kirim ulang password barunya, "
                           "atau /batal untuk membatalkan.")
        return
    if len(new_pw) > 128:
        await send_message(chat_id,
                           "❌ Password terlalu panjang (maksimal 128 karakter). Kirim ulang, "
                           "atau /batal untuk membatalkan.")
        return
    email = ""
    try:
        from auth import hash_password
        from db import client as _client
        from tenant_db import resolve_platform_database_name
        pdb = _client[resolve_platform_database_name(os.environ)]
        admin = await pdb["admins"].find_one({"platform_role": "platform_admin"})
        if admin is None:
            admin = await pdb["admins"].find_one({"role": "admin"})
        if admin is None:
            await send_message(chat_id, "❌ Tidak ada akun admin panel yang ditemukan.")
            await set_state(user["telegram_id"], None)
            return
        email = admin.get("email", "")
        await pdb["admins"].update_one(
            {"_id": admin["_id"]},
            {"$set": {"password_hash": hash_password(new_pw)}},
        )
    except Exception:
        # Never include the password in logs.
        logger.exception("panel password reset failed")
        await send_message(chat_id, "❌ Gagal menyimpan password baru. Coba lagi nanti ya.")
        await set_state(user["telegram_id"], None)
        return
    await set_state(user["telegram_id"], None)
    # Best effort: remove the message that contained the new password.
    try:
        mid = (message or {}).get("message_id")
        if mid:
            await delete_message(chat_id, mid)
    except Exception:
        pass
    await send_message(
        chat_id,
        f"✅ Password panel admin untuk <code>{escape(email)}</code> berhasil diganti.\n"
        "Silakan login ulang di panel. Pastikan pesan berisi password tadi sudah terhapus ya.")


async def handle_welcome_photo_upload(chat_id, user, message) -> bool:
    """Save an admin-sent photo/GIF as the welcome picture.

    Returns True when the message was consumed by this flow.
    """
    lang = user.get("lang", "id")
    if not await is_bot_admin(user):
        await set_state(user["telegram_id"], None)
        return False
    file_id, kind = None, "photo"
    if message.get("animation"):
        file_id = (message.get("animation") or {}).get("file_id")
        kind = "animation"
    elif message.get("photo"):
        sizes = message.get("photo") or []
        file_id = (sizes[-1] or {}).get("file_id") if sizes else None
    elif (message.get("document") or {}).get("mime_type") == "image/gif":
        file_id = (message.get("document") or {}).get("file_id")
        kind = "animation"
    if not file_id:
        await send_message(chat_id, "Kirim foto atau GIF ya. /batal untuk membatalkan.",
                           kb=cancel_kb(lang))
        return True
    await _save_welcome_media({"enabled": True, "mode": "upload",
                               "file": file_id, "kind": kind})
    await set_state(user["telegram_id"], None)
    label = "GIF 🎞️" if kind == "animation" else "Foto 🖼️"
    await send_message(chat_id,
                       f"✅ {label} tersimpan! Coba /start untuk melihat hasilnya.",
                       kb=back_kb(lang))
    return True


async def show_welcome_media_menu(chat_id, user):
    """Admin-only panel to customize the /start welcome picture."""
    if not await is_bot_admin(user):
        await send_message(chat_id, "⛔ Khusus admin bot.", kb=back_kb(user.get("lang", "id")))
        return
    scope = get_current_scope()
    media = dict(getattr(scope, "welcome_media", None) or {})
    enabled = bool(media.get("enabled"))
    mode = media.get("mode") or "auto"
    status = "Aktif ✅" if enabled else "Nonaktif ❌"
    mode_label = "Otomatis (generate dari nama bot)" if mode == "auto" else "Upload manual"
    current = ""
    if enabled and mode == "upload" and media.get("file"):
        kind = "GIF 🎞️" if (media.get("kind") == "animation") else "Foto 🖼️"
        current = f"\n🗂️ Saat ini: {kind}"
    text = (
        "🎨 <b>Custom Welcome Picture</b>\n\n"
        f"Status: <b>{status}</b>\n"
        f"Mode: <b>{mode_label}</b>{current}\n\n"
        "Mode otomatis bikin banner dari nama bot. "
        "Mode upload: kirim foto/GIF langsung ke chat ini."
    )
    toggle_label = "❌ Nonaktifkan" if enabled else "✅ Aktifkan"
    kb = {"inline_keyboard": [
        [{"text": toggle_label, "callback_data": "wmedia:toggle"}],
        [{"text": "🤖 Mode Otomatis", "callback_data": "wmedia:mode:auto"},
         {"text": "🖼️ Mode Upload", "callback_data": "wmedia:mode:upload"}],
        [{"text": "🔄 Generate Ulang Banner", "callback_data": "wmedia:regen"}],
        [{"text": "⬅️ Kembali", "callback_data": "menu:settings"}],
    ]}
    await send_message(chat_id, text, kb=kb)


async def show_language_menu(chat_id, user):
    lang = user.get("lang", "id")
    kb = {"inline_keyboard": [
        [{"text": "🇮🇩 Bahasa Indonesia", "callback_data": "setlang:id"}],
        [{"text": "🇬🇧 English", "callback_data": "setlang:en"}],
        [{"text": t(lang, "btn_back"), "callback_data": "menu:settings"}],
    ]}
    await send_message(chat_id, t(lang, "choose_language"), kb=kb)


async def handle_set_currency(chat_id, user, new_cur):
    lang = user.get("lang", "id")
    old_cur = user["currency"]
    balance = float(user.get(CUR_FIELD[old_cur], 0))
    if balance > 0:
        rate = await get_rate()
        converted = balance * rate if old_cur == "USD" else balance / rate
        kb = {"inline_keyboard": [
            [{"text": t(lang, "btn_convert_yes"), "callback_data": f"conv:yes:{new_cur}"}],
            [{"text": t(lang, "btn_convert_no"), "callback_data": f"conv:no:{new_cur}"}],
        ]}
        await send_message(chat_id,
            t(lang, "convert_ask", cur=new_cur, balance=fmt_amount(balance, old_cur),
              converted=fmt_amount(converted, new_cur), rate=fmt_amount(rate, "IDR")), kb=kb)
    else:
        await db.bot_users.update_one({"telegram_id": user["telegram_id"]}, {"$set": {"currency": new_cur}})
        await send_message(chat_id, t(lang, "currency_changed", cur=new_cur), kb=back_kb(lang))


async def handle_conversion(chat_id, user, convert, new_cur):
    lang = user.get("lang", "id")
    old_cur = "USD" if new_cur == "IDR" else "IDR"
    if convert:
        rate = await get_rate()
        balance = float(user.get(CUR_FIELD[old_cur], 0))
        converted = balance * rate if old_cur == "USD" else balance / rate
        await db.bot_users.update_one({"telegram_id": user["telegram_id"]}, {
            "$set": {"currency": new_cur, CUR_FIELD[old_cur]: 0.0},
            "$inc": {CUR_FIELD[new_cur]: converted},
        })
        await send_message(chat_id, t(lang, "converted_done", cur=new_cur, amount=fmt_amount(converted, new_cur)), kb=back_kb(lang))
    else:
        await db.bot_users.update_one({"telegram_id": user["telegram_id"]}, {"$set": {"currency": new_cur}})
        await send_message(chat_id, t(lang, "changed_kept", cur=new_cur), kb=back_kb(lang))


# ============ ADMIN CALLBACKS ============

async def handle_admin_callback(cb, action, dep_id):
    from_id = cb["from"]["id"]
    s = await get_settings()
    if str(from_id) != str(s.get("admin_telegram_id")):
        await answer_callback(cb["id"], "Bukan admin.")
        return
    dep = await db.deposits.find_one({"_id": dep_id})
    if not dep:
        await answer_callback(cb["id"], "Deposit tidak ditemukan.")
        return
    if action == "app":
        if dep["status"] != "pending":
            await answer_callback(cb["id"], f"Sudah diproses ({dep['status']}).")
            return
        await credit_deposit(dep, note="Disetujui via bot Telegram")
        await answer_callback(cb["id"], "✅ Deposit disetujui!")
        await send_message(from_id, f"✅ Deposit {fmt_amount(dep['amount'], dep['currency'])} dari <code>{dep['user_tid']}</code> disetujui.")
    elif action == "rej":
        if dep["status"] != "pending":
            await answer_callback(cb["id"], f"Sudah diproses ({dep['status']}).")
            return
        await reject_deposit(dep, note="Ditolak via bot Telegram")
        await answer_callback(cb["id"], "❌ Deposit ditolak.")
        await send_message(from_id, f"❌ Deposit {fmt_amount(dep['amount'], dep['currency'])} dari <code>{dep['user_tid']}</code> ditolak.")
    elif action == "cxl":
        if dep["status"] != "approved":
            await answer_callback(cb["id"], f"Tidak bisa dibatalkan ({dep['status']}).")
            return
        await cancel_deposit(dep)
        await answer_callback(cb["id"], "🚫 Deposit dibatalkan.")
        await send_message(from_id, f"🚫 Deposit dari <code>{dep['user_tid']}</code> dibatalkan dan saldo dikurangi.")


# ============ DISPATCH ============

def frozen_text(user):
    lang = user.get("lang", "id")
    r = user.get("frozen_reason", "")
    return t(lang, "frozen", reason=t(lang, "frozen_reason", r=r) if r else "")


async def handle_callback(cb):
    data = cb.get("data", "")
    chat_id = cb["message"]["chat"]["id"]

    blocked = await db.bot_users.find_one(
        {"telegram_id": cb["from"]["id"], "silent_blocked": True},
        {"_id": 1},
    )
    if blocked:
        try:
            await answer_callback(cb["id"])
        except Exception:
            pass
        return

    if data.startswith("adm:"):
        _, action, dep_id = data.split(":", 2)
        await handle_admin_callback(cb, action, dep_id)
        return

    user = await get_user(cb["from"])
    lang = user.get("lang", "id")
    message_id = cb.get("message", {}).get("message_id")
    if message_id is not None:
        _EDIT_TARGETS[chat_id] = message_id
    await answer_callback(cb["id"])
    try:
        await db.analytics_events.insert_one({
            "channel": "telegram_bot", "event_type": "click", "path": data,
            "metadata": {"telegram_id": user["telegram_id"]}, "created_at": now_iso(),
        })
    except Exception:
        logger.debug("Could not track Telegram interaction", exc_info=True)

    if data == "gate:check":
        clear_cache_for_user(user["telegram_id"])
        if not await ensure_join_gate(chat_id, user, force_refresh=True):
            return
        if not user.get("currency"):
            await show_currency_selection(chat_id, lang)
        else:
            await show_main_menu(chat_id, user)
        return

    if not await ensure_join_gate(chat_id, user):
        return

    if data.startswith("reseller:"):
        from reseller_signup import handle_callback as reseller_callback, show_entry
        if not _reseller_enabled():
            await send_message(chat_id, "🤖 Fitur Bikin Bot Sendiri tidak aktif di bot ini.")
            return
        if user.get("frozen"):
            await send_message(chat_id, frozen_text(user))
            return
        if data == "reseller:entry":
            await show_entry(chat_id, user)
        else:
            await reseller_callback(chat_id, data, user)
        return

    if data.startswith("service:wait:"):
        return

    if data.startswith("setlang:"):
        new_lang = data.split(":")[1]
        await db.bot_users.update_one(
            {"telegram_id": user["telegram_id"]},
            {"$set": {"lang": new_lang}},
        )
        user["lang"] = new_lang
        await send_message(chat_id, t(new_lang, "lang_set"))
        if user.get("currency"):
            await show_main_menu(chat_id, user)
        else:
            await show_currency_selection(chat_id, new_lang)
        return

    if data.startswith("cur:"):
        new_cur = data.split(":")[1]
        if new_cur not in CUR_FIELD:
            return
        await db.bot_users.update_one(
            {"telegram_id": user["telegram_id"]},
            {"$set": {"currency": new_cur}},
        )
        user["currency"] = new_cur
        await show_main_menu(chat_id, user)
        return

    if not user.get("currency"):
        await show_currency_selection(chat_id, lang)
        return

    if user.get("frozen") and data not in ("menu:help",):
        await send_message(chat_id, frozen_text(user))
        return

    if data in ("cancel", "menu:main"):
        await set_state(user["telegram_id"], None)
        await show_main_menu(chat_id, user)
    elif data == "menu:products":
        await show_products(chat_id, user, 1)
    elif data.startswith("catalog:"):
        _, token, page = data.split(":", 2)
        await show_products(chat_id, user, int(page), catalog=token)
    elif data.startswith("products:"):
        await show_products(chat_id, user, int(data.split(":", 1)[1]))
    elif data == "menu:stock":
        await show_stock(chat_id, user, edit_id=message_id)
    elif data.startswith("stockpage:"):
        try:
            await show_stock_view(chat_id, user, int(data.split(":", 1)[1]))
        except (ValueError, IndexError):
            await show_stock_view(chat_id, user, 1)
    elif data.startswith("stockadd:"):
        try:
            _, page_s, pid = data.split(":", 2)
            await handle_stock_quick_add(chat_id, user, int(page_s), pid, cb["id"])
        except (ValueError, IndexError):
            pass
    elif data.startswith("prod:"):
        await show_product_detail(chat_id, user, data.split(":", 1)[1])
    elif data.startswith("buy:"):
        await show_payment_methods(chat_id, user, [{"pid": data.split(":", 1)[1], "qty": 1}])
    elif data.startswith("cartadd:"):
        await add_to_cart(chat_id, user, data.split(":", 1)[1])
    elif data.startswith("qtycustom:"):
        await start_custom_quantity(chat_id, user, data.split(":", 1)[1])
    elif data.startswith("custompay:"):
        _, pid, qty_raw = data.split(":", 2)
        pending = user.get("state_data") or {}
        try:
            qty = int(qty_raw)
        except ValueError:
            await send_message(chat_id, "❌ Jumlah pembelian tidak valid.", kb={"inline_keyboard": [
                [{"text": "🛒 Keranjang", "callback_data": "menu:cart"}],
            ]})
            return
        if user.get("state") != "cart_custom_confirm" or str(pending.get("pid") or "") != pid or int(pending.get("qty") or 0) != qty:
            await set_state(user["telegram_id"], None)
            await send_message(
                chat_id,
                "⚠️ Konfirmasi pembelian ini sudah tidak aktif. Silakan buka kembali keranjang dan pilih jumlah yang diinginkan.",
                kb={"inline_keyboard": [
                    [{"text": "🛒 Buka Keranjang", "callback_data": "menu:cart"}],
                ]},
            )
            return
        product = await db.products.find_one({"_id": pid, "active": True})
        if not product:
            await set_state(user["telegram_id"], None)
            await send_message(chat_id, "❌ Product sudah tidak tersedia.", kb={"inline_keyboard": [
                [{"text": "🛒 Buka Keranjang", "callback_data": "menu:cart"}],
            ]})
            return
        stock = await stock_for(product)
        if stock is not None and qty > stock:
            await set_state(user["telegram_id"], None)
            await send_message(
                chat_id,
                f"⚠️ Stok berubah. Saat ini hanya tersedia <b>{int(stock)}</b> item. Silakan pilih jumlah kembali.",
                kb={"inline_keyboard": [
                    [{"text": "🔢 Ubah Jumlah", "callback_data": f"qtycustom:{pid}"},
                     {"text": "🛒 Keranjang", "callback_data": "menu:cart"}],
                ]},
            )
            return
        await set_state(user["telegram_id"], None)
        await show_payment_methods(chat_id, user, [{"pid": pid, "qty": qty}], preserve_cart=True)
    elif data == "menu:cart":
        await set_state(user["telegram_id"], None)
        user["state"] = None
        user["state_data"] = {}
        await show_cart(chat_id, user)
    elif data == "coupon:apply":
        # "Gunakan Kupon" in cart: prompt for the code (was a dead button).
        await set_state(user["telegram_id"], "coupon_code")
        await send_message(chat_id, "🎟️ Ketik <b>kode kupon</b> kamu:", kb=cancel_kb(lang))
    elif data == "coupon:guide":
        await handle_coupon_guide(chat_id, user, edit_id=message_id)
    elif data.startswith("qtyinc:"):
        await change_qty(chat_id, user, data.split(":", 1)[1], 1)
    elif data.startswith("qtydec:"):
        await change_qty(chat_id, user, data.split(":", 1)[1], -1)
    elif data.startswith("cartrm:"):
        pid = data.split(":", 1)[1]
        cart = [i for i in norm_cart(user.get("cart")) if i["pid"] != pid]
        await save_cart(user["telegram_id"], cart)
        user["cart"] = cart
        await show_cart(chat_id, user)
    elif data == "cartclear":
        await save_cart(user["telegram_id"], [])
        await send_message(chat_id, t(lang, "cart_cleared"), kb=back_kb(lang))
    elif data == "checkout":
        await show_payment_methods(chat_id, user, norm_cart(user.get("cart")))
    elif data == "pay:balance":
        await handle_payment_method(chat_id, user, "balance")
    elif data == "pay:qris":
        await handle_payment_method(chat_id, user, "qris")
    elif data == "menu:deposit":
        await show_deposit_menu(chat_id, user)
    elif data == "depmethod:qris":
        await start_idr_deposit(chat_id, user, "qris")
    elif data == "depmethod:bank":
        await start_idr_deposit(chat_id, user, "bank")
    elif data == "gopay:yes":
        await confirm_gopay_deposit(chat_id, user)
    elif data == "gopay:no":
        await set_state(user["telegram_id"], None)
        _EDIT_TARGETS.pop(chat_id, None)
        if message_id is not None:
            try:
                await delete_message(chat_id, message_id)
            except Exception:
                pass
        await show_main_menu(chat_id, user)
    elif data.startswith("depcoin:"):
        await show_network_selection(chat_id, user, data.split(":")[1])
    elif data.startswith("depnet:"):
        _, coin, network = data.split(":")
        await show_deposit_address(chat_id, user, coin, network)
    elif data == "menu:balance":
        await show_balance(chat_id, user)
    elif data == "menu:history":
        await show_history(chat_id, user, 1, loading=True, edit_id=message_id)
    elif data.startswith("histpage:"):
        try:
            await show_history(chat_id, user, int(data.split(":", 1)[1]))
        except (ValueError, IndexError):
            await show_history(chat_id, user, 1)
    elif data.startswith("hist:ord:"):
        await show_order_history_detail(chat_id, user, data.split(":", 2)[2])
    elif data.startswith("hist:dep:"):
        await show_deposit_history_detail(chat_id, user, data.split(":", 2)[2])
    elif data == "menu:settings":
        await show_settings(chat_id, user)
    elif data == "wmedia:menu":
        await show_welcome_media_menu(chat_id, user)
    elif data == "wmedia:toggle":
        if not await is_bot_admin(user):
            await answer_callback(cb["id"], "⛔ Khusus admin bot.")
        else:
            scope = get_current_scope()
            media = dict(getattr(scope, "welcome_media", None) or {})
            new_state = not bool(media.get("enabled"))
            await _save_welcome_media({"enabled": new_state})
            await show_welcome_media_menu(chat_id, user)
    elif data == "wmedia:mode:auto":
        if not await is_bot_admin(user):
            await answer_callback(cb["id"], "⛔ Khusus admin bot.")
        else:
            await _save_welcome_media({"enabled": True, "mode": "auto"})
            # Force banner regeneration on next /start.
            try:
                from welcome_banner import _slug_dir
                for old in _slug_dir(get_current_scope().slug).glob("banner-auto-*.png"):
                    try:
                        old.unlink()
                    except OSError:
                        pass
            except Exception:
                pass
            await show_welcome_media_menu(chat_id, user)
    elif data == "wmedia:mode:upload":
        if not await is_bot_admin(user):
            await answer_callback(cb["id"], "⛔ Khusus admin bot.")
        else:
            await _save_welcome_media({"enabled": True, "mode": "upload"})
            await set_state(user["telegram_id"], "welcome_photo_upload")
            await send_message(
                chat_id,
                "📤 <b>Mode upload aktif.</b>\n\nKirim foto atau GIF ke chat ini "
                "untuk dijadikan welcome picture. Kirim /batal untuk membatalkan.",
                kb=cancel_kb(lang),
            )
    elif data == "wmedia:regen":
        if not await is_bot_admin(user):
            await answer_callback(cb["id"], "⛔ Khusus admin bot.")
        else:
            try:
                from welcome_banner import _slug_dir
                scope = get_current_scope()
                for old in _slug_dir(scope.slug).glob("banner-auto-*.png"):
                    try:
                        old.unlink()
                    except OSError:
                        pass
                await _save_welcome_media({"enabled": True, "mode": "auto"})
                await send_message(chat_id, "🔄 Banner akan dibuat ulang di /start berikutnya.",
                                   kb=back_kb(lang))
            except Exception:
                logger.exception("Banner regen failed")
                await send_message(chat_id, "❌ Gagal.", kb=back_kb(lang))
    elif data == "langmenu":
        await show_language_menu(chat_id, user)
    elif data.startswith("setcur:"):
        await handle_set_currency(chat_id, user, data.split(":")[1])
    elif data.startswith("conv:"):
        _, yn, new_cur = data.split(":")
        await handle_conversion(chat_id, user, yn == "yes", new_cur)
    elif data == "menu:help":
        await send_message(chat_id, t(lang, "help"), kb=back_kb(lang))


async def handle_message(message):
    if "from" not in message or message["from"].get("is_bot"):
        return

    chat_id = message["chat"]["id"]
    message_id = message.get("message_id")

    if message_id is not None:
        try:
            await db.bot_chat_messages.update_one(
                {"chat_id": int(chat_id), "message_id": int(message_id)},
                {"$set": {
                    "chat_id": int(chat_id),
                    "message_id": int(message_id),
                    "direction": "in",
                    "created_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
        except Exception:
            logger.debug("Could not remember incoming bot message", exc_info=True)

    blocked = await db.bot_users.find_one(
        {"telegram_id": message["from"]["id"], "silent_blocked": True},
        {"_id": 1},
    )
    if blocked:
        return

    user = await get_user(message["from"])
    lang = user.get("lang", "id")
    text = (message.get("text") or "").strip()

    if text.startswith("/start"):
        payload = text.split(" ", 1)[1].strip().lower() if " " in text else ""
        if payload:
            source = await db.traffic_sources.find_one({"code": payload})
            if source:
                await db.bot_users.update_one(
                    {"telegram_id": user["telegram_id"]},
                    {"$set": {
                        "traffic_source_code": payload,
                        "traffic_source_kind": source.get("kind"),
                        "traffic_source_label": source.get("label"),
                    }},
                )
                user["traffic_source_code"] = payload

        if not await ensure_join_gate(chat_id, user):
            return
        first_start_at = user.get("first_start_at") or now_iso()
        await db.bot_users.update_one(
            {"telegram_id": user["telegram_id"], "first_start_at": {"$exists": False}},
            {"$set": {"first_start_at": first_start_at}},
        )
        if not user.get("first_start_at"):
            user["first_start_at"] = first_start_at
        await set_state(user["telegram_id"], None)
        if user.get("frozen"):
            await send_message(chat_id, frozen_text(user))
        else:
            await show_start_welcome(chat_id, user)
        return

    if text.lower().startswith("/link"):
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            await send_message(chat_id, "Untuk menghubungkan akun toko, kirim <code>/link KODE</code> dari halaman Profil toko.")
            return
        from storefront_routes import complete_telegram_link
        linked = await complete_telegram_link(int(user["telegram_id"]), parts[1])
        if not linked:
            await send_message(chat_id, "Kode penghubung tidak valid/kedaluwarsa atau akun Telegram sudah terhubung ke akun toko lain. Buat kode baru dari Profil toko.")
            return
        await send_message(chat_id, f"Akun Telegram berhasil dihubungkan ke <b>{escape(linked['email'])}</b>. Saldo bot sekarang tersinkron dengan akun toko.")
        return

    if text == "/id":
        await send_message(chat_id, f"🪪 Telegram User ID kamu: <code>{user['telegram_id']}</code>\n"
                           "Gunakan ID ini sebagai admin saat mendaftarkan bot reseller.")
        return

    if text == "/gantipassword" or text.startswith("/gantipassword@"):
        # Owner-only: reset the platform panel admin password via the central bot.
        # Tenant bot admins must NOT be able to touch the platform panel password.
        try:
            _scope = get_current_scope()
            _central = (getattr(_scope, "slug", "") == "central")
        except Exception:
            _central = False
        if not _central or not await is_bot_admin(user):
            await send_message(chat_id, "❌ Perintah ini hanya untuk pemilik bot utama.")
            return
        await set_state(user["telegram_id"], "panel_pw_reset")
        await send_message(chat_id,
                           "🔑 <b>Ganti password panel admin</b>\n\n"
                           "Kirim password barunya sebagai pesan berikutnya (minimal 8 karakter).\n"
                           "Kirim di chat ini saja ya, dan hapus pesanmu setelah selesai.\n"
                           "Ketik /batal untuk membatalkan.")
        return

    if not await ensure_join_gate(chat_id, user):
        return

    if not user.get("currency"):
        await show_currency_selection(chat_id, lang)
        return

    if user.get("frozen"):
        await send_message(chat_id, frozen_text(user))
        return

    if text.lower().startswith("/coupon "):
        # Auto-attach disabled: coupons are entered in the cart at checkout.
        await send_message(chat_id,
            "🎟️ Pasang kupon otomatis sudah dinonaktifkan.\n"
            "Ketik /coupon untuk lihat daftar kupon, lalu masukkan kodenya "
            "di <b>keranjang</b> saat checkout ya.")
        return
    if text.lower() == "/coupon":
        await show_coupons(chat_id, user)
        return

    if text in ("/batal", "/menu", "/cancel"):
        await set_state(user["telegram_id"], None)
        await show_main_menu(chat_id, user)
        return
    if text in ("/saldo", "/balance"):
        await show_balance(chat_id, user)
        return
    if text in ("/riwayat", "/history"):
        await show_history(chat_id, user, 1, loading=True)
        return
    if text in ("/stok", "/stock"):
        await show_stock(chat_id, user)
        return
    if text == "/help":
        await send_message(chat_id, t(lang, "help"), kb=back_kb(lang))
        return

    # Admin welcome-picture upload: a photo/GIF sent while the bot awaits one.
    if user.get("state") == "welcome_photo_upload":
        if await handle_welcome_photo_upload(chat_id, user, message):
            return

    # Owner-only platform panel password reset (central bot only).
    if user.get("state") == "panel_pw_reset":
        await handle_panel_pw_reset(chat_id, user, message, text)
        return

    state = user.get("state")
    if state == "reseller_token":
        from reseller_signup import receive_token
        await receive_token(chat_id, message)
        return
    if state == "reseller_admin":
        from reseller_signup import receive_admin
        await receive_admin(chat_id, user, text)
        return
    if state == "coupon_code":
        code = text.strip().upper()
        if not code:
            await send_message(chat_id, "Kode kupon tidak boleh kosong.")
            return
        await db.bot_users.update_one({"telegram_id": user["telegram_id"]}, {"$set": {"pending_coupon": code, "state": None, "state_data": {}}})
        user["pending_coupon"] = code
        user["state"] = None
        await send_message(chat_id, f"🎟️ Kupon <code>{escape(code)}</code> disimpan. Klik Checkout untuk menerapkannya.", kb={"inline_keyboard": [[{"text": "🛒 Keranjang", "callback_data": "menu:cart"}]]})
        return
    if state == "cart_custom_qty":
        await handle_custom_quantity(chat_id, user, text)
    elif state == "cart_custom_confirm":
        await send_message(
            chat_id,
            "🛒 Pesanan masih menunggu konfirmasi.\n\nSilakan gunakan tombol <b>Bayar</b> atau <b>Ubah Jumlah</b> pada pesan sebelumnya.",
            kb={"inline_keyboard": [
                [{"text": "🛒 Kembali ke Keranjang", "callback_data": "menu:cart"}],
            ]},
        )
    elif state == "dep_usd_amount":
        await handle_dep_usd_amount(chat_id, user, text)
    elif state == "dep_usd_wallet":
        await handle_dep_usd_wallet(chat_id, user, text)
    elif state == "dep_usd_proof":
        await handle_usd_proof(chat_id, user, message)
    elif state == "dep_idr_amount":
        await handle_dep_idr_amount(chat_id, user, text)
    elif state == "dep_idr_confirm":
        await send_message(chat_id, t(lang, "gopay_confirm_button"))
    elif state == "dep_idr_proof":
        await handle_idr_proof(chat_id, user, message)
    else:
        await show_main_menu(chat_id, user)

    if message_id and state in {"cart_custom_qty", "cart_custom_confirm", "dep_usd_amount", "dep_usd_wallet", "dep_usd_proof", "dep_idr_amount", "dep_idr_confirm", "dep_idr_proof"}:
        try:
            await delete_message(chat_id, message_id)
        except Exception:
            pass


async def process_update(update: dict):
    chat_id = None
    try:
        if "callback_query" in update:
            chat_id = update["callback_query"].get("message", {}).get("chat", {}).get("id")
            await handle_callback(update["callback_query"])
        elif "message" in update:
            chat_id = update["message"].get("chat", {}).get("id")
            await handle_message(update["message"])
    except Exception:
        logger.exception("Failed processing update")
    finally:
        if chat_id is not None:
            _EDIT_TARGETS.pop(chat_id, None)
