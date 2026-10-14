from ..fulfillment_types import CommerceError, FulfillmentType
from .base import FulfillmentHandler


class FulfillmentRegistry:
    def __init__(self):
        self._handlers = {}

    def register(self, kind, handler):
        kind = FulfillmentType(kind)
        if kind in self._handlers:
            raise CommerceError("Fulfillment handler already registered")
        self._handlers[kind] = handler

    def get(self, kind):
        try:
            return self._handlers[FulfillmentType(kind)]
        except (ValueError, TypeError, KeyError):
            raise CommerceError("Unsupported fulfillment type") from None


class DigitalAutoHandler(FulfillmentHandler):
    async def process(self, context):
        if context.execute is None:
            raise CommerceError("Digital delivery adapter required")
        return "delivered" if await context.execute() else "delivery_failed"


class ServiceHandler(FulfillmentHandler):
    async def process(self, context):
        if context.execute is None:
            raise CommerceError("Service delivery adapter required")
        return "queued" if await context.execute() else "failed"


class PendingHandler(FulfillmentHandler):
    async def process(self, context):
        # C1 foundation only: never invoke digital delivery for these types.
        return "pending"


registry = FulfillmentRegistry()
registry.register(FulfillmentType.DIGITAL_AUTO, DigitalAutoHandler())
registry.register(FulfillmentType.SERVICE, ServiceHandler())
for kind in (FulfillmentType.DIGITAL_MANUAL, FulfillmentType.PHYSICAL, FulfillmentType.SUBSCRIPTION):
    registry.register(kind, PendingHandler())
