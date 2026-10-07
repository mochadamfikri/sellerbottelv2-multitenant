import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from db import db
from auth import get_current_admin
from services import now_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/analytics", dependencies=[Depends(get_current_admin)])
public_router = APIRouter(prefix="/api/analytics")

class TrackEventBody(BaseModel):
    channel: Literal["web_profile", "web_store", "telegram_bot"]
    event_type: Literal["page_view", "click", "add_to_cart", "interaction"]
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    path: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"

@public_router.post("/track")
async def track_event(body: TrackEventBody, request: Request):
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")
    doc = {
        "channel": body.channel,
        "event_type": body.event_type,
        "product_id": body.product_id,
        "product_name": body.product_name,
        "path": body.path,
        "metadata": body.metadata,
        "ip": ip,
        "user_agent": ua,
        "created_at": now_iso(),
    }
    await db.analytics_events.insert_one(doc)
    return {"ok": True}

def _parse_time_range(time_range: str):
    now = datetime.now(timezone.utc)
    if time_range == "24h":
        start = now - timedelta(hours=24)
    elif time_range == "7d":
        start = now - timedelta(days=7)
    elif time_range == "30d":
        start = now - timedelta(days=30)
    elif time_range == "all":
        start = None
    else:
        start = now - timedelta(days=7)
    return start.isoformat() if start else None

@router.get("/summary")
async def get_analytics_summary(time_range: str = Query("7d", pattern="^(24h|7d|30d|all)$")):
    iso_start = _parse_time_range(time_range)
    match_filter = {}
    if iso_start:
        match_filter["created_at"] = {"$gte": iso_start}

    # Profile website traffic
    profile_match = {**match_filter, "channel": "web_profile"}
    profile_views = await db.analytics_events.count_documents({**profile_match, "event_type": "page_view"})
    profile_unique_ips = len(await db.analytics_events.distinct("ip", profile_match))
    profile_clicks = await db.analytics_events.count_documents({**profile_match, "event_type": "click"})

    # Shopping website traffic
    store_match = {**match_filter, "channel": "web_store"}
    store_views = await db.analytics_events.count_documents({**store_match, "event_type": "page_view"})
    store_unique_ips = len(await db.analytics_events.distinct("ip", store_match))
    store_clicks = await db.analytics_events.count_documents({**store_match, "event_type": "click"})

    # Telegram bot traffic
    bot_match = {**match_filter, "channel": "telegram_bot"}
    bot_events = await db.analytics_events.count_documents(bot_match)
    bot_clicks = await db.analytics_events.count_documents({**bot_match, "event_type": "click"})
    bot_unique_users = len(await db.analytics_events.distinct("metadata.telegram_id", bot_match))
    if bot_unique_users == 0:
        bot_user_filter = {}
        if iso_start:
            bot_user_filter["created_at"] = {"$gte": iso_start}
        bot_unique_users = await db.bot_users.count_documents(bot_user_filter)

    # Top 3 products clicked
    click_pipeline = [
        {"$match": {**match_filter, "event_type": "click", "product_id": {"$ne": None}}},
        {"$group": {
            "_id": "$product_id",
            "name": {"$first": "$product_name"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 3}
    ]
    top_clicked = await db.analytics_events.aggregate(click_pipeline).to_list(3)

    # Top 3 products added to cart
    cart_pipeline = [
        {"$match": {**match_filter, "event_type": "add_to_cart", "product_id": {"$ne": None}}},
        {"$group": {
            "_id": "$product_id",
            "name": {"$first": "$product_name"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 3}
    ]
    top_cart = await db.analytics_events.aggregate(cart_pipeline).to_list(3)

    return {
        "time_range": time_range,
        "profile_web": {
            "page_views": profile_views,
            "unique_visitors": profile_unique_ips,
            "interactions": profile_clicks,
        },
        "shopping_web": {
            "page_views": store_views,
            "unique_visitors": store_unique_ips,
            "interactions": store_clicks,
        },
        "telegram_bot": {
            "total_events": bot_events,
            "bot_users": bot_unique_users,
            "interactions": bot_clicks,
        },
        "top_clicked_products": [
            {"product_id": item["_id"], "name": item.get("name") or item["_id"], "count": item["count"]}
            for item in top_clicked
        ],
        "top_cart_products": [
            {"product_id": item["_id"], "name": item.get("name") or item["_id"], "count": item["count"]}
            for item in top_cart
        ],
    }
