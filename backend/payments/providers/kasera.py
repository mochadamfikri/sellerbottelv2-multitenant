"""Kasera test-mode HTTP adapter. Official docs: pay.kasera.id/en/docs/api.

No undocumented refund/cancel/payout endpoints are invented.
"""
import hashlib
import hmac
import json
import os
import time
import httpx
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from .base import Provider
from ..models import now, money

class KaseraSandbox(Provider):
    def guard(self):
        if os.getenv("PHASE3_SANDBOX_ENABLED") != "true" or not self.credentials.get("api_key", "").startswith("kp_test_"):
            raise FulfillmentUnavailable("Approved Kasera sandbox configuration required")

    async def request(self, method, path, **kwargs):
        self.guard()
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            response = await http.request(method, "https://pay.kasera.id/v1" + path, headers={"Authorization": "Bearer " + self.credentials["api_key"], **kwargs.pop("headers", {})}, **kwargs)
            if response.status_code not in {200, 201}:
                raise FulfillmentUnavailable("Kasera sandbox request rejected")
            result = response.json()
            if not isinstance(result, dict):
                raise CommerceError("Malformed provider response")
            return result

    async def connect(self):
        return await self.get_capabilities()

    async def get_capabilities(self):
        result = await self.request("GET", "/payment_methods")
        methods = result.get("data")
        if not isinstance(methods, list) or not methods or any(not isinstance(m, dict) or not isinstance(m.get("code"), str) for m in methods):
            raise CommerceError("Invalid Kasera discovery response")
        return {"provider": "kasera", "environment": "sandbox", "coverage": "SANDBOX", "merchant_reference": None, "supported_methods": [m["code"] for m in methods], "method_details": methods, "refund_support": False, "cancel_support": False, "payout_support": False, "last_verified_at": now(), "discovery": "authenticated payment_methods; account-info API unavailable"}

    async def create_payment(self, payment):
        result = await self.request("POST", "/transactions", headers={"Idempotency-Key": payment["provider_reference"]}, json={"amount": payment["amount"], "external_id": payment["provider_reference"], "payment_methods": [payment["method"]], "customer": {"name": "Store customer"}, "send_receipt": False})
        if result.get("livemode") is not False or result.get("amount") != payment["amount"] or result.get("currency") != "IDR" or not isinstance(result.get("id"), str) or result.get("status") != "pending":
            raise CommerceError("Malformed Kasera test payment")
        return {"provider_payment_id": result["id"], "status": "pending", "gateway_fee": money(result.get("fee", 0)), "instructions": {"label": "SANDBOX Kasera", "checkout_url": result.get("checkout_url"), "instrument": result.get("payment")}, "expires_at": result.get("expires_at")}

    async def get_payment(self, payment):
        from urllib.parse import quote
        if not payment.get("provider_payment_id"):
            raise FulfillmentUnavailable("Missing provider ID; reconcile create by reference manually")
        result = await self.request("GET", "/transactions/" + quote(payment["provider_payment_id"], safe=""))
        if result.get("livemode") is not False or result.get("external_id") != payment["provider_reference"] or result.get("amount") != payment["amount"]:
            raise CommerceError("Provider payment binding mismatch")
        return {"status": {"succeeded": "paid", "canceled": "cancelled"}.get(result.get("status"), result.get("status")), "provider_payment_id": result["id"], "gateway_fee": money(result["fee"])}

    def verify_webhook(self, body, signature):
        self.guard()
        try:
            parts = signature.split(",")
            timestamp = next(p[2:] for p in parts if p.startswith("t="))
            if abs(time.time() - int(timestamp)) > 300:
                raise ValueError
            expected = hmac.new(self.credentials["webhook_secret"].encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
            if not any(hmac.compare_digest(expected, p[3:]) for p in parts if p.startswith("v1=")):
                raise ValueError
            event = json.loads(body)
            data = event["data"]
            if event.get("livemode") is not False:
                raise ValueError
            return {"event_id": event["id"], "reference": data["external_id"], "provider_payment_id": data["payment_request_id"], "amount": data["amount"], "currency": data["currency"], "status": {"succeeded": "paid"}.get(data["status"], data["status"])}
        except Exception:
            raise CommerceError("Invalid Kasera webhook signature/payload") from None

    async def cancel_payment(self, payment):
        raise CommerceError("Kasera API cancellation unsupported; wait for confirmed expiry")

    async def refund(self, payment, refund):
        return {"status": "manual_refund_required"}
