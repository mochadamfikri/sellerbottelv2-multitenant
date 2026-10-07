"""The simple product broadcast composer used by the admin panel."""
import asyncio
import base64
import re
import uuid
from html import escape, unescape
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_admin
from broadcast_image import render_message_poster, render_product_collection, render_sales_report
from broadcast_reports import format_report, sales_summary
from central_broadcast import build_central_content, options as central_options
from checkout import stock_for
from db import db, get_settings
from services import _broadcast_channel_id, base_price, fmt_amount, now_iso
from tgapi import send_message, send_photo_bytes
from product_catalog import catalog_name
from pricing import price_for_product

router = APIRouter(prefix="/api/admin/broadcasts/compose", dependencies=[Depends(get_current_admin)])


def _broadcast_user_query(query: dict | None = None):
    """Return the canonical eligible-recipient filter for every broadcast flow."""
    safe_query = dict(query or {})
    safe_query["blocked"] = {"$ne": True}
    safe_query["silent_blocked"] = {"$ne": True}
    return safe_query


class ComposeBody(BaseModel):
    kind: Literal["message", "best_sellers", "daily_recap", "system_update"] = "message"
    period: Literal["7d", "30d", "all"] = "30d"
    day: str | None = None
    message: str = ""
    product_ids: list[str] = Field(default_factory=list)
    summaries: dict[str, str] = Field(default_factory=dict)
    target: Literal["chats", "users", "both"] = "chats"
    topic: str = ""
    reference_id: str = ""
    title: str = ""
    image_mode: Literal["generated", "none", "auto"] = "generated"
    chat_ids: list[str] | None = Field(default=None, max_length=20)


def clean_description(value: str, limit: int = 180) -> str:
    """Improve spacing without inventing product claims."""
    plain = unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
    plain = re.sub(r"\s+", " ", plain).strip(" -•\t\n")
    if len(plain) <= limit:
        return plain
    return plain[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


async def configured_chats(kind="message") -> list[str]:
    settings = await get_settings()
    if kind in {"daily_recap", "best_sellers"} and settings.get("recap_channel_ids"):
        return list(dict.fromkeys(value.strip() for value in re.split(r"[,\n]+", settings["recap_channel_ids"]) if value.strip()))
    channel = await _broadcast_channel_id()
    groups = re.split(r"[,\n]+", str(settings.get("broadcast_group_ids") or ""))
    chats = [channel, *(value.strip() for value in groups)]
    return list(dict.fromkeys(value for value in chats if value))


async def build_content(body: ComposeBody):
    text, image, products = await _build_content(body)
    if body.image_mode == "none" or (body.image_mode == "auto" and not (await get_settings()).get("broadcast_auto_image_enabled")):
        image = None
    if len(text) > 4000:
        raise HTTPException(400, "Pesan terlalu panjang. Ringkas deskripsi atau kurangi produk hingga di bawah 4000 karakter.")
    return text, image, products


async def selected_chats(body):
    if body.target not in {"chats", "both"}:
        return []
    if body.chat_ids is None:
        return await configured_chats(body.kind)
    chats = list(dict.fromkeys(value.strip() for value in body.chat_ids if value.strip()))
    if any(not re.fullmatch(r"(?:-\d+|@[A-Za-z0-9_]{5,32})", value) for value in chats):
        raise HTTPException(400, "Tujuan broadcast harus berupa ID -100… atau @username.")
    return chats


async def _build_content(body: ComposeBody):
    if body.kind == "system_update":
        text, image = await build_central_content(body)
        return text, image, []
    if body.kind != "message":
        try:
            summary = await sales_summary(body.kind, body.period, body.day)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return format_report(body.kind, summary), render_sales_report(body.kind, summary), []
    ids = body.product_ids
    if len(ids) != len(set(ids)) or len(ids) > 10:
        raise HTTPException(400, "Pilih maksimal 10 produk tanpa duplikat.")
    message = body.message.strip()
    if len(message) > 1000:
        raise HTTPException(400, "Pesan utama maksimal 1000 karakter.")
    if not message and not ids:
        raise HTTPException(400, "Tulis pesan atau pilih produk.")

    products = []
    for pid in ids:
        product = await db.products.find_one({"_id": pid, "active": True})
        if not product:
            raise HTTPException(400, "Salah satu produk tidak aktif atau tidak ditemukan.")
        stock = await stock_for(product)
        if stock is not None and stock < max(1, int(product.get("minimum_purchase_qty") or 1)):
            raise HTTPException(400, f"Stok {product.get('name') or 'produk'} habis.")
        summary = clean_description(body.summaries.get(pid) or product.get("description") or "")
        price = fmt_amount((await price_for_product(product, "IDR", 1))["unit_price"], "IDR")
        products.append({"id": pid, "name": str(product.get("name") or "Produk"),
                         "summary": summary, "price": price, "stock": stock, "catalog": catalog_name(product)})

    lines = ["📣 <b>Pengumuman</b>", f"<blockquote>{escape(message)}</blockquote>"] if message else []
    if products:
        if not lines:
            lines.append("🛍️ <b>Pilihan Produk</b>")
        if lines:
            lines.append("")
        for index, product in enumerate(products, 1):
            lines.append(f"✨ <b>{index}. {escape(product['name'])}</b> — {escape(product['price'])}")
            if product["summary"]:
                lines.append(f"<blockquote>{escape(product['summary'])}</blockquote>")
            if product["stock"] is not None:
                lines.append(f"📦 Stok: {int(product['stock'])}")
            lines.append("")
        lines.append("🛒 Order: @Idse_MarketBot")
    text = "\n".join(lines).strip()
    image = render_product_collection(products, title=body.title.strip()[:80] or "PILIHAN PRODUK") if products else render_message_poster(message, title=body.title.strip()[:80] or "PENGUMUMAN")
    return text, image, products


@router.get("/central-options")
async def get_central_options():
    return await central_options()


async def send_composed(chat_id: str | int, text: str, image: bytes | None):
    if image:
        caption = text if len(text) <= 1024 else "📢 <b>Info SellerBottel</b> — rincian lengkap ada di pesan berikutnya."
        result = await send_photo_bytes(chat_id, image, "pilihan-produk.jpg", caption=caption)
        if not result.get("ok"):
            return result
        if len(text) > 1024:
            return await send_message(chat_id, text)
        return result
    return await send_message(chat_id, text)


async def _send_users(broadcast_id: str, text: str, image: bytes | None, chat_success: int, chat_failed: int):
    success, failed, blocked = chat_success, chat_failed, 0
    async for user in db.bot_users.find(_broadcast_user_query(), {"telegram_id": 1}):
        job = await db.broadcasts.find_one({"_id": broadcast_id}, {"status": 1})
        if job and job.get("status") == "cancelled":
            await db.broadcasts.update_one({"_id": broadcast_id}, {"$set": {"success": success, "failed": failed, "finished_at": now_iso()}})
            return
        if not await db.bot_users.find_one(_broadcast_user_query({"telegram_id": user["telegram_id"]})):
            continue
        try:
            result = await send_composed(user["telegram_id"], text, image)
            if result.get("ok"):
                success += 1
            else:
                failed += 1
                if result.get("error_code") == 403:
                    blocked += 1
                    await db.bot_users.update_one({"telegram_id": user["telegram_id"]}, {"$set": {"blocked": True}})
        except Exception:
            failed += 1
        if (success + failed) % 20 == 0:
            await db.broadcasts.update_one({"_id": broadcast_id}, {"$set": {"success": success, "failed": failed, "blocked": blocked}})
        await asyncio.sleep(0.08)
    await db.broadcasts.update_one({"_id": broadcast_id, "status": "running"}, {"$set": {
        "status": "completed", "success": success, "failed": failed,
        "blocked": blocked, "finished_at": now_iso(),
    }})


@router.post("/preview")
async def preview(body: ComposeBody):
    text, image, products = await build_content(body)
    chats = await selected_chats(body)
    user_count = await db.bot_users.count_documents(_broadcast_user_query()) if body.target in {"users", "both"} else 0
    return {"text": text, "products": products, "chats": chats, "user_count": user_count,
            "image_data_url": "data:image/jpeg;base64," + base64.b64encode(image).decode() if image else None}


@router.post("/jobs/{broadcast_id}/cancel")
async def cancel_job(broadcast_id: str):
    result = await db.broadcasts.update_one({"_id": broadcast_id, "status": "running"},
        {"$set": {"status": "cancelled", "finished_at": now_iso()}})
    if not result.matched_count:
        raise HTTPException(409, "Broadcast sudah selesai atau tidak ditemukan.")
    return {"ok": True}


@router.post("/test")
async def send_test(body: ComposeBody):
    text, image, _ = await build_content(body)
    admin_id = str((await get_settings()).get("admin_telegram_id") or "").strip()
    if not admin_id:
        raise HTTPException(400, "Telegram ID admin belum diisi di Pengaturan.")
    result = await send_composed(admin_id, text, image)
    if not result.get("ok"):
        raise HTTPException(502, f"Gagal kirim tes: {result.get('description', 'Telegram error')}")
    return {"ok": True}


@router.post("/send")
async def send(body: ComposeBody):
    text, image, products = await build_content(body)
    chats = await selected_chats(body)
    if body.target in {"chats", "both"} and not chats:
        raise HTTPException(400, "Channel/grup broadcast belum diisi di Pengaturan.")
    user_count = await db.bot_users.count_documents(_broadcast_user_query()) if body.target in {"users", "both"} else 0
    doc = {"_id": str(uuid.uuid4()), "text": text, "status": "running", "broadcast_type": body.kind,
           "broadcast_topic": body.topic if body.kind == "system_update" else None,
           "reference_id": body.reference_id if body.kind == "system_update" else None,
           "broadcast_target": body.target, "product_ids": [p["id"] for p in products],
           "total": user_count + len(chats), "success": 0, "failed": 0, "blocked": 0,
           "created_at": now_iso(), "finished_at": None}
    await db.broadcasts.insert_one(doc)
    chat_results = []
    for chat in chats:
        current = await db.broadcasts.find_one({"_id": doc["_id"]}, {"status": 1})
        if current and current.get("status") == "cancelled":
            break
        try:
            result = await send_composed(chat, text, image)
            chat_results.append({"chat_id": chat, "ok": bool(result.get("ok")),
                                 "error": None if result.get("ok") else result.get("description")})
        except Exception as exc:
            chat_results.append({"chat_id": chat, "ok": False, "error": type(exc).__name__})
    chat_success = sum(bool(row["ok"]) for row in chat_results)
    await db.broadcasts.update_one({"_id": doc["_id"]}, {"$set": {
        "chat_results": chat_results, "chat_success": chat_success,
        "chat_failed": len(chats) - chat_success,
    }})
    if body.target in {"users", "both"} and user_count:
        asyncio.create_task(_send_users(doc["_id"], text, image, chat_success, len(chats) - chat_success))
    else:
        await db.broadcasts.update_one({"_id": doc["_id"], "status": "running"}, {"$set": {
            "status": "completed", "success": chat_success, "failed": len(chats) - chat_success,
            "finished_at": now_iso(),
        }})
    return {"ok": True, "id": doc["_id"], "chat_results": chat_results, "queued_users": user_count}
