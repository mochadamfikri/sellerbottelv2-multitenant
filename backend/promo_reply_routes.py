from fastapi import APIRouter
from db import db

router = APIRouter()

@router.get("/events")
async def events():
    return await db.promo_events.find({}).sort("created_at", -1).limit(500).to_list(500)
