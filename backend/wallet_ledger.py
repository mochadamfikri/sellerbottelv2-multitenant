"""Development-only, injected-DB tenant wallet ledger primitives.

Entries are append-only documents.  Callers supply a resolved tenant context;
no global database handle, transaction, or commit is used here.
"""
from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Mapping


EntryType = Literal["debit", "credit"]


def _context_tenant_id(context: Any) -> str:
    tenant_id = context.get("tenant_id") if isinstance(context, Mapping) else getattr(context, "tenant_id", None)
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("tenant context must provide tenant_id")
    return tenant_id


def _amount(value: Decimal | str | int) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount must be a finite positive decimal") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("amount must be a finite positive decimal")
    return amount


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def create_ledger_entry(
    db: Any,
    context: Any = None,
    *,
    tenant_id: str | None = None,
    entry_type: EntryType,
    amount: Decimal | str | int,
    currency: str,
    reference_id: str,
    idempotency_key: str,
    description: str = "",
) -> dict[str, Any]:
    """Append one immutable debit/credit entry, replaying a matching request.

    The injected ``db`` is the sole persistence dependency.  A repeated key
    returns its original entry only when its immutable request fields match.
    """
    context_id = _context_tenant_id(context)
    if tenant_id is not None and tenant_id != context_id:
        raise ValueError("tenant_id mismatch with tenant context")
    if entry_type not in ("debit", "credit"):
        raise ValueError("entry_type must be 'debit' or 'credit'")
    numeric_amount = _amount(amount)
    if not isinstance(currency, str) or not currency:
        raise ValueError("currency is required")
    if not isinstance(reference_id, str) or not reference_id:
        raise ValueError("reference_id is required")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise ValueError("idempotency_key is required")

    collection = db.wallet_ledger
    immutable_request = {
        "tenant_id": context_id, "entry_type": entry_type,
        "amount": str(numeric_amount), "currency": currency,
        "reference_id": reference_id, "description": description,
    }
    existing = await _maybe_await(collection.find_one({"tenant_id": context_id, "idempotency_key": idempotency_key}))
    if existing is not None:
        if existing.get("request") != immutable_request:
            raise ValueError("idempotency_key was already used with a different request")
        return {"entry": existing, "replayed": True}

    entry = {
        "entry_id": str(uuid.uuid4()), **immutable_request,
        "idempotency_key": idempotency_key, "request": immutable_request,
        "created_at": datetime.now(timezone.utc),
    }
    try:
        await _maybe_await(collection.insert_one(entry))
    except Exception as exc:
        # An index may enforce the same tenant/key uniqueness under races.
        replay = await _maybe_await(collection.find_one({"tenant_id": context_id, "idempotency_key": idempotency_key}))
        if replay is None:
            raise exc
        if replay.get("request") != immutable_request:
            raise ValueError("idempotency_key was already used with a different request") from exc
        return {"entry": replay, "replayed": True}
    return {"entry": entry, "replayed": False}


async def wallet_balance(db: Any, context: Any, *, currency: str) -> Decimal:
    """Calculate a tenant-scoped balance from immutable ledger entries."""
    tenant_id = _context_tenant_id(context)
    if not isinstance(currency, str) or not currency:
        raise ValueError("currency is required")
    balance = Decimal("0")
    cursor = db.wallet_ledger.find({"tenant_id": tenant_id, "currency": currency})
    if hasattr(cursor, "__aiter__"):
        async for entry in cursor:
            value = _amount(entry["amount"])
            balance += value if entry["entry_type"] == "credit" else -value
    else:
        for entry in await _maybe_await(cursor):
            value = _amount(entry["amount"])
            balance += value if entry["entry_type"] == "credit" else -value
    return balance
