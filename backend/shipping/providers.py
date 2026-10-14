from abc import ABC, abstractmethod
import hashlib
import hmac
import json
import os
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from payments.models import money

class ShippingProvider(ABC):
    @abstractmethod
    async def get_rates(self, origin, address, parcels): ...
    @abstractmethod
    async def create_shipment(self, intent): ...
    @abstractmethod
    async def cancel_shipment(self, shipment): ...
    @abstractmethod
    async def track_shipment(self, shipment): ...

class MockShipping(ShippingProvider):
    name = "mock_courier"
    def __init__(self, fields):
        if os.getenv("PHASE3_MOCK_ENABLED") != "true" or not fields.get("api_key", "").startswith("mock_") or not fields.get("webhook_secret", "").startswith("mock_"):
            raise FulfillmentUnavailable("Approved mock shipping credentials required")
        self.fields = fields

    async def get_rates(self, origin, address, parcels):
        if not origin or not address or not parcels or any(p["weight"] <= 0 for p in parcels):
            raise CommerceError("Origin/address and positive parcel weight required")
        weight = sum(p["weight"] * p["qty"] for p in parcels)
        # Contract simulator, not a claim of live courier pricing.
        base = 5000 + ((weight + 999) // 1000) * 1000
        return [{"service": "REG", "label": "Mock Regular", "amount": money(base), "eta": "2–3 hari (simulasi)"}, {"service": "EXP", "label": "Mock Express", "amount": money(base + 5000), "eta": "1 hari (simulasi)"}]

    async def create_shipment(self, intent):
        return {"provider_shipment_id": "mock_ship_" + intent["_id"], "tracking_number": "MOCK-" + intent["_id"][:12], "carrier_name": "Mock Courier", "status": "created"}

    async def cancel_shipment(self, shipment):
        return {"status": "cancelled"}

    async def track_shipment(self, shipment):
        return {"status": shipment["status"]}

    def verify(self, body, signature):
        expected = hmac.new(self.fields["webhook_secret"].encode(), body, hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
            raise CommerceError("Invalid shipping event signature")
        return json.loads(body)

def adapter(name, fields):
    if name != "mock_courier":
        raise CommerceError("Shipping provider unsupported")
    return MockShipping(fields)
