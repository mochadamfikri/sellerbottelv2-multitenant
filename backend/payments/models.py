from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from commerce.fulfillment_types import CommerceError

TRANSITIONS = {"created": {"pending", "failed", "cancelled", "paid", "expired"},
               "pending": {"paid", "expired", "failed", "cancelled"},
               "paid": {"partially_refunded", "refunded"},
               "partially_refunded": {"partially_refunded", "refunded"},
               "expired": set(), "failed": set(), "cancelled": set(), "refunded": set()}

def now():
    return datetime.now(timezone.utc)

def utc(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def money(value, *, positive=False):
    """IDR minor unit is one rupiah. Reject fractions instead of silently rounding."""
    try:
        result = Decimal(str(value))
        if isinstance(value, bool) or not result.is_finite() or result != result.to_integral_value() or result < (1 if positive else 0) or result > 10**12:
            raise ValueError
        return int(result)
    except (ValueError, InvalidOperation):
        raise CommerceError("Amount must be integer rupiah") from None

def public_payment(payment):
    return {k: payment.get(k) for k in ("_id", "order_id", "payment_mode", "provider", "method", "environment", "amount", "currency", "status", "provider_payment_id", "provider_reference", "expires_at", "paid_at", "cancelled_at", "refunded_amount", "created_at", "updated_at", "instructions", "reconciliation")}

async def ensure_indexes(database, platform):
    await database.order_payments.create_index("order_id", unique=True, name="payment_order_unique")
    await platform.payment_routes.create_index([("provider", 1), ("provider_reference", 1)], unique=True, name="payment_route_reference")
    await platform.payment_routes.create_index([("provider", 1), ("provider_payment_id", 1)], unique=True, partialFilterExpression={"provider_payment_id": {"$type": "string"}}, name="payment_route_external")
    await platform.payment_events.create_index([("route_id", 1), ("event_id", 1)], unique=True, name="payment_event_unique")
