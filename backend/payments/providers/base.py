from abc import ABC, abstractmethod
import hashlib
import hmac
import json
import os
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from ..models import now, utc

class Provider(ABC):
    def __init__(self, name, environment, credentials):
        self.name, self.environment, self.credentials = name, environment, credentials

    @abstractmethod
    async def connect(self): ...
    @abstractmethod
    async def get_capabilities(self): ...
    @abstractmethod
    async def create_payment(self, payment): ...
    @abstractmethod
    async def get_payment(self, payment): ...
    @abstractmethod
    def verify_webhook(self, body, signature): ...
    @abstractmethod
    async def cancel_payment(self, payment): ...
    @abstractmethod
    async def refund(self, payment, refund): ...

class MockProvider(Provider):
    """Explicit deterministic contract simulator; never authenticates a real merchant."""
    def validate(self):
        if os.getenv("PHASE3_MOCK_ENABLED") != "true":
            raise FulfillmentUnavailable("Mock payments are disabled")
        key = self.credentials.get("api_key") if self.name == "kasera" else self.credentials.get("server_key")
        if not key or not key.startswith("mock_") or not self.credentials.get("webhook_secret", "").startswith("mock_"):
            raise CommerceError("Mock credentials must start with mock_")

    async def connect(self):
        self.validate()
        return await self.get_capabilities()

    async def get_capabilities(self):
        self.validate()
        return {"provider": self.name, "environment": "mock", "coverage": "MOCKED", "merchant_reference": "mock-account", "supported_methods": ["qris", "va_bca", "va_bni"], "refund_support": True, "cancel_support": True, "payout_support": False, "last_verified_at": now(), "discovery": "deterministic mock contract"}

    async def create_payment(self, payment):
        self.validate()
        return {"provider_payment_id": "mock_" + payment["provider_reference"], "status": "pending", "instructions": {"label": "MOCK — tidak memindahkan uang", "reference": payment["provider_reference"]}, "gateway_fee": 0}

    async def get_payment(self, payment):
        # A mock does not invent a paid result. Only a signed event confirms it.
        self.validate()
        from datetime import datetime
        expiry = payment.get("expires_at")
        expiry = datetime.fromisoformat(expiry) if isinstance(expiry, str) else expiry
        expired = expiry and utc(expiry) <= now() and payment["status"] == "pending"
        return {"status": "expired" if expired else payment["status"], "provider_payment_id": payment.get("provider_payment_id"), "gateway_fee": 0}

    def verify_webhook(self, body, signature):
        self.validate()
        expected = hmac.new(self.credentials["webhook_secret"].encode(), body, hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
            raise CommerceError("Invalid webhook signature")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise CommerceError("Invalid webhook")
        return data

    async def cancel_payment(self, payment):
        self.validate()
        return {"status": "cancelled"}

    async def refund(self, payment, refund):
        self.validate()
        return {"status": "succeeded", "provider_refund_id": "mock_refund_" + refund["_id"]}
