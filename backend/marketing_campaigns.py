"""Persistent channel campaigns in broadcasts; stock audits in stock_events.

Each inventory status change embeds its audit in the SAME Mongo document.
Campaign leases serialize admin actions/workers. Uncertain Telegram sends are
never automatically repeated (Telegram sendMessage has no idempotency key).
"""
import asyncio
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from auth import get_current_admin
from broadcast_composer import configured_chats, send_composed
from checkout import stock_for
from db import db
from product_catalog import catalog_name
from services import base_price, fmt_amount

router = APIRouter(prefix="/api/admin/broadcasts/campaigns", dependencies=[Depends(get_current_admin)])
KIND = "marketing_campaign"
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


def next_time(campaign, clock=None):
    return ((clock or now()) + timedelta(minutes=random.randint(campaign["minimum_interval"], campaign["maximum_interval"]))).isoformat()


class CampaignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    channel: str = Field(min_length=1, max_length=100)
    minimum_interval: int = Field(default=5, ge=1, le=10080)
    maximum_interval: int = Field(default=70, ge=1, le=10080)
    count: int = Field(default=30, ge=1, le=500)
    product_ids: list[str] = Field(default_factory=list, max_length=500)
    request_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")

    @model_validator(mode="after")
    def valid(self):
        if not self.name.strip() or self.maximum_interval < self.minimum_interval:
            raise ValueError("Nama wajib diisi dan interval maksimum harus >= minimum")
        return self


def inventory_product(product):
    return (product.get("product_kind") == "digital" or product.get("delivery_type") == "inventory" or product.get("inventory_enabled")) and product.get("product_kind") != "service"


async def eligible(campaign):
    query = {"active": True, "archived": {"$ne": True}}
    if campaign.get("product_ids"):
        query["_id"] = {"$in": campaign["product_ids"]}
    products = []
    async for product in db.products.find(query):
        if not inventory_product(product):
            continue
        stock = await stock_for(product)
        if stock is not None and stock >= max(1, int(product.get("minimum_purchase_qty") or 1)):
            products.append(product)
    alternatives = [p for p in products if p["_id"] != campaign.get("last_product_id")]
    random.shuffle(alternatives)
    rest = [p for p in products if p not in alternatives]
    random.shuffle(rest)
    return alternatives + rest


def public(campaign, detail=False):
    result = {k: v for k, v in campaign.items() if k not in {"lease_owner", "lease_until", "events", "request"}}
    result["remaining"] = campaign["count"] - campaign.get("sent", 0)
    if detail:
        result["events"] = campaign["events"]
    return result


@router.get("/options")
async def options():
    return {"channels": await configured_chats(), "allocation": "Satu item inventory per pesan. Jasa/tanpa inventory tidak dipilih."}


@router.post("")
async def create(body: CampaignBody, admin: dict = Depends(get_current_admin)):
    if body.channel not in await configured_chats():
        raise HTTPException(400, "Pilih tujuan broadcast yang sudah dikonfigurasi")
    cid = "marketing:" + str(admin["_id"]) + ":" + body.request_id
    existing = await db.broadcasts.find_one({"_id": cid})
    if existing:
        if existing.get("request") != body.model_dump():
            raise HTTPException(409, "Request ID sudah digunakan")
        return public(existing)
    campaign = {"_id": cid, "kind": KIND, "name": body.name.strip(), "channel": body.channel,
        "minimum_interval": body.minimum_interval, "maximum_interval": body.maximum_interval,
        "count": body.count, "product_ids": list(dict.fromkeys(body.product_ids)),
        "status": "active", "sent": 0, "cursor": 0, "created_at": now().isoformat(),
        "admin_id": admin["_id"], "request": body.model_dump(), "last_product_id": None,
        "events": [{"_id": str(uuid.uuid4()), "status": "pending", "attempts": 0} for _ in range(body.count)]}
    if not await eligible(campaign):
        raise HTTPException(400, "Tidak ada produk inventory aktif dengan stok yang memenuhi minimum pembelian")
    campaign["next_scheduled_at"] = next_time(campaign)
    campaign["events"][0]["scheduled_at"] = campaign["next_scheduled_at"]
    try:
        await db.broadcasts.insert_one(campaign)
    except DuplicateKeyError:
        existing = await db.broadcasts.find_one({"_id": cid})
        if existing.get("request") != body.model_dump():
            raise HTTPException(409, "Request ID sudah digunakan")
        return public(existing)
    return public(campaign)


@router.get("")
async def listing():
    return [public(c) async for c in db.broadcasts.find({"kind": KIND}).sort("created_at", -1).limit(100)]


@router.get("/{cid}")
async def detail(cid: str):
    campaign = await db.broadcasts.find_one({"_id": cid, "kind": KIND})
    if not campaign:
        raise HTTPException(404, "Campaign tidak ditemukan")
    return public(campaign, True)


async def lock(cid, due=False):
    token = str(uuid.uuid4())
    clock = now()
    query = {"_id": cid, "kind": KIND, "$or": [{"lease_until": {"$exists": False}}, {"lease_until": {"$lte": clock.isoformat()}}]}
    if due:
        query.update(status="active", next_scheduled_at={"$lte": clock.isoformat()})
    return await db.broadcasts.find_one_and_update(query, {"$set": {"lease_owner": token,
        "lease_until": (clock + timedelta(minutes=3)).isoformat()}}, return_document=ReturnDocument.AFTER)


async def write(campaign, values):
    result = await db.broadcasts.update_one({"_id": campaign["_id"], "lease_owner": campaign["lease_owner"]}, {"$set": values})
    if not result.matched_count:
        raise RuntimeError("Campaign lease lost")


async def unlock(campaign):
    await db.broadcasts.update_one({"_id": campaign["_id"], "lease_owner": campaign["lease_owner"]}, {"$unset": {"lease_owner": "", "lease_until": ""}})


async def stock_audit(item):
    for receipt in item.get("marketing_audit", []):
        await db.stock_events.update_one({"_id": receipt["_id"]}, {"$setOnInsert": receipt}, upsert=True)


async def repair_stock_audits():
    async for item in db.inventory_items.find({"marketing_audit.0": {"$exists": True}}, {"marketing_audit": 1}):
        await stock_audit(item)


async def allocate(campaign, event):
    # Unique partial index on marketing.event_id is a second guard against retries.
    existing = await db.inventory_items.find_one({"marketing.event_id": event["_id"]})
    if existing:
        if existing.get("status") != "marketing_allocated":
            raise RuntimeError("Allocation already restored")
        await stock_audit(existing)
        return existing
    for product in await eligible(campaign):
        receipt = {"_id": "marketing:allocate:" + event["_id"], "event_type": "OWNER_MARKETING_ALLOCATION",
            "quantity": -1, "product_id": product["_id"], "product_name": product.get("name"),
            "campaign_id": campaign["_id"], "reference": event["_id"], "status": "recorded",
            "admin_id": campaign["admin_id"], "created_at": now().isoformat()}
        try:
            item = await db.inventory_items.find_one_and_update({"product_id": product["_id"], "status": "available"},
                {"$set": {"status": "marketing_allocated", "marketing": {"event_id": event["_id"],
                    "campaign_id": campaign["_id"], "allocated_at": now().isoformat()}},
                 "$push": {"marketing_audit": receipt}}, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:
            item = await db.inventory_items.find_one({"marketing.event_id": event["_id"], "status": "marketing_allocated"})
        if item:
            await stock_audit(item)
            return item
    return None


async def finish_sent(campaign, event, message_id, verified_by=None):
    index = campaign["cursor"]
    values = {f"events.{index}.status": "sent", f"events.{index}.sent_at": now().isoformat(),
        f"events.{index}.telegram_message_id": message_id, "sent": campaign["sent"] + 1,
        "cursor": index + 1, "last_product_id": event.get("product_id"), "error": None}
    if verified_by:
        values[f"events.{index}.confirmed_by"] = verified_by
    if index + 1 >= campaign["count"]:
        values.update(status="completed", next_scheduled_at=None)
    else:
        scheduled = next_time(campaign)
        values.update(status="active", next_scheduled_at=scheduled)
        values[f"events.{index + 1}.scheduled_at"] = scheduled
    await write(campaign, values)


async def process(cid):
    campaign = await lock(cid, due=True)
    if not campaign:
        return
    index = campaign["cursor"]
    event = campaign["events"][index]
    try:
        if event["status"] in {"sending", "unknown"}:
            await write(campaign, {"status": "failed", "error": "Pengiriman tidak pasti. Periksa channel; konfirmasi terkirim atau stop. Tidak dikirim ulang otomatis.", f"events.{index}.status": "unknown"})
            return
        item = await allocate(campaign, event)
        if not item:
            await write(campaign, {"status": "paused", "error": "Stok eligible habis. Tambah stok lalu Resume."})
            return
        product = await db.products.find_one({"_id": item["product_id"], "active": True, "archived": {"$ne": True}})
        if not product:
            await write(campaign, {"status": "failed", "error": "Produk alokasi tidak aktif; aktifkan kembali atau Stop lalu restore."})
            return
        event.update(product_id=product["_id"], product_name=product.get("name"), catalog=catalog_name(product),
                     inventory_id=item["_id"], allocation_reference=event["_id"])
        await write(campaign, {f"events.{index}": {**event, "status": "allocated"}})
        price = fmt_amount(await base_price(product, "IDR"), "IDR")
        text = ("📣 <b>PROMO IDSE — Produk Pilihan</b>\n\n"
            f"Produk: <b>{escape(str(product.get('name') or 'Produk')[:200])}</b>\n"
            f"Katalog: {escape(str(catalog_name(product))[:100])}\nHarga: {escape(price)}\n\n"
            "Konten promosi toko. Bukan pemberitahuan pembelian pelanggan.")
        # One text message; avoids multi-message partial delivery/image ambiguity.
        await write(campaign, {f"events.{index}.status": "sending", f"events.{index}.attempts": event.get("attempts", 0) + 1,
            f"events.{index}.sending_at": now().isoformat()})
        try:
            result = await asyncio.wait_for(send_composed(campaign["channel"], text, None), timeout=40)
        except Exception:
            await write(campaign, {"status": "failed", "error": "Hasil Telegram tidak pasti; periksa channel sebelum melanjutkan.", f"events.{index}.status": "unknown"})
            return
        if result.get("ok"):
            await finish_sent(campaign, event, (result.get("result") or {}).get("message_id"))
        elif result.get("ok") is False and result.get("error_code"):
            # An explicit Telegram rejection can be retried with the SAME allocation.
            wait = max(60, int((result.get("parameters") or {}).get("retry_after") or 60))
            await write(campaign, {"status": "failed", "error": "Telegram menolak pengiriman (kode %s). Resume untuk mencoba lagi." % result.get("error_code", "unknown"),
                "retry_after": (now() + timedelta(seconds=wait)).isoformat(), f"events.{index}.status": "failed"})
        else:
            await write(campaign, {"status": "failed", "error": "Respons Telegram tidak valid; periksa channel sebelum melanjutkan.", f"events.{index}.status": "unknown"})
    finally:
        await unlock(campaign)


class Action(BaseModel):
    action: Literal["pause", "resume", "stop", "confirm_sent"]
    message_id: int | None = Field(default=None, ge=1)


@router.post("/{cid}/action")
async def action(cid: str, body: Action, admin: dict = Depends(get_current_admin)):
    campaign = await lock(cid)
    if not campaign:
        raise HTTPException(409, "Campaign sedang diproses atau tidak ditemukan. Coba lagi setelah pengiriman selesai.")
    try:
        if campaign["status"] in {"completed", "stopped"}:
            raise HTTPException(409, "Campaign sudah selesai/dihentikan")
        event = campaign["events"][campaign["cursor"]]
        if body.action == "pause":
            await write(campaign, {"status": "paused"})
        elif body.action == "stop":
            events = campaign["events"]
            for row in events:
                if row["status"] not in {"sent", "unknown", "sending"}:
                    row["status"] = "cancelled"
            await write(campaign, {"status": "stopped", "next_scheduled_at": None, "events": events})
        elif body.action == "confirm_sent":
            if event["status"] not in {"unknown", "sending"} or not body.message_id:
                raise HTTPException(400, "Hanya pengiriman tidak pasti yang dapat dikonfirmasi dengan ID pesan Telegram")
            await finish_sent(campaign, event, body.message_id, admin["_id"])
        else:
            if event["status"] in {"unknown", "sending"}:
                raise HTTPException(409, "Periksa channel lalu konfirmasi ID pesan terkirim atau Stop; jangan mengirim ulang pesan tidak pasti")
            scheduled = max(next_time(campaign), campaign.get("retry_after") or "")
            await write(campaign, {"status": "active", "error": None, "next_scheduled_at": scheduled,
                f"events.{campaign['cursor']}.scheduled_at": scheduled})
        return await detail(cid)
    finally:
        await unlock(campaign)


@router.get("/{cid}/allocations")
async def allocations(cid: str):
    rows = []
    async for item in db.inventory_items.find({"status": "marketing_allocated", "marketing.campaign_id": cid},
                                            {"product_id": 1, "marketing": 1}):
        product = await db.products.find_one({"_id": item["product_id"]}, {"name": 1})
        rows.append({**item, "product_name": (product or {}).get("name") or item["product_id"]})
    return rows


class RestoreBody(BaseModel):
    event_id: str | None = None  # None restores all eligible allocations for this campaign


@router.post("/{cid}/restore")
async def restore(cid: str, body: RestoreBody, admin: dict = Depends(get_current_admin)):
    campaign = await lock(cid)
    if not campaign:
        raise HTTPException(409, "Campaign sedang diproses atau tidak ditemukan")
    count = 0
    try:
        query = {"status": "marketing_allocated", "marketing.campaign_id": cid}
        if body.event_id:
            query["marketing.event_id"] = body.event_id
        async for item in db.inventory_items.find(query):
            event_id = item["marketing"]["event_id"]
            event = next(e for e in campaign["events"] if e["_id"] == event_id)
            if event["status"] != "sent" and campaign["status"] != "stopped":
                continue  # a failed/pending send must retain its original allocation for retry
            receipt = {"_id": "marketing:restore:" + event_id, "event_type": "OWNER_MARKETING_RESTORE",
                "quantity": 1, "product_id": item["product_id"], "reference": event_id,
                "campaign_id": cid, "admin_id": admin["_id"], "status": "recorded", "created_at": now().isoformat()}
            restored = await db.inventory_items.find_one_and_update({"_id": item["_id"], "status": "marketing_allocated", "marketing.event_id": event_id},
                {"$set": {"status": "available", "marketing.restored_at": now().isoformat()}, "$push": {"marketing_audit": receipt}}, return_document=ReturnDocument.AFTER)
            if restored:
                count += 1
                await stock_audit(restored)
        return {"ok": True, "restored": count, "remaining": await db.inventory_items.count_documents(query)}
    finally:
        await unlock(campaign)


async def run_marketing(stop):
    from balance_admin import repair_audits
    while not stop.is_set():
        try:
            await repair_audits()
            await repair_stock_audits()
            async for campaign in db.broadcasts.find({"kind": KIND, "status": "active", "next_scheduled_at": {"$lte": now().isoformat()}}).limit(20):
                try:
                    await process(campaign["_id"])
                except Exception as exc:
                    logger.error("Marketing worker failed: %s", type(exc).__name__)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Marketing audit/worker retry: %s", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass
