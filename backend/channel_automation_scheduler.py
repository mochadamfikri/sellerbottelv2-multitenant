"""Channel Automation Persistent Scheduler Engine.

Section 10: AUTOMATION SCHEDULER — FLEXIBLE RUNTIME
- Supports intervals: Seconds, Minutes, Fractional minutes, Combined min & sec,
  Custom sequences (Mode A, Mode B), Randomized sequence with weights (Mode C).
- Converts all intervals to seconds.
- Background persistent loop that survives service restarts.
- Resumes RUNNING campaigns automatically on startup.
- Uses database for persistent state (next_run_at, last_run_at, status).
- Distributed lock / concurrency control to prevent duplicate messages across multiple workers.
- Exponential backoff & handles Telegram HTTP 429 Retry-After.
"""
import asyncio
import logging
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from db import db
from channel_automation_protection import assert_not_protected, is_product_protected
from channel_automation_tables import (
    render_promo_product_table,
    render_simulation_table,
    make_product_url,
)
from channel_inventory_engine import reserve_channel_inventory, log_channel_action
from tgapi import tg
from services import now_iso

logger = logging.getLogger(__name__)

_SCHEDULER_TASK: Optional[asyncio.Task] = None
_STOP_EVENT = asyncio.Event()


def parse_interval_to_seconds(spec: Any) -> int:
    """Converts seconds, minutes, fractional minutes, or combined into seconds."""
    if isinstance(spec, (int, float)):
        return max(5, int(round(spec)))

    if isinstance(spec, str):
        val = spec.strip().lower()
        if ("m" in val or "menit" in val) and ("s" in val or "detik" in val):
            m_part = val.split("menit")[0] if "menit" in val else val.split("m")[0]
            rest = val[len(m_part):].replace("menit", "").replace("m", "").strip()
            s_part = rest.replace("detik", "").replace("s", "").strip()
            try:
                m = float(m_part.strip())
                s = float(s_part.strip())
                return max(5, int(round(m * 60 + s)))
            except ValueError:
                pass
        if val.endswith("s") or val.endswith("detik"):
            num = float(val.replace("detik", "").replace("s", "").strip())
            return max(5, int(round(num)))
        if val.endswith("m") or val.endswith("menit"):
            num = float(val.replace("menit", "").replace("m", "").strip())
            return max(5, int(round(num * 60)))
        try:
            return max(5, int(round(float(val))))
        except ValueError:
            pass

    return 60  # Default 60 seconds
    return 60  # Default 60 seconds


def select_next_interval_seconds(campaign: Dict[str, Any]) -> int:
    """Calculate next delay in seconds according to Mode A/B/C."""
    mode = campaign.get("schedule_mode", "custom_sequence")
    
    if mode == "custom_sequence":
        # sequence: e.g. [180, 120, 180, 360, 300, 330]
        sequence = campaign.get("sequence_seconds") or [180, 120, 180, 360, 300, 330]
        idx = int(campaign.get("current_sequence_index", 0))
        next_sec = sequence[idx % len(sequence)]
        return max(5, int(next_sec))

    if mode == "random_pool":
        # Mode C: Weighted or simple random from pool
        pool = campaign.get("interval_pool_seconds") or [
            30, 60, 90, 120, 140, 150, 180, 210, 300, 330, 360, 1800
        ]
        weights = campaign.get("interval_pool_weights")
        if weights and len(weights) == len(pool):
            chosen = random.choices(pool, weights=weights, k=1)[0]
        else:
            chosen = random.choice(pool)
        return max(5, int(chosen))

    # Fixed or single interval
    fixed = campaign.get("interval_seconds", 60)
    return parse_interval_to_seconds(fixed)


async def select_eligible_product(campaign: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Selects an eligible product according to Section 5:
    
    - Active product
    - Inventory available > 0
    - Valid price
    - NOT protected (asserted)
    - Conforms to campaign filters (all, specific IDs, category)
    - Weighted selection if configured
    """
    query: Dict[str, Any] = {"active": True}

    selected_ids = campaign.get("target_product_ids")
    if selected_ids and isinstance(selected_ids, list) and len(selected_ids) > 0:
        query["_id"] = {"$in": selected_ids}

    category = campaign.get("target_category")
    if category:
        query["catalog_name"] = category

    cursor = db.products.find(query)
    candidates = []
    async for p in cursor:
        if is_product_protected(p):
            continue

        price = p.get("price_idr")
        if not price or float(price) <= 0:
            continue

        # Check actual available inventory
        available_cnt = await db.inventory_items.count_documents({
            "product_id": p["_id"],
            "status": "available",
        })
        if available_cnt > 0:
            candidates.append((p, available_cnt))

    if not candidates:
        return None

    # Weighted random selection based on available stock count
    products, weights = zip(*candidates)
    selected = random.choices(products, weights=weights, k=1)[0]
    assert_not_protected(selected, "campaign product publication")
    return selected


async def execute_campaign_job(campaign: Dict[str, Any]) -> Dict[str, Any]:
    """Executes a single step of a scheduled campaign."""
    campaign_id = campaign["_id"]
    channel_id = campaign.get("channel_id")
    if not channel_id:
        return {"success": False, "error": "No channel configured for campaign"}

    # Acquire distributed/atomic lock on this campaign
    lock_token = str(uuid.uuid4())
    acquired = await db.channel_automation_campaigns.update_one(
        {
            "_id": campaign_id,
            "status": "RUNNING",
            "$or": [
                {"executing_lock": None},
                {"executing_lock_expires_at": {"$lt": time.time()}},
            ],
        },
        {
            "$set": {
                "executing_lock": lock_token,
                "executing_lock_expires_at": time.time() + 60,
            }
        },
    )
    if acquired.modified_count == 0:
        return {"success": False, "skipped": "already_executing_or_not_running"}

    try:
        is_simulation = campaign.get("is_simulation", False)
        product = await select_eligible_product(campaign)
        if not product:
            logger.warning("No eligible products with available stock for campaign %s", campaign_id)
            return {"success": False, "error": "no_eligible_products_with_stock"}

        pid = product["_id"]
        pname = product.get("name", "Produk")
        price = int(product.get("price_idr", 0))

        # Check inventory reservation if campaign configured to reserve
        reserve_units = campaign.get("reserve_units_per_post", 0)
        reservation_id = None
        if not is_simulation and reserve_units > 0:
            try:
                res_data = await reserve_channel_inventory(
                    product_id=pid,
                    quantity=reserve_units,
                    campaign_id=campaign_id,
                    admin_user="scheduler",
                    operation_type="campaign_post_reservation",
                )
                reservation_id = res_data.get("reservation_id")
            except Exception as e:
                logger.error("Failed to reserve inventory for campaign %s: %e", campaign_id, e)
                return {"success": False, "error": f"inventory_reservation_failed: {e}"}

        # Render message
        import os
        bot_uname = os.environ.get("TELEGRAM_BOT_USERNAME", "Idse_MarketBot")


        if is_simulation:
            rendered = render_simulation_table(pname, pid, price, bot_uname)
        else:
            rendered = render_promo_product_table(pname, pid, price, bot_uname)

        # Dispatch via sendRichMessage with retry/backoff
        send_result = await send_rich_message_to_channel(
            channel_id=channel_id,
            html_content=rendered.html,
            fallback_text=rendered.fallback_text,
        )

        msg_id = (send_result.get("result") or {}).get("message_id")
        now_ts = now_iso()

        # Update message history
        msg_record = {
            "_id": str(uuid.uuid4()),
            "campaign_id": campaign_id,
            "channel_id": channel_id,
            "product_id": pid,
            "product_name": pname,
            "is_simulation": is_simulation,
            "reservation_id": reservation_id,
            "telegram_message_id": msg_id,
            "sent_at": now_ts,
            "status": "sent" if send_result.get("ok") else "failed",
            "error_response": None if send_result.get("ok") else send_result,
        }
        await db.channel_automation_messages.insert_one(msg_record)

        # Calculate next schedule
        next_delay = select_next_interval_seconds(campaign)
        next_run_epoch = time.time() + next_delay
        next_run_iso = datetime.fromtimestamp(next_run_epoch, tz=timezone.utc).isoformat()

        seq_idx = int(campaign.get("current_sequence_index", 0)) + 1

        update_fields: Dict[str, Any] = {
            "last_run_at": now_ts,
            "next_run_at": next_run_iso,
            "next_run_epoch": next_run_epoch,
            "current_sequence_index": seq_idx,
            "executing_lock": None,
            "executing_lock_expires_at": None,
        }
        if send_result.get("ok"):
            inc_fields = {"messages_sent": 1}
        else:
            inc_fields = {"failed_messages": 1}

        await db.channel_automation_campaigns.update_one(
            {"_id": campaign_id},
            {"$set": update_fields, "$inc": inc_fields},
        )

        return {"success": bool(send_result.get("ok")), "message_id": msg_id, "next_run": next_run_iso}

    except Exception as exc:
        logger.exception("Error executing campaign job %s", campaign_id)
        # Release lock
        await db.channel_automation_campaigns.update_one(
            {"_id": campaign_id},
            {"$set": {"executing_lock": None, "executing_lock_expires_at": None}},
        )
        return {"success": False, "error": str(exc)}


async def send_rich_message_to_channel(
    channel_id: Any,
    html_content: str,
    fallback_text: str,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Dispatches rich table message with exponential backoff and HTTP 429 Retry-After handling."""
    retries = 0
    backoff = 2

    while retries < max_retries:
        try:
            resp = await tg(
                "sendRichMessage",
                chat_id=channel_id,
                rich_message={"html": html_content, "skip_entity_detection": True},
            )
            if isinstance(resp, dict):
                if resp.get("ok"):
                    return resp
                err_code = resp.get("error_code")
                # Handle rate limiting 429
                if err_code == 429:
                    params = resp.get("parameters") or {}
                    retry_after = int(params.get("retry_after", backoff))
                    logger.warning("Telegram 429 Rate limited. Waiting %d seconds", retry_after)
                    await asyncio.sleep(retry_after)
                    retries += 1
                    continue
                # If Telegram endpoint explicitly rejects table HTML (400), try fallback
                if err_code == 400:
                    fallback_resp = await tg("sendMessage", chat_id=channel_id, text=fallback_text)
                    return fallback_resp
            return resp or {"ok": False, "error": "unknown_response"}
        except Exception as e:
            logger.warning("Send rich message error (attempt %d): %s", retries + 1, e)
            await asyncio.sleep(backoff)
            backoff *= 2
            retries += 1

    return {"ok": False, "error": "max_retries_exceeded"}


async def scheduler_loop():
    """Persistent background task that monitors and runs scheduled campaigns."""
    logger.info("Channel Automation Scheduler started.")
    while not _STOP_EVENT.is_set():
        try:
            now_epoch = time.time()
            # Find running campaigns whose next_run_epoch <= now
            cursor = db.channel_automation_campaigns.find({
                "status": "RUNNING",
                "$or": [
                    {"next_run_epoch": {"$lte": now_epoch}},
                    {"next_run_epoch": {"$exists": False}},
                    {"next_run_epoch": None},
                ],
            })
            campaigns = [c async for c in cursor]
            for campaign in campaigns:
                asyncio.create_task(execute_campaign_job(campaign))
        except Exception as e:
            logger.error("Error in scheduler_loop: %s", e)

        # Sleep briefly before next tick (no busy-wait)
        try:
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            break

    logger.info("Channel Automation Scheduler stopped.")


def start_channel_scheduler():
    global _SCHEDULER_TASK
    if _SCHEDULER_TASK is None or _SCHEDULER_TASK.done():
        _STOP_EVENT.clear()
        _SCHEDULER_TASK = asyncio.create_task(scheduler_loop())
        logger.info("Channel scheduler task created.")


def stop_channel_scheduler():
    global _SCHEDULER_TASK
    _STOP_EVENT.set()
    if _SCHEDULER_TASK and not _SCHEDULER_TASK.done():
        _SCHEDULER_TASK.cancel()
