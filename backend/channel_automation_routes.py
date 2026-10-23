"""Channel Automation Admin API Routes V2.

Implements all required admin controls:
- Campaign Management (CRUD, Start, Pause, Resume, Stop, Set Runtime, Preview)
- Channel Connection (Connect, Validate Permission, Test Message, Disconnect)
- Protected Products List & Verification (Exclusions verification)
- Reserved Inventory & Restoration (Restore All, Restore Partial per product)
- Activity Logs & Metrics
"""
import os
import time
import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field

from auth import get_current_admin
from db import db
from channel_automation_protection import (
    PROTECTED_PRODUCT_IDS,
    is_product_protected,
    assert_not_protected,
)
from channel_automation_tables import (
    render_verified_transaction_table,
    render_scheduled_transaction_table,
)


from channel_automation_utils import (
    calculate_nominal,
    format_idr,
    generate_dummy_username,
    generate_dummy_user_id,
)
from channel_automation_scheduler import (
    parse_interval_to_seconds,
    select_next_interval_seconds,
    send_rich_message_to_channel,
    COMBINATION_A,
    COMBINATION_B,
    COMBINATION_C,
)
from channel_inventory_engine import (
    get_prom_inventory_summary,
    reserve_channel_inventory,
    restore_channel_inventory,
    log_channel_action,
)

from services import now_iso
from tgapi import tg

router = APIRouter(prefix="/api/admin/channel-automation", tags=["Channel Automation"])


# ===================== MODELS =====================

class CampaignCreate(BaseModel):
    name: str
    channel_id: str
    schedule_mode: str = "custom_sequence"  # combination_a, combination_b, combination_c, custom_sequence, random_pool, fixed
    sequence_seconds: Optional[List[int]] = None
    interval_pool_seconds: Optional[List[int]] = None
    interval_pool_weights: Optional[List[float]] = None
    interval_seconds: Optional[int] = 60
    target_product_ids: Optional[List[str]] = None
    target_category: Optional[str] = None
    product_weights: Optional[Dict[str, float]] = None
    reserve_units_per_post: Optional[int] = 0
    admin_fee: Optional[int] = 0
    is_simulation: bool = True  # default True for scheduled simulation


class RestoreRequest(BaseModel):
    product_id: str
    mode: str = "all"  # "all" or "partial"
    quantity: Optional[int] = None


class ChannelConnectRequest(BaseModel):
    channel_id: str
    channel_username: Optional[str] = None
    channel_title: Optional[str] = None


# ===================== CHANNEL CONNECTION =====================

@router.get("/channel")
async def get_channel_config(admin: dict = Depends(get_current_admin)):
    """Fetch current connected channel status."""
    conf = await db.channel_automation_configs.find_one({"_id": "default_channel"})
    if not conf:
        settings = await db.settings.find_one({}) or {}
        b_channel = settings.get("broadcast_channel_id")
        return {
            "channel_id": b_channel or "",
            "channel_username": "",
            "channel_title": "",
            "bot_permission_status": "unknown",
            "connection_status": "connected" if b_channel else "disconnected",
            "last_successful_send": None,
        }
    return {
        "channel_id": conf.get("channel_id", ""),
        "channel_username": conf.get("channel_username", ""),
        "channel_title": conf.get("channel_title", ""),
        "bot_permission_status": conf.get("bot_permission_status", "unknown"),
        "connection_status": conf.get("connection_status", "disconnected"),
        "last_successful_send": conf.get("last_successful_send"),
    }


@router.post("/channel/connect")
async def connect_channel(data: ChannelConnectRequest, admin: dict = Depends(get_current_admin)):
    """Save or update channel connection."""
    admin_user = admin.get("email") or "admin"
    channel_id = data.channel_id.strip()

    perm_status = "valid"
    title = data.channel_title or ""
    uname = data.channel_username or ""

    try:
        chat_info = await tg("getChat", chat_id=channel_id)
        if isinstance(chat_info, dict) and chat_info.get("ok"):
            res = chat_info["result"]
            title = res.get("title") or title
            uname = res.get("username") or uname
            perm_status = "administrator"
        else:
            perm_status = "unverified"
    except Exception:
        perm_status = "unverified"

    doc = {
        "_id": "default_channel",
        "channel_id": channel_id,
        "channel_username": uname,
        "channel_title": title,
        "bot_permission_status": perm_status,
        "connection_status": "connected",
        "updated_at": now_iso(),
        "updated_by": admin_user,
    }
    await db.channel_automation_configs.update_one({"_id": "default_channel"}, {"$set": doc}, upsert=True)
    await log_channel_action("channel_connected", admin_user, {"channel_id": channel_id, "title": title})

    return {"success": True, "channel": doc}


@router.post("/channel/validate")
async def validate_channel(admin: dict = Depends(get_current_admin)):
    """Validates bot permissions on the connected channel."""
    conf = await db.channel_automation_configs.find_one({"_id": "default_channel"})
    if not conf or not conf.get("channel_id"):
        raise HTTPException(status_code=400, detail="No channel configured.")

    channel_id = conf["channel_id"]
    try:
        chat_info = await tg("getChat", chat_id=channel_id)
        if isinstance(chat_info, dict) and chat_info.get("ok"):
            await db.channel_automation_configs.update_one(
                {"_id": "default_channel"},
                {"$set": {"bot_permission_status": "administrator", "connection_status": "connected"}},
            )
            return {"success": True, "status": "administrator", "chat": chat_info.get("result")}
        return {"success": False, "status": "unverified", "error": chat_info}
    except Exception as e:
        return {"success": False, "status": "failed", "error": str(e)}


@router.post("/channel/test-message")
async def send_test_message(admin: dict = Depends(get_current_admin)):
    """Sends a test message with the official 4-field transaction table."""
    conf = await db.channel_automation_configs.find_one({"_id": "default_channel"})
    channel_id = conf.get("channel_id") if conf else None
    if not channel_id:
        settings = await db.settings.find_one({}) or {}
        channel_id = settings.get("broadcast_channel_id")
    if not channel_id:
        raise HTTPException(status_code=400, detail="Channel not connected.")

    bot_uname = os.environ.get("TELEGRAM_BOT_USERNAME", "Idse_MarketBot").strip().lstrip("@")
    dummy_name = generate_dummy_username()
    raw_id, _ = generate_dummy_user_id()

    rendered = render_scheduled_transaction_table(
        product_name="Gemini Google AI Plus 400GB 12 bulan",
        product_id="dd1cce0a-2633-59c5-8ca3-f1ae40db80d3",
        price=15106,
        bot_username=bot_uname,
        dummy_name=dummy_name,
        dummy_user_id=raw_id,
    )

    resp = await send_rich_message_to_channel(channel_id, rendered.html, rendered.fallback_text)
    if resp.get("ok"):
        now_ts = now_iso()
        await db.channel_automation_configs.update_one(
            {"_id": "default_channel"},
            {"$set": {"last_successful_send": now_ts}},
            upsert=True,
        )
        return {"success": True, "result": resp}
    return {"success": False, "error": resp}



@router.post("/channel/disconnect")
async def disconnect_channel(admin: dict = Depends(get_current_admin)):
    admin_user = admin.get("email") or "admin"
    await db.channel_automation_configs.update_one(
        {"_id": "default_channel"},
        {"$set": {"connection_status": "disconnected"}},
    )
    await log_channel_action("channel_disconnected", admin_user, {})
    return {"success": True}


# ===================== CAMPAIGN MANAGEMENT =====================

@router.get("/campaigns")
async def list_campaigns(admin: dict = Depends(get_current_admin)):
    """List all automation campaigns."""
    cursor = db.channel_automation_campaigns.find({}).sort("created_at", -1)
    campaigns = [c async for c in cursor]
    return {"campaigns": campaigns}


@router.post("/campaigns")
async def create_campaign(data: CampaignCreate, admin: dict = Depends(get_current_admin)):
    """Creates a new Channel Automation Campaign."""
    admin_user = admin.get("email") or "admin"
    cid = str(uuid.uuid4())

    # Validate target products if specified to ensure protected products are excluded
    if data.target_product_ids:
        for pid in data.target_product_ids:
            if is_product_protected(pid):
                raise HTTPException(
                    status_code=400,
                    detail=f"Product {pid} is permanently PROTECTED and cannot be added to campaigns.",
                )

    # Preset intervals if selected
    seq_seconds = data.sequence_seconds
    pool_seconds = data.interval_pool_seconds
    if data.schedule_mode == "combination_a":
        seq_seconds = COMBINATION_A
    elif data.schedule_mode == "combination_b":
        seq_seconds = COMBINATION_B
    elif data.schedule_mode == "combination_c":
        pool_seconds = COMBINATION_C

    doc = {
        "_id": cid,
        "name": data.name,
        "channel_id": data.channel_id,
        "schedule_mode": data.schedule_mode,
        "sequence_seconds": seq_seconds or COMBINATION_A,
        "interval_pool_seconds": pool_seconds or COMBINATION_C,
        "interval_pool_weights": data.interval_pool_weights,
        "interval_seconds": data.interval_seconds or 60,
        "target_product_ids": data.target_product_ids or [],
        "target_category": data.target_category,
        "product_weights": data.product_weights or {},
        "reserve_units_per_post": data.reserve_units_per_post or 0,
        "admin_fee": data.admin_fee or 0,
        "is_simulation": data.is_simulation,
        "status": "STOPPED",
        "current_sequence_index": 0,
        "current_sequence_counter": 1,
        "messages_sent": 0,
        "failed_messages": 0,
        "last_run_at": None,
        "next_run_at": None,
        "next_run_epoch": None,
        "created_at": now_iso(),
        "created_by": admin_user,
    }
    await db.channel_automation_campaigns.insert_one(doc)
    await log_channel_action("campaign_created", admin_user, {"campaign_id": cid, "name": data.name})
    return {"success": True, "campaign": doc}


@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: str, admin: dict = Depends(get_current_admin)):
    """Starts or resumes a campaign."""
    admin_user = admin.get("email") or "admin"
    c = await db.channel_automation_campaigns.find_one({"_id": campaign_id})
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    next_sec = select_next_interval_seconds(c)
    next_epoch = time.time() + next_sec
    from datetime import datetime, timezone
    next_iso = datetime.fromtimestamp(next_epoch, tz=timezone.utc).isoformat()

    await db.channel_automation_campaigns.update_one(
        {"_id": campaign_id},
        {"$set": {
            "status": "RUNNING",
            "next_run_epoch": next_epoch,
            "next_run_at": next_iso,
        }},
    )
    await log_channel_action("campaign_started", admin_user, {"campaign_id": campaign_id})
    return {"success": True, "status": "RUNNING", "next_run_at": next_iso}


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, admin: dict = Depends(get_current_admin)):
    admin_user = admin.get("email") or "admin"
    await db.channel_automation_campaigns.update_one(
        {"_id": campaign_id},
        {"$set": {"status": "PAUSED"}},
    )
    await log_channel_action("campaign_paused", admin_user, {"campaign_id": campaign_id})
    return {"success": True, "status": "PAUSED"}


@router.post("/campaigns/{campaign_id}/resume")
async def resume_campaign(campaign_id: str, admin: dict = Depends(get_current_admin)):
    return await start_campaign(campaign_id, admin)


@router.post("/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: str, admin: dict = Depends(get_current_admin)):
    admin_user = admin.get("email") or "admin"
    await db.channel_automation_campaigns.update_one(
        {"_id": campaign_id},
        {"$set": {"status": "STOPPED", "next_run_epoch": None, "next_run_at": None}},
    )
    await log_channel_action("campaign_stopped", admin_user, {"campaign_id": campaign_id})
    return {"success": True, "status": "STOPPED"}


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, admin: dict = Depends(get_current_admin)):
    admin_user = admin.get("email") or "admin"
    await db.channel_automation_campaigns.delete_one({"_id": campaign_id})
    await log_channel_action("campaign_deleted", admin_user, {"campaign_id": campaign_id})
    return {"success": True}


# ===================== PREVIEW & NOMINAL CALCULATOR =====================

@router.get("/preview")
async def preview_message(
    template_type: str = Query("verified_transaction"),  # verified_transaction, simulation
    product_id: Optional[str] = Query(None),
    admin: dict = Depends(get_current_admin),
):
    """Renders preview of the exact 4-field rich table for admin."""
    bot_uname = os.environ.get("TELEGRAM_BOT_USERNAME", "Idse_MarketBot").strip().lstrip("@")

    # Fetch product
    p = None
    if product_id:
        p = await db.products.find_one({"_id": product_id})
    if not p:
        p = await db.products.find_one({"active": True, "_id": {"$nin": list(PROTECTED_PRODUCT_IDS)}})

    pid = p["_id"] if p else "demo_id"
    pname = p.get("name", "Gemini Pro 18 Bulan") if p else "Gemini Pro 18 Bulan"
    price = int(p.get("price_idr", 15000)) if p else 15000

    calc = calculate_nominal(base_price=price, admin_fee=0, sequence=1)

    if template_type == "verified_transaction":
        rendered = render_verified_transaction_table(
            customer_name="@RapliArdn",
            customer_telegram_id="1297810938",
            product_name=pname,
            product_id=pid,
            final_amount=calc["final_amount"],
            bot_username=bot_uname,
        )
        return {
            "template_type": template_type,
            "html": rendered.html,
            "fallback": rendered.fallback_text,
            "nominal_breakdown": calc,
        }
    else:  # scheduled_transaction / automation
        dummy_uname = generate_dummy_username()
        raw_tid, dummy_tid = generate_dummy_user_id()
        rendered = render_scheduled_transaction_table(
            product_name=pname,
            product_id=pid,
            price=calc["final_amount"],
            bot_username=bot_uname,
            dummy_name=dummy_uname,
            dummy_user_id=raw_tid,
        )

        return {
            "template_type": template_type,
            "html": rendered.html,
            "fallback": rendered.fallback_text,
            "dummy_user": dummy_uname,
            "dummy_id": dummy_tid,
            "nominal_breakdown": calc,
        }



# ===================== INVENTORY RESTORATION =====================

@router.get("/inventory/reserved")
async def list_reserved_inventory(admin: dict = Depends(get_current_admin)):
    """List products that currently have PROM inventory."""
    summary = await get_prom_inventory_summary()
    return {"reserved_products": summary, "prom_products": summary}



@router.post("/inventory/restore")
async def restore_inventory(data: RestoreRequest, admin: dict = Depends(get_current_admin)):
    """Restore reserved inventory back to available per product."""
    admin_user = admin.get("email") or "admin"
    pid = data.product_id

    # Strictly protect Claude products
    if is_product_protected(pid):
        raise HTTPException(status_code=403, detail="Product is permanently PROTECTED from restoration module.")

    try:
        res = await restore_channel_inventory(
            product_id=pid,
            quantity=data.quantity,
            admin_user=admin_user,
            mode=data.mode,
        )
        return res
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===================== METRICS & AUDIT LOGS =====================

@router.get("/metrics")
async def get_dashboard_metrics(admin: dict = Depends(get_current_admin)):
    """Returns actual metrics according to Section 9 & Acceptance Criteria."""
    running_campaigns = await db.channel_automation_campaigns.count_documents({"status": "RUNNING"})
    total_campaigns = await db.channel_automation_campaigns.count_documents({})

    sent_msgs = await db.channel_automation_messages.count_documents({"status": "sent"})
    failed_msgs = await db.channel_automation_messages.count_documents({"status": "failed"})

    eligible_count = 0
    async for p in db.products.find({"active": True}):
        if is_product_protected(p):
            continue
        cnt = await db.inventory_items.count_documents({"product_id": p["_id"], "status": "available"})
        if cnt > 0:
            eligible_count += 1

    total_reserved = await db.inventory_items.count_documents({"status": "PROM"})

    protected_count = len(PROTECTED_PRODUCT_IDS)

    next_run_doc = await db.channel_automation_campaigns.find_one(
        {"status": "RUNNING", "next_run_at": {"$ne": None}},
        sort=[("next_run_epoch", 1)],
    )

    return {
        "running_campaigns": running_campaigns,
        "total_campaigns": total_campaigns,
        "messages_sent": sent_msgs,
        "failed_messages": failed_msgs,
        "eligible_products": eligible_count,
        "reserved_stock": total_reserved,
        "protected_products_excluded": protected_count,
        "next_run": (next_run_doc or {}).get("next_run_at"),
    }


@router.get("/logs")
async def get_activity_logs(limit: int = 50, admin: dict = Depends(get_current_admin)):
    cursor = db.channel_automation_logs.find({}).sort("created_at", -1).limit(limit)
    logs = [l async for l in cursor]
    return {"logs": logs}


@router.get("/protected-products")
async def list_protected_products(admin: dict = Depends(get_current_admin)):
    """Explicitly returns the list of permanently protected products."""
    prods = []
    async for p in db.products.find({"$or": [{"_id": {"$in": list(PROTECTED_PRODUCT_IDS)}}, {"sku": {"$in": ["PRD008", "SRV002", "SRV003"]}}]}):
        prods.append({
            "product_id": p["_id"],
            "name": p.get("name"),
            "sku": p.get("sku"),
            "status": "PROTECTED — PERMANENTLY EXCLUDED",
        })
    return {"protected_products": prods}
