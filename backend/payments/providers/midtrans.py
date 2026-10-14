"""Midtrans Core API sandbox only. Deterministic QRIS capabilities, no account discovery claim."""
import hashlib
import hmac
import json
import os
import httpx
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from .base import Provider
from ..models import now, money

class MidtransSandbox(Provider):
    def guard(self):
        if os.getenv("PHASE3_SANDBOX_ENABLED") != "true" or not self.credentials.get("server_key", "").startswith("SB-Mid-server-"):
            raise FulfillmentUnavailable("Approved Midtrans sandbox server key required")

    async def request(self, method, path, **kwargs):
        self.guard()
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            result = await http.request(method, "https://api.sandbox.midtrans.com/v2" + path, auth=(self.credentials["server_key"], ""), **kwargs)
            if result.status_code not in {200, 201, 404}:
                raise FulfillmentUnavailable("Midtrans sandbox request rejected")
            value = result.json()
            if not isinstance(value, dict):
                raise CommerceError("Malformed Midtrans response")
            return value

    async def connect(self):
        # An authenticated status probe returns 404 for an unknown test order;
        # 401 is never interpreted as a successful connection.
        result = await self.request("GET", "/sellerbottel-connection-probe/status")
        if str(result.get("status_code")) not in {"200", "404"}:
            raise CommerceError("Midtrans credential authentication failed")
        return await self.get_capabilities()

    async def get_capabilities(self):
        self.guard()
        return {"provider": "midtrans", "environment": "sandbox", "coverage": "SANDBOX", "merchant_reference": self.credentials.get("merchant_id"), "supported_methods": ["qris"], "refund_support": True, "cancel_support": True, "payout_support": False, "last_verified_at": now(), "discovery": "configured Core QRIS; merchant activation still required"}

    async def create_payment(self, payment):
        if payment["method"] != "qris":
            raise CommerceError("Midtrans sandbox adapter supports QRIS only")
        result = await self.request("POST", "/charge", json={"payment_type": "qris", "qris": {"acquirer": "gopay"}, "transaction_details": {"order_id": payment["provider_reference"], "gross_amount": payment["amount"]}})
        if str(result.get("status_code")) != "201" or result.get("order_id") != payment["provider_reference"] or money(result.get("gross_amount")) != payment["amount"] or not isinstance(result.get("transaction_id"), str):
            raise CommerceError("Malformed Midtrans charge response")
        return {"provider_payment_id": result["transaction_id"], "status": "pending", "gateway_fee": 0, "fee_requires_reconciliation": True, "instructions": {"label": "SANDBOX Midtrans", "qr_string": result.get("qr_string"), "actions": result.get("actions", [])}}

    async def get_payment(self, payment):
        result = await self.request("GET", "/" + payment["provider_reference"] + "/status")
        if result.get("order_id") != payment["provider_reference"] or money(result.get("gross_amount")) != payment["amount"]:
            raise CommerceError("Provider payment binding mismatch")
        return {"status": self.state(result), "provider_payment_id": result["transaction_id"]}

    def state(self, result):
        return {"settlement": "paid", "pending": "pending", "expire": "expired", "cancel": "cancelled", "deny": "failed", "failure": "failed"}.get(result.get("transaction_status"), "unsupported")

    def verify_webhook(self, body, signature):
        self.guard()
        try:
            value = json.loads(body)
            expected = hashlib.sha512((value["order_id"] + str(value["status_code"]) + value["gross_amount"] + self.credentials["server_key"]).encode()).hexdigest()
            if not hmac.compare_digest(expected, value.get("signature_key", "")):
                raise ValueError
            # No provider event ID exists in Core notifications: stable semantic digest.
            return {"event_id": hashlib.sha256(body).hexdigest(), "reference": value["order_id"], "provider_payment_id": value["transaction_id"], "amount": money(value["gross_amount"]), "currency": value.get("currency", "IDR"), "status": self.state(value)}
        except Exception:
            raise CommerceError("Invalid Midtrans webhook signature/payload") from None

    async def cancel_payment(self, payment):
        result = await self.request("POST", "/" + payment["provider_reference"] + "/cancel")
        if result.get("transaction_status") != "cancel":
            raise FulfillmentUnavailable("Cancellation needs reconciliation")
        return {"status": "cancelled"}

    async def refund(self, payment, refund):
        # Requires merchant activation; reject responses never imply success.
        result = await self.request("POST", "/" + payment["provider_payment_id"] + "/refund", json={"refund_key": refund["_id"], "amount": refund["amount"], "reason": "Approved seller refund"})
        if str(result.get("status_code")) != "200" or not result.get("refund_chargeback_id"):
            raise FulfillmentUnavailable("Refund requires provider reconciliation")
        return {"status": "succeeded", "provider_refund_id": str(result["refund_chargeback_id"])}
