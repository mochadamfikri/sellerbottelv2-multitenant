"""Watch effective inventory availability and announce zero crossings."""
import asyncio
import logging
import uuid
from html import escape

from pymongo import ReturnDocument
from fastapi import APIRouter, Depends, HTTPException

from broadcast_image import render_product_image
from auth import get_current_admin
from broadcast_composer import clean_description, configured_chats
from checkout import stock_for
from db import db, get_settings
from services import base_price, fmt_amount, now_iso
from tgapi import send_photo_bytes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/broadcasts/stock-events", dependencies=[Depends(get_current_admin)])
monitor_lock = asyncio.Lock()


async def scan_stock(product_id: str | None = None):
    settings = await get_settings()
    enabled = settings.get("stock_notifications_enabled", True)
    chats = await configured_chats() if enabled else []
    query = {"active": True}
    if product_id:
        query["_id"] = product_id
    async for product in db.products.find(query):
        if product.get("product_kind") == "service" or product.get("delivery_type") == "service":
            continue
        stock = await stock_for(product)
        if stock is None:
            continue
        available = stock > 0
        previous = product.get("stock_notice_available")
        prev_count = product.get("stock_notice_count")
        if previous is None or prev_count is None:
            await db.products.update_one(
                {"_id": product["_id"]},
                {"$set": {"stock_notice_available": available, "stock_notice_count": stock}},
            )
            continue

        prev_count_int = int(prev_count)
        curr_count_int = int(stock)
        diff = curr_count_int - prev_count_int

        # Deteksi perubahan stok (baik restock zero-crossing maupun penambahan/pengurangan stok)
        if diff == 0:
            continue

        changed = await db.products.find_one_and_update(
            {"_id": product["_id"], "active": True},
            {"$set": {"stock_notice_available": available, "stock_notice_count": stock}},
            return_document=ReturnDocument.BEFORE,
        )
        if not changed or not chats:
            continue

        event_type = "restocked" if (previous == False and available) else ("sold_out" if stock <= 0 else ("stock_added" if diff > 0 else "stock_reduced"))
        event = {
            "_id": str(uuid.uuid4()), "product_id": product["_id"],
            "product_name": product.get("name") or "Produk",
            "catalog_name": product.get("catalog_name") or "Produk",
            "event_type": event_type,
            "from_count": prev_count_int,
            "to_count": curr_count_int,
            "diff": diff,
            "targets": chats, "delivered": [],
            "attempts": 0, "status": "pending", "created_at": now_iso(),
        }
        await db.stock_events.insert_one(event)


async def deliver_pending():
    async for event in db.stock_events.find({"status": "pending"}).sort("created_at", 1).limit(50):
        product = await db.products.find_one({"_id": event["product_id"]})
        if not product:
            await db.stock_events.update_one({"_id": event["_id"]}, {"$set": {"status": "cancelled"}})
            continue
        stock = int(event["to_count"])
        diff_val = int(event.get("diff") or (stock - int(event.get("from_count") or 0)))
        diff_str = f"+{diff_val}" if diff_val > 0 else str(diff_val)

        p_name = escape(str(product.get("name") or "Produk"))
        cat_name = escape(str(product.get("catalog_name") or "Produk"))
        price_val = fmt_amount(await base_price(product, "IDR"), "IDR")
        desc_raw = clean_description(product.get("description") or "", 150)
        desc_escaped = escape(desc_raw)

        # Tabel format resmi sesuai instruksi Owner:
        # Katalog | Product | Penambahan/pengurangan | Total Stock | Harga | Deskripsi
        table_html = (
            "<p><b>📢 UPDATE STOK PRODUK</b></p>\n"
            "<table bordered striped compact>\n"
            "<tr><th>Katalog</th><th>Product</th><th>Penambahan/pengurangan</th><th>Total Stock</th><th>Harga</th><th>Deskripsi</th></tr>\n"
            f"<tr><td>{cat_name}</td><td><b>{p_name}</b></td><td><b>{diff_str}</b></td><td>{stock}</td><td><code>{price_val}</code></td><td>{desc_escaped}</td></tr>\n"
            "</table>\n"
            "<p>🛒 <i>Pemesanan cepat di bot: @Idse_MarketBot</i></p>"
        )

        delivered = set(event.get("delivered") or [])
        rich_enabled = True

        for chat in event.get("targets") or []:
            if chat in delivered:
                continue
            try:
                # Kirim langsung tabel Telegram Rich Message
                from rich_table_transport import tg
                result = await tg("sendRichMessage", chat_id=chat, rich_message={"html": table_html, "skip_entity_detection": True})
                if not result.get("ok"):
                    # Fallback plain text jika channel/client tidak support rich table
                    plain_fallback = (
                        f"📢 <b>UPDATE STOK PRODUK</b>\n\n"
                        f"📦 <b>{p_name}</b>\n"
                        f"• Katalog: {cat_name}\n"
                        f"• Perubahan: <b>{diff_str}</b>\n"
                        f"• Total Stok: <b>{stock}</b>\n"
                        f"• Harga: <code>{price_val}</code>\n"
                        f"• Deskripsi: {desc_escaped}\n\n"
                        f"🛒 Order: @Idse_MarketBot"
                    )
                    from tgapi import send_message
                    result = await send_message(chat, plain_fallback)

                if result.get("ok"):
                    delivered.add(chat)
                else:
                    logger.warning("Stock notification %s to %s failed: %s", event["_id"], chat, result.get("description"))
            except Exception as exc:
                logger.warning("Stock notification %s to %s failed: %s", event["_id"], chat, type(exc).__name__)

        done = len(delivered) >= len(event.get("targets") or [])
        await db.stock_events.update_one({"_id": event["_id"]}, {"$set": {
            "delivered": list(delivered), "status": "sent" if done else "pending",
            "updated_at": now_iso(), "last_error": None if done else "Pengiriman ke sebagian target gagal",
        }, "$inc": {"attempts": 1}})


async def run_stock_monitor(stop: asyncio.Event):
    while not stop.is_set():
        try:
            async with monitor_lock:
                await scan_stock()
                await deliver_pending()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Stock monitor gagal; akan dicoba lagi")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass


def schedule_stock_scan(product_id: str):
    """React promptly to writes; the periodic scan remains a recovery path."""
    async def run():
        try:
            async with monitor_lock:
                await scan_stock(product_id)
                await deliver_pending()
        except Exception:
            logger.exception("Stock scan gagal untuk produk %s", product_id)

    asyncio.create_task(run())


@router.get("")
async def list_stock_events():
    return await db.stock_events.find({"event_type": {"$in": ["restocked", "sold_out"]}}).sort("created_at", -1).limit(50).to_list(50)


@router.post("/{event_id}/retry")
async def retry_stock_event(event_id: str):
    event = await db.stock_events.find_one({"_id": event_id})
    if not event:
        raise HTTPException(404, "Notifikasi stok tidak ditemukan.")
    if event.get("event_type") not in {"restocked", "sold_out"}:
        raise HTTPException(400, "Ledger marketing bukan notifikasi stok; gunakan menu campaign")
    if event.get("status") == "sent":
        return {"ok": True, "status": "sent"}
    await db.stock_events.update_one({"_id": event_id}, {"$set": {"status": "pending"}})
    async with monitor_lock:
        await deliver_pending()
    current = await db.stock_events.find_one({"_id": event_id})
    return {"ok": current.get("status") == "sent", "status": current.get("status")}
