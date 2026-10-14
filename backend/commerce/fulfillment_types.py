"""Canonical fulfillment classification, compatibility and safe domain errors."""
from enum import StrEnum


class CommerceError(ValueError):
    status_code = 422


class FulfillmentUnavailable(CommerceError):
    status_code = 503


class FulfillmentType(StrEnum):
    DIGITAL_AUTO = "digital_auto"
    DIGITAL_MANUAL = "digital_manual"
    SERVICE = "service"
    PHYSICAL = "physical"
    SUBSCRIPTION = "subscription"


OPERATIONAL_TYPES = frozenset({FulfillmentType.DIGITAL_AUTO, FulfillmentType.SERVICE})


def resolve_fulfillment_type(product):
    explicit = product.get("fulfillment_type")
    if explicit is not None:
        try:
            return FulfillmentType(explicit)
        except (ValueError, TypeError):
            raise CommerceError("Unsupported fulfillment type") from None
    kind = product.get("product_kind")
    delivery = product.get("delivery_type")
    if (kind is not None and not isinstance(kind, str)) or (delivery is not None and not isinstance(delivery, str)):
        raise CommerceError("Ambiguous legacy fulfillment classification")
    if kind == "service" or delivery == "service":
        return FulfillmentType.SERVICE
    if kind in {"physical", "subscription", "digital_manual"}:
        return FulfillmentType(kind)
    # Missing fields historically mean a legacy digital link/catalog item.
    if kind in (None, "", "digital") and delivery in (None, "", "inventory", "link", "file", "session", "license", "redeem_code", "account"):
        return FulfillmentType.DIGITAL_AUTO
    raise CommerceError("Ambiguous legacy fulfillment classification")


def require_operational(product):
    value = resolve_fulfillment_type(product)
    if value not in OPERATIONAL_TYPES:
        raise CommerceError("Fulfillment unavailable until a later commerce phase")
    return value


def canonical_product(product):
    value = resolve_fulfillment_type(product)
    if product.get("active", True) and value not in OPERATIONAL_TYPES:
        raise CommerceError("This fulfillment type cannot be activated in C1")
    return {**product, "fulfillment_type": value.value}


def uses_digital_inventory(product):
    return resolve_fulfillment_type(product) == FulfillmentType.DIGITAL_AUTO and bool(
        product.get("product_kind") == "digital" or product.get("delivery_type") == "inventory" or product.get("inventory_enabled"))


STATES = {
    FulfillmentType.DIGITAL_AUTO: {"reserved": {"delivering", "cancelled"}, "delivering": {"delivered", "delivery_failed"}, "delivered": set(), "delivery_failed": set(), "cancelled": set()},
    FulfillmentType.SERVICE: {"queued": {"processing", "completed", "failed", "cancelled"}, "processing": {"completed", "failed", "cancelled"}, "completed": set(), "failed": set(), "cancelled": set()},
    FulfillmentType.DIGITAL_MANUAL: {"pending": {"processing", "cancelled"}, "processing": {"delivered", "failed", "cancelled"}, "delivered": set(), "failed": set(), "cancelled": set()},
    FulfillmentType.PHYSICAL: {"pending": set()},
    FulfillmentType.SUBSCRIPTION: {"pending": set()},
}


def initial_status(kind):
    return {FulfillmentType.DIGITAL_AUTO: "reserved", FulfillmentType.SERVICE: "queued"}.get(FulfillmentType(kind), "pending")
