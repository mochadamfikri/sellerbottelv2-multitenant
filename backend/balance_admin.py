"""Admin adjustments on existing wallets, with an atomic embedded audit receipt.

Mongo is standalone: balance and receipt commit in ONE document. The existing
balance_adjustments ledger is an idempotent projection, repaired by the worker.
"""
import hashlib
import math
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from auth import get_current_admin
from db import db

router = APIRouter(prefix="/api/admin/wallets", dependencies=[Depends(get_current_admin)])


class Adjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal["ADD", "SUBTRACT"]
    amount: float = Field(gt=0, le=1_000_000_000, allow_inf_nan=False)
    currency: Literal["IDR", "USD"] = "IDR"
    reason: str = Field(min_length=1, max_length=500)
    request_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value):
        if not value.strip():
            raise ValueError("Catatan wajib diisi")
        return value.strip()


async def wallet(target):
    customer = None
    if target.startswith("store:"):
        customer = await db.store_customers.find_one({"_id": target[6:]})
        if not customer:
            raise HTTPException(404, "Pengguna web tidak ditemukan")
        if not customer.get("telegram_id"):
            return db.store_customers, customer, customer
        user = await db.bot_users.find_one({"telegram_id": customer["telegram_id"]})
    elif target.startswith("bot:"):
        user = await db.bot_users.find_one({"_id": target[4:]})
    else:
        raise HTTPException(400, "Target wallet tidak valid")
    if not user:
        raise HTTPException(409, "Wallet Telegram tidak ditemukan; periksa tautan akun")
    return db.bot_users, user, customer


async def project(receipt):
    await db.balance_adjustments.update_one({"_id": receipt["_id"]}, {"$setOnInsert": receipt}, upsert=True)


async def repair_audits():
    for collection in (db.bot_users, db.store_customers):
        async for account in collection.find({"admin_balance_audit.0": {"$exists": True}}, {"admin_balance_audit": 1}):
            for receipt in account["admin_balance_audit"]:
                await project(receipt)


async def adjust(target, body, admin):
    key = hashlib.sha256((str(admin["_id"]) + ":" + target + ":" + body.request_id).encode()).hexdigest()
    signature = {"target": target, "currency": body.currency, "amount": body.amount,
                 "direction": body.direction, "reason": body.reason}
    previous = await db.balance_adjustments.find_one({"_id": key})
    if not previous:
        for collection in (db.bot_users, db.store_customers):
            owner = await collection.find_one({"admin_balance_audit._id": key}, {"admin_balance_audit": 1})
            if owner:
                previous = next(r for r in owner["admin_balance_audit"] if r["_id"] == key)
                break
    if previous:
        if previous.get("request") != signature:
            raise HTTPException(409, "Request ID sudah digunakan untuk penyesuaian lain")
        return {"ok": True, "adjustment": previous, "balance": previous["balance_after"], "replayed": True}
    precision = 0 if body.currency == "IDR" else 2
    if round(body.amount, precision) != body.amount:
        raise HTTPException(400, "IDR harus bulat; USD maksimal dua desimal")
    delta = body.amount if body.direction == "ADD" else -body.amount
    field = "balance_" + body.currency.lower()
    for _ in range(12):
        collection, account, customer = await wallet(target)
        found = next((r for r in account.get("admin_balance_audit", []) if r["_id"] == key), None)
        if found:
            if found.get("request") != signature:
                raise HTTPException(409, "Request ID sudah digunakan")
            return {"ok": True, "adjustment": found, "balance": found["balance_after"], "replayed": True}
        before = float(account.get(field) or 0)
        after = round(before + delta, max(precision, 2))
        if not math.isfinite(after) or after < 0:
            raise HTTPException(409, "Saldo tidak cukup atau tidak valid")
        receipt = {"_id": key, "type": "ADMIN_BALANCE_ADJUSTMENT", "request_id": body.request_id,
            "request": signature, "target_user_id": account["_id"], "wallet_collection": collection.name,
            "user_source": "WEB" if collection.name == "store_customers" else "BOT",
            "customer_id": customer["_id"] if customer else None, "user_tid": account.get("telegram_id"),
            "currency": body.currency, "amount": delta, "direction": body.direction,
            "balance_before": before, "balance_after": after, "admin_id": admin["_id"],
            "reason": body.reason, "created_at": datetime.now(timezone.utc).isoformat()}
        match = {"_id": account["_id"], field: account.get(field), "admin_balance_audit._id": {"$ne": key}}
        if collection.name == "store_customers":
            match["telegram_id"] = account.get("telegram_id")  # CAS against concurrent account linking
        result = await collection.update_one(match, {"$set": {field: after}, "$push": {"admin_balance_audit": receipt}})
        if result.modified_count:
            try:
                await project(receipt)
            except Exception:
                pass  # durable receipt remains on wallet; worker/history repairs projection
            return {"ok": True, "adjustment": receipt, "balance": after, "replayed": False}
    raise HTTPException(409, "Saldo sedang berubah. Coba lagi dengan request yang sama")


@router.post("/{target}/adjust")
async def adjust_route(target: str, body: Adjustment, admin: dict = Depends(get_current_admin)):
    return await adjust(target, body, admin)


@router.get("/{target}/history")
async def history(target: str, limit: int = Query(50, ge=1, le=200)):
    collection, account, customer = await wallet(target)
    clauses = [{"target_user_id": account["_id"]}]
    if account.get("telegram_id"):
        clauses.append({"user_tid": account["telegram_id"]})
    if customer:
        clauses.append({"customer_id": customer["_id"]})
    rows = await db.balance_adjustments.find({"$or": clauses}).sort("created_at", -1).limit(limit).to_list(limit)
    indexed = {r["_id"]: r for r in rows}
    for owner in (account, customer or {}):
        for receipt in owner.get("admin_balance_audit", []):
            indexed[receipt["_id"]] = receipt
    return sorted(indexed.values(), key=lambda r: str(r.get("created_at") or ""), reverse=True)[:limit]
