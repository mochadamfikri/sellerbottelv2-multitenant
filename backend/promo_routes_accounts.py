import uuid
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from promo_telegram import list_accounts, begin_login, verify_login, revoke_account, check_account
from promo_service import now_iso
from db import db

router = APIRouter()

class LoginStartBody(BaseModel):
    phone: str = Field(min_length=7, max_length=32)

class LoginVerifyBody(BaseModel):
    code: str = Field(min_length=3, max_length=16)
    password: str | None = Field(default=None, max_length=256)

class ManualProspectBody(BaseModel):
    tg_user_id: int
    username: str = ""
    name: str = ""
    notes: str = ""

@router.get("/accounts")
async def accounts():
    return await list_accounts()

@router.post("/accounts/login/start")
async def account_login_start(body: LoginStartBody):
    account_id = str(uuid.uuid4())
    try:
        result = await begin_login(account_id, body.phone)
        result["account_id"] = account_id
        return result
    except Exception as exc:
        raise HTTPException(400, str(exc))

@router.post("/accounts/login/{account_id}/verify")
async def account_login_verify(account_id: str, body: LoginVerifyBody):
    try:
        return await verify_login(account_id, body.code, body.password)
    except Exception as exc:
        raise HTTPException(400, str(exc))

@router.post("/accounts/{account_id}/check")
async def account_check(account_id: str):
    try:
        return await check_account(account_id)
    except Exception as exc:
        raise HTTPException(400, str(exc))

@router.delete("/accounts/{account_id}")
async def account_revoke(account_id: str):
    try:
        return await revoke_account(account_id)
    except Exception as exc:
        raise HTTPException(400, str(exc))

@router.post("/prospects/manual")
async def manual_prospect(body: ManualProspectBody):
    existing = await db.prospects.find_one({"tg_user_id": body.tg_user_id})
    if existing:
        raise HTTPException(409, "Telegram ID sudah tercatat sebagai prospek.")
    bot_user = await db.bot_users.find_one({"telegram_id": body.tg_user_id})
    doc = {
        "_id": str(uuid.uuid4()),
        "tg_user_id": body.tg_user_id,
        "username": body.username,
        "name": body.name,
        "owner_account_id": None,
        "source": {"kind": "manual", "label": "Manual"},
        "status": "customer" if bot_user else "new",
        "contact_allowed": False,
        "bot_user_tid": body.tg_user_id if bot_user else None,
        "contact_count": 0,
        "last_contacted_at": None,
        "notes": body.notes,
        "created_at": now_iso(),
    }
    await db.prospects.insert_one(doc)
    return doc
