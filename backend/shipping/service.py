import hashlib
import json
from datetime import timedelta
from uuid import uuid4, uuid5, NAMESPACE_URL
from pymongo.errors import DuplicateKeyError
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from commerce.physical.models import address_snapshot
from payments.models import now, money
from payments.credentials import seal, unseal
from .providers import adapter

def fingerprint(items, address):
    return hashlib.sha256(json.dumps({"items": items, "address": address}, sort_keys=True, default=str).encode()).hexdigest()

def parcels(quote):
    result = []
    for item in quote["items"]:
        physical = item.get("physical_snapshot")
        if physical:
            weight = money(physical["weight"], positive=True)
            result.append({"variant_id": physical["variant_id"], "qty": item["qty"], "weight": weight, "dimensions": physical["dimensions"]})
    return result

async def config(database, tenant):
    doc = await database.shipping_settings.find_one({"_id": "main", "tenant_id": tenant}) or {"mode": "manual_shipping"}
    return doc

def shipping_adapter(database, tenant, doc):
    fields = unseal(f"shipping:{database.name}:{tenant}:{doc['credential_id']}", doc["secret"])
    return adapter(doc["provider"], fields)

async def save_config(database, tenant, data):
    mode = data["mode"]
    if mode not in {"manual_shipping", "integrated_shipping", "pickup_only"}:
        raise CommerceError("Invalid shipping mode")
    doc = {"_id": "main", "tenant_id": tenant, "mode": mode, "manual_shipping_fee": money(data.get("manual_shipping_fee", 0)), "origin": address_snapshot(data.get("origin")) if mode != "manual_shipping" else data.get("origin"), "updated_at": now()}
    if mode == "integrated_shipping":
        previous = await config(database, tenant)
        fields = data.get("credentials")
        if fields:
            courier = adapter(data["provider"], fields)
            version = str(uuid4())
            doc.update({"provider": courier.name, "credential_id": version, "secret": seal(f"shipping:{database.name}:{tenant}:{version}", fields), "coverage": "MOCKED"})
        elif previous.get("secret") and previous.get("provider") == data["provider"]:
            doc.update({k: previous[k] for k in ("provider", "credential_id", "secret", "coverage")})
        else:
            raise CommerceError("Shipping credentials required")
    await database.shipping_settings.replace_one({"_id": "main"}, doc, upsert=True)
    # C2 manual quote remains the source for legacy wallet and QRIS transport.
    await database.settings.update_one({"_id": "main"}, {"$set": {"manual_shipping_fee": doc["manual_shipping_fee"]}}, upsert=True)
    return {k: v for k, v in doc.items() if k != "secret"}

async def rates(database, tenant, customer_id, quote, address):
    doc = await config(database, tenant)
    address = address_snapshot(address)
    if doc["mode"] != "integrated_shipping":
        return {"mode": doc["mode"], "rates": [], "shipping_fee": 0 if doc["mode"] == "pickup_only" else money(quote["shipping_fee"])}
    package = parcels(quote)
    values = await shipping_adapter(database, tenant, doc).get_rates(doc["origin"], address, package)
    saved = []
    for value in values:
        rate = {"_id": str(uuid4()), "tenant_id": tenant, "customer_id": customer_id, "mode": "integrated_shipping", "provider": doc["provider"], "coverage": "MOCKED", "credential_id": doc["credential_id"], "credential_snapshot": doc["secret"], "origin": doc["origin"], "address": address, "parcels": package, "fingerprint": fingerprint(package, address), "created_at": now(), "expires_at": now() + timedelta(minutes=10), **value}
        money(rate["amount"])
        await database.shipping_rates.insert_one(rate.copy())
        saved.append({k: rate[k] for k in ("_id", "service", "label", "amount", "eta", "coverage", "expires_at")})
    return {"mode": doc["mode"], "rates": saved}

async def checkout_shipping(database, tenant, quote, address, rate_id, customer_id=None):
    doc = await config(database, tenant)
    basic = {"requires_shipping": True, "shipping_address": address_snapshot(address), "shipping_mode": doc["mode"]}
    if doc["mode"] == "manual_shipping":
        return {**basic, "shipping_fee": money(quote["shipping_fee"])}
    if doc["mode"] == "pickup_only":
        return {**basic, "shipping_fee": 0, "shipping_quote": {"mode": "pickup_only", "origin": doc["origin"]}}
    rate = await database.shipping_rates.find_one({"_id": rate_id, "tenant_id": tenant, "customer_id": customer_id})
    if not rate or rate["expires_at"].replace(tzinfo=now().tzinfo) <= now() or rate["credential_id"] != doc["credential_id"] or rate["fingerprint"] != fingerprint(parcels(quote), basic["shipping_address"]):
        raise CommerceError("Select a current shipping rate for this cart/address")
    # Credential snapshot is kept in a private order-side document, never sent
    # to the customer/order listing.
    await database.order_shipping_credentials.update_one({"_id": rate["_id"]}, {"$setOnInsert": {"secret": rate["credential_snapshot"], "credential_id": rate["credential_id"], "tenant_id": tenant}}, upsert=True)
    snapshot = {k: v for k, v in rate.items() if k not in {"credential_snapshot", "fingerprint", "customer_id", "expires_at"}}
    return {**basic, "shipping_fee": rate["amount"], "shipping_quote": snapshot}

async def create_shipment(database, platform, tenant, oid, fid):
    from commerce.physical.workflow import transition
    order = await database.purchases.find_one({"_id": oid, "tenant_id": tenant, "shipping_mode": "integrated_shipping"})
    record = await database.fulfillments.find_one({"_id": fid, "order_id": oid, "tenant_id": tenant, "type": "physical"})
    if not order or not record:
        raise CommerceError("Integrated shipment not found")
    sid = str(uuid5(NAMESPACE_URL, f"integrated-shipment:{database.name}:{tenant}:{fid}"))
    previous = await database.integrated_shipments.find_one({"_id": sid})
    if previous:
        if previous["status"] in {"created", "shipped", "delivered"}:
            await project(database, previous)
            return previous
        raise FulfillmentUnavailable("Shipment create is ambiguous; reconcile provider reference")
    if record["status"] != "ready_to_ship" or record.get("execution_status") != "done" or order["status"] not in {"paid", "physical_pending", "service_waiting"}:
        raise CommerceError("Paid ready-to-ship fulfillment required")
    saved = await database.order_shipping_credentials.find_one({"_id": order["shipping_quote"]["_id"], "tenant_id": tenant})
    private = {"provider": order["shipping_quote"]["provider"], "credential_id": saved["credential_id"], "secret": saved["secret"]}
    courier = shipping_adapter(database, tenant, private)
    intent = {"_id": sid, "tenant_id": tenant, "order_id": oid, "fulfillment_id": fid, "status": "create_unknown", "created_at": now(), "quote": order["shipping_quote"], "credentials": private}
    try:
        await database.integrated_shipments.insert_one(intent.copy())
    except DuplicateKeyError:
        raise FulfillmentUnavailable("Shipment initialization in progress") from None
    try:
        result = await courier.create_shipment(intent)
    except Exception:
        raise FulfillmentUnavailable("Shipment provider outcome unknown; reconcile before retry") from None
    if not result.get("provider_shipment_id") or not result.get("tracking_number") or result.get("status") != "created":
        raise CommerceError("Malformed shipment response; reconcile")
    await platform.shipping_routes.create_index([("provider", 1), ("provider_shipment_id", 1)], unique=True, name="shipping_provider_route")
    await platform.shipping_routes.insert_one({"_id": sid, "provider": courier.name, "provider_shipment_id": result["provider_shipment_id"], "tenant_id": tenant, "tenant_database": database.name, "provider_result": result})
    await database.integrated_shipments.update_one({"_id": sid}, {"$set": result})
    shipment = await database.integrated_shipments.find_one({"_id": sid})
    await project(database, shipment)
    return shipment

async def project(database, shipment):
    from commerce.physical.workflow import transition
    record = await database.fulfillments.find_one({"_id": shipment["fulfillment_id"], "tenant_id": shipment["tenant_id"]})
    if record["status"] == "ready_to_ship":
        await transition(shipment["order_id"], record["_id"], "shipped", carrier_name=shipment["carrier_name"], tracking_number=shipment["tracking_number"])
    if shipment["status"] == "delivered":
        await transition(shipment["order_id"], record["_id"], "delivered")
    await database.fulfillments.update_one({"_id": record["_id"], "tenant_id": shipment["tenant_id"]}, {"$set": {"shipment_snapshot.provider": shipment["quote"]["provider"], "shipment_snapshot.provider_shipment_id": shipment["provider_shipment_id"], "shipment_snapshot.coverage": "MOCKED"}})

async def event(platform, client, raw, signature):
    from bot_tenant_scope import BotTenantScope, use_bot_tenant
    try:
        hint = json.loads(raw)
    except Exception:
        raise CommerceError("Malformed shipping event") from None
    route = await platform.shipping_routes.find_one({"provider_shipment_id": hint.get("provider_shipment_id"), "provider": "mock_courier"})
    if not route:
        raise CommerceError("Unknown shipment route")
    registry = await platform.tenants.find_one({"_id": route["tenant_id"], "database_name": route["tenant_database"]})
    if not registry or registry.get("status") != "active":
        raise CommerceError("Shipment tenant unavailable")
    database = client[route["tenant_database"]]
    shipment = await database.integrated_shipments.find_one({"_id": route["_id"], "tenant_id": route["tenant_id"]})
    payload = shipping_adapter(database, route["tenant_id"], shipment["credentials"]).verify(raw, signature)
    if payload.get("status") not in {"shipped", "delivered"} or not isinstance(payload.get("event_id"), str) or not 1 <= len(payload["event_id"]) <= 100:
        raise CommerceError("Invalid tracking state")
    # Receipt journal + latest state are atomically persisted in shipment. A
    # later duplicate calls project(), repairing failures without regressing.
    old = next((e for e in shipment.get("events", []) if e["event_id"] == payload["event_id"]), None)
    if old and old != payload:
        raise CommerceError("Shipping event ID conflict")
    if not old:
        await database.integrated_shipments.update_one({"_id": shipment["_id"], "events.event_id": {"$ne": payload["event_id"]}}, {"$push": {"events": payload}})
    await database.integrated_shipments.update_one({"_id": shipment["_id"], **({"status": {"$ne": "delivered"}} if payload["status"] == "shipped" else {})}, {"$set": {"status": payload["status"]}})
    shipment = await database.integrated_shipments.find_one({"_id": shipment["_id"]})
    async with use_bot_tenant(BotTenantScope(tenant_id=registry["_id"], slug=registry["slug"], database_name=database.name, db_handle=database)):
        await project(database, shipment)
    return {"ok": True}
