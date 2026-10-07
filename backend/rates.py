from datetime import datetime, timezone, timedelta
import httpx
from db import db, get_settings


async def get_rate() -> float:
    s = await get_settings()
    if s.get("rate_mode") == "manual":
        return float(s.get("manual_rate") or 16000.0)
    updated = s.get("rate_updated_at")
    if updated:
        try:
            ts = datetime.fromisoformat(updated)
            if datetime.now(timezone.utc) - ts < timedelta(hours=1):
                return float(s.get("cached_rate") or 16000.0)
        except (ValueError, TypeError):
            pass
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://open.er-api.com/v6/latest/USD")
            rate = float(r.json()["rates"]["IDR"])
        await db.settings.update_one({"_id": "main"}, {"$set": {
            "cached_rate": rate,
            "rate_updated_at": datetime.now(timezone.utc).isoformat(),
        }})
        return rate
    except Exception:
        return float(s.get("cached_rate") or 16000.0)
