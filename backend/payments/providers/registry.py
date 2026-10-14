from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from .base import MockProvider

SCHEMAS = {"kasera": ["api_key", "webhook_secret"], "midtrans": ["server_key", "client_key", "merchant_id", "webhook_secret"]}

def provider(name, environment, credentials):
    if name not in SCHEMAS:
        raise CommerceError("Unsupported provider")
    if environment == "mock":
        return MockProvider(name, environment, credentials)
    # Live execution is deliberately closed on this development machine.
    if environment == "sandbox":
        if name == "kasera":
            from .kasera import KaseraSandbox
            return KaseraSandbox(name, environment, credentials)
        from .midtrans import MidtransSandbox
        return MidtransSandbox(name, environment, credentials)
    raise CommerceError("Only mock/sandbox environments are allowed")
