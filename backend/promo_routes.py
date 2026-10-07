import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_admin
from db import db
from promo_service import create_coupon, update_coupon, now_iso


router = APIRouter(prefix="/api/admin/promo", dependencies=[Depends(get_current_admin)])


class CouponBody(BaseModel):
    code: str
    type: str = "percent"
    value: float
    currency: str = "IDR"
    quota_total: int | None = Field(default=None, ge=1)
    per_user_limit: int = Field(default=1, ge=1)
    min_purchase: float = Field(default=0, ge=0)
    max_discount: float | None = Field(default=None, gt=0)
    product_ids: list[str] = Field(default_factory=list)
    starts_at: str | None = None
    ends_at: str | None = None
    active: bool = True


class ProspectBody(BaseModel):
    tg_user_id: int
    username: str = ""
    name: str = ""
    owner_account_id: str
    source: dict = {}
    notes: str = ""


class SourceBody(BaseModel):
    code: str
    kind: str
    label: str


@router.get("/summary")
async def summary():
    return {
        "coupons": await db.promo_coupons.count_documents({}),
        "prospects": await db.prospects.count_documents({}),
        "campaigns": await db.outreach_campaigns.count_documents({}),
        "telegram_accounts": await db.tg_accounts.count_documents({}),
        "groups": await db.tg_groups.count_documents({}),
    }


@router.get("/coupons")
async def coupons():
    return await db.promo_coupons.find({}).sort("created_at", -1).to_list(500)


@router.post("/coupons")
async def coupon_create(body: CouponBody):
    try:
        selected_ids = list(dict.fromkeys(body.product_ids))
        if selected_ids and await db.products.count_documents({"_id": {"$in": selected_ids}}) != len(selected_ids):
            raise HTTPException(400, "Salah satu produk cakupan kupon tidak ditemukan.")
        return await create_coupon(body.model_dump())
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.put("/coupons/{coupon_id}")
async def coupon_update(coupon_id: str, body: CouponBody):
    existing = await db.promo_coupons.find_one({"_id": coupon_id})
    if not existing:
        raise HTTPException(404, "Kupon tidak ditemukan.")
    try:
        selected_ids = list(dict.fromkeys(body.product_ids))
        if selected_ids and await db.products.count_documents({"_id": {"$in": selected_ids}}) != len(selected_ids):
            raise HTTPException(400, "Salah satu produk cakupan kupon tidak ditemukan.")
        updated = await update_coupon(coupon_id, body.model_dump())
        if not updated:
            raise HTTPException(404, "Kupon tidak ditemukan.")
        return updated
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.patch("/coupons/{coupon_id}/toggle")
async def coupon_toggle(coupon_id: str):
    existing = await db.promo_coupons.find_one({"_id": coupon_id})
    if not existing:
        raise HTTPException(404, "Kupon tidak ditemukan.")
    active = not existing.get("active", True)
    await db.promo_coupons.update_one({"_id": coupon_id}, {"$set": {"active": active, "updated_at": now_iso()}})
    return {"active": active}


@router.delete("/coupons/{coupon_id}")
async def coupon_delete(coupon_id: str):
    existing = await db.promo_coupons.find_one({"_id": coupon_id})
    if not existing:
        raise HTTPException(404, "Kupon tidak ditemukan.")
    if int(existing.get("used_count") or 0) > 0:
        raise HTTPException(409, "Kupon ini sudah pernah digunakan. Nonaktifkan kupon agar riwayat transaksi tetap utuh.")
    await db.promo_coupons.delete_one({"_id": coupon_id})
    return {"ok": True}


@router.get("/coupons/{coupon_id}/redemptions")
async def coupon_redemptions(coupon_id: str):
    return await db.promo_coupon_redemptions.find({"coupon_id": coupon_id}).sort("created_at", -1).to_list(1000)


@router.get("/prospects")
async def prospects(status: str | None = None, limit: int = 200):
    query = {"status": status} if status else {}
    return await db.prospects.find(query).sort("created_at", -1).limit(min(max(limit, 1), 1000)).to_list(min(max(limit, 1), 1000))


@router.post("/prospects")
async def prospect_create(body: ProspectBody):
    existing = await db.prospects.find_one({
        "owner_account_id": body.owner_account_id,
        "tg_user_id": body.tg_user_id,
    })
    if existing:
        raise HTTPException(409, "Prospek sudah tercatat.")
    bot_user = await db.bot_users.find_one({"telegram_id": body.tg_user_id})
    owner = await db.tg_accounts.find_one({"_id": body.owner_account_id})
    if not owner:
        raise HTTPException(400, "Akun pemilik prospek tidak ditemukan.")
    doc = {
        "_id": str(uuid.uuid4()),
        "tg_user_id": body.tg_user_id,
        "username": body.username,
        "name": body.name,
        "owner_account_id": body.owner_account_id,
        "source": body.source,
        "status": "customer" if bot_user else "new",
        "bot_user_tid": body.tg_user_id if bot_user else None,
        "contact_allowed": False,
        "contact_count": 0,
        "last_contacted_at": None,
        "notes": body.notes,
        "created_at": now_iso(),
    }
    await db.prospects.insert_one(doc)
    return doc


@router.patch("/prospects/{prospect_id}")
async def prospect_update(prospect_id: str, payload: dict):
    allowed = {"username", "name", "status", "notes", "source", "contact_allowed"}
    data = {k: v for k, v in payload.items() if k in allowed}
    if "status" in data and data["status"] not in {"new", "contacted", "replied", "interested", "customer", "opt_out"}:
        raise HTTPException(400, "Status prospek tidak valid.")
    await db.prospects.update_one({"_id": prospect_id}, {"$set": data})
    return await db.prospects.find_one({"_id": prospect_id})


@router.get("/sources")
async def sources():
    return await db.traffic_sources.find({}).sort("created_at", -1).to_list(500)


@router.post("/sources")
async def source_create(body: SourceBody):
    code = body.code.strip().lower()
    if not code or not body.kind.strip():
        raise HTTPException(400, "Kode dan jenis source wajib diisi.")
    if await db.traffic_sources.find_one({"code": code}):
        raise HTTPException(409, "Source code sudah ada.")
    doc = {"_id": str(uuid.uuid4()), "code": code, "kind": body.kind.strip(), "label": body.label.strip(), "created_at": now_iso()}
    await db.traffic_sources.insert_one(doc)
    return doc
