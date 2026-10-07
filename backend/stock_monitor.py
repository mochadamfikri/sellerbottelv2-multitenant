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
        if previous is None:
            await db.products.update_one(
                {"_id": product["_id"], "stock_notice_available": {"$exists": False}},
                {"$set": {"stock_notice_available": available, "stock_notice_count": stock}},
            )
            continue
        if previous == available:
            if product.get("stock_notice_count") != stock:
                await db.products.update_one({"_id": product["_id"]}, {"$set": {"stock_notice_count": stock}})
            continue

        changed = await db.products.find_one_and_update(
            {"_id": product["_id"], "stock_notice_available": previous, "active": True},
            {"$set": {"stock_notice_available": available, "stock_notice_count": stock}},
            return_document=ReturnDocument.BEFORE,
        )
        if not changed or not chats:
            continue
        event = {
            "_id": str(uuid.uuid4()), "product_id": product["_id"],
            "product_name": product.get("name") or "Produk",
            "event_type": "restocked" if available else "sold_out",
            "from_count": 0 if available else int(changed.get("stock_notice_count") or 0),
            "to_count": int(stock), "targets": chats, "delivered": [],
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
        if event["event_type"] == "restocked":
            title = "PRODUK RESTOCK"
            heading = f"✅ <b>{escape(str(product.get('name') or 'Produk'))} tersedia kembali</b>\nStok: 0 → {stock}"
        else:
            title = "STOK HABIS"
            heading = f"⚠️ <b>{escape(str(product.get('name') or 'Produk'))} habis</b>\nStok: {event['from_count']} → 0"
        description = clean_description(product.get("description") or "", 300)
        price = fmt_amount(await base_price(product, "IDR"), "IDR")
        caption = heading + f"\nHarga: {escape(price)}" + (f"\n\n{escape(description)}" if description else "")
        image = render_product_image(product.get("name") or "Produk", price, stock, description, title=title)
        delivered = set(event.get("delivered") or [])
        for chat in event.get("targets") or []:
            if chat in delivered:
                continue
            try:
                result = await send_photo_bytes(chat, image, "status-produk.jpg", caption=caption)
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
