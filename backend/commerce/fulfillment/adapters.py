"""Channel adapters reuse V2 delivery, without owning wallets or reservations."""
from candidate_readonly import assert_service_writable
from ..fulfillment_types import FulfillmentType, FulfillmentUnavailable, uses_digital_inventory
from ..order_items import product_for_line
from .router import route_item, ensure_order_fulfillments


async def fulfill_bot_line(order, line, product, *, chat_id, user, lang,
                           inventory_items=None, send_message_fn=None, send_document_fn=None,
                           queue_service_fn=None, inventory_delivery_fn=None, product_delivery_fn=None):
    assert_service_writable("fulfillment.fulfill_bot_line")
    from bot import deliver_inventory, deliver_product
    deliver_inventory = inventory_delivery_fn or deliver_inventory
    deliver_product = product_delivery_fn or deliver_product
    from inventory import decrypt_items
    from db import db
    product = product_for_line(line, product)
    async def execute():
        if line["fulfillment_type"] == FulfillmentType.SERVICE:
            if queue_service_fn is not None:
                await queue_service_fn(chat_id, user, product, order, lang)
            return True
        if uses_digital_inventory(product):
            records = inventory_items
            same_product = [row for row in order["items"] if row["product_id"] == line["product_id"]]
            if records is None or len(same_product) > 1:
                offset = 0
                for row in same_product:
                    if row["line_id"] == line["line_id"]:
                        break
                    offset += row["qty"]
                records = await db.inventory_items.find({"order_id": order["_id"], "product_id": line["product_id"], "status": "sold"}).sort("_id", 1).skip(offset).limit(line["qty"]).to_list(line["qty"])
            if len(records) != line["qty"]:
                return False
            options = {}
            if send_message_fn is not None: options["send_message_fn"] = send_message_fn
            if send_document_fn is not None: options["send_document_fn"] = send_document_fn
            return await deliver_inventory(chat_id, product, decrypt_items(records), **options)
        ok = True
        for _ in range(line["qty"]):
            options = {}
            if send_message_fn is not None: options["send_message_fn"] = send_message_fn
            if send_document_fn is not None: options["send_document_fn"] = send_document_fn
            ok = await deliver_product(chat_id, product, lang, **options) and ok
        return ok
    try:
        return await route_item(order, line, execute)
    except FulfillmentUnavailable:
        return "delivery_failed"  # Preserve V2 channel failure/notification behavior.


async def fulfill_web_order(order):
    assert_service_writable("fulfillment.fulfill_web_order")
    from db import db
    await ensure_order_fulfillments(order)
    states = []
    for line in order.get("items") or []:
        current = await db.products.find_one({"_id": line["product_id"]})
        product = product_for_line(line, current)
        async def execute(line=line, product=product, current=current):
            if line["fulfillment_type"] == FulfillmentType.SERVICE:
                return True
            if uses_digital_inventory(product):
                return await db.inventory_items.count_documents({"order_id": order["_id"], "product_id": line["product_id"], "status": "sold"}) >= sum(row["qty"] for row in order["items"] if row["product_id"] == line["product_id"])
            return current is not None
        states.append(await route_item(order, line, execute))
    return states
