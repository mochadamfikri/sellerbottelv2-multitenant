"""C2 regression: standalone-Mongo atomic journal, checkout saga and shipments."""
import asyncio
import base64
from unittest.mock import AsyncMock
import pytest
from mongomock_motor import AsyncMongoMockClient
from cryptography.fernet import Fernet
from commerce.fulfillment_types import CommerceError, FulfillmentUnavailable
from commerce.physical.models import VariantBody, create_variant, address_snapshot, normalize_cart
from commerce.physical.stock import PhysicalStock, ensure_indexes

ADDRESS = {"recipient_name":"Buyer", "phone":"081234567890", "address_line_1":"Jalan Testing 12", "city":"Bandung", "province":"Jawa Barat", "postal_code":"40111"}

@pytest.fixture
def physical(monkeypatch):
    import db
    database = AsyncMongoMockClient().physical_test
    monkeypatch.setattr(db,"_default_db",database)
    monkeypatch.setenv("INVENTORY_ENCRYPTION_KEY",Fernet.generate_key().decode())
    monkeypatch.setenv("GOPAY_ENABLED","true")
    monkeypatch.setattr("stock_monitor.schedule_stock_scan",lambda *args:None)
    monkeypatch.setattr("services.notify_transaction_channel_safely",AsyncMock())
    monkeypatch.setattr("services.notify_admin",AsyncMock())
    monkeypatch.setattr("storefront_routes.send_order_completion_email",AsyncMock(return_value=False))
    async def setup():
        await database.settings.insert_one({"_id":"main","rate_mode":"manual","manual_rate":16000,"manual_shipping_fee":5000,"store_qris_enabled":True})
        await database.products.insert_one({"_id":"physical","name":"Hoodie original","price_idr":10000,"active":True,"fulfillment_type":"physical","product_kind":"physical","requires_shipping":True})
        await database.store_customers.insert_one({"_id":"customer","balance_idr":100000,"currency":"IDR","email":""})
        variant = await create_variant(database,"physical",VariantBody(sku="hoodie-l",option_values={"color":"Black","size":"L"},price_override=12000,weight=300))
        await PhysicalStock(database).move(variant["_id"],"RECEIVE",5,reference_id="initial-stock",reason="Opening stock")
        return variant
    variant=asyncio.run(setup())
    return database,variant


def test_variant_sku_normalized_unique_and_stable(physical):
    database,variant=physical
    async def run():
        assert variant["sku"]=="HOODIE-L" and variant["available"]==0
        with pytest.raises(CommerceError): await create_variant(database,"physical",VariantBody(sku="HoOdIe-L"))
        assert (await database.physical_variants.index_information())["physical_sku_unique"]["unique"]
    asyncio.run(run())

@pytest.mark.parametrize("sku",["", "has space", "<bad>", "/path"])
def test_invalid_sku_rejected(sku):
    with pytest.raises(ValueError):VariantBody(sku=sku)

@pytest.mark.parametrize("field",["recipient_name","phone","address_line_1","city","province","postal_code"])
def test_address_required_fields(field):
    value={**ADDRESS};value.pop(field)
    with pytest.raises(CommerceError):address_snapshot(value)

@pytest.mark.parametrize("postal",["abcd","1234","123456"])
def test_indonesia_postal_validation(postal):
    with pytest.raises(CommerceError):address_snapshot({**ADDRESS,"postal_code":postal})


def test_same_sku_separate_databases_and_variant_ownership(physical):
    database,variant=physical
    async def run():
        other=database.client.other
        await other.products.insert_one({"_id":"physical","fulfillment_type":"physical"})
        another=await create_variant(other,"physical",VariantBody(sku=variant["sku"]))
        assert another["sku"]==variant["sku"]
        with pytest.raises(CommerceError):await PhysicalStock(other).get(variant["_id"])
        with pytest.raises(CommerceError):await create_variant(database,"foreign",VariantBody(sku="new"))
    asyncio.run(run())

@pytest.mark.parametrize("kind,qty,hand,reserved",[("RESERVATION",2,5,2),("DAMAGE",2,3,0),("ADJUSTMENT",-2,3,0),("RECEIVE",2,7,0)])
def test_stock_movement_and_auditable_invariants(physical,kind,qty,hand,reserved):
    database,variant=physical
    async def run():
        stock=PhysicalStock(database)
        await stock.move(variant["_id"],kind,qty,reference_id="movement")
        value=await stock.get(variant["_id"])
        assert (value["on_hand"],value["reserved"])==(hand,reserved)
        assert value["on_hand"]==sum(e["delta_on_hand"] for e in value["stock_events"])
        assert value["reserved"]==sum(e["delta_reserved"] for e in value["stock_events"])
        assert await database.stock_movements.count_documents({})==2
    asyncio.run(run())


def test_reserve_release_sale_idempotent_and_compensating_return(physical):
    database,variant=physical
    async def run():
        stock=PhysicalStock(database)
        for _ in range(2):await stock.move(variant["_id"],"RESERVATION",2,reference_id="release-line")
        for _ in range(2):await stock.move(variant["_id"],"RELEASE",2,reference_id="release-line")
        await stock.move(variant["_id"],"RESERVATION",1,reference_id="sale-line")
        for _ in range(2):await stock.move(variant["_id"],"SALE",1,reference_id="sale-line")
        for _ in range(2):await stock.move(variant["_id"],"RETURN",1,reference_id="sale-line")
        value=await stock.get(variant["_id"])
        assert (value["on_hand"],value["reserved"])==(5,0)
        assert await database.stock_movements.count_documents({})==6
        with pytest.raises(CommerceError):await stock.move(variant["_id"],"SALE",2,reference_id="release-line")
    asyncio.run(run())

@pytest.mark.parametrize("kind,quantity",[("RESERVATION",6),("DAMAGE",6),("ADJUSTMENT",-6),("RECEIVE",0),("RECEIVE",True)])
def test_negative_available_and_invalid_quantities_rejected(physical,kind,quantity):
    database,variant=physical
    async def run():
        with pytest.raises(CommerceError):await PhysicalStock(database).move(variant["_id"],kind,quantity,reference_id="invalid")
        assert (await database.physical_variants.find_one({"_id":variant["_id"]}))["on_hand"]==5
    asyncio.run(run())


def test_concurrent_last_unit_no_oversell(physical):
    database,variant=physical
    async def run():
        stock=PhysicalStock(database)
        await stock.move(variant["_id"],"DAMAGE",4,reference_id="reduce")
        results=await asyncio.gather(*(stock.move(variant["_id"],"RESERVATION",1,reference_id=f"buyer-{i}") for i in range(10)),return_exceptions=True)
        assert sum(isinstance(result,dict) for result in results)==1
        value=await stock.get(variant["_id"])
        assert value["on_hand"]==value["reserved"]==1
    asyncio.run(run())


def test_ledger_projection_failure_is_repaired_without_double_stock(physical,monkeypatch):
    database,variant=physical
    async def run():
        stock=PhysicalStock(database)
        original=stock.project
        async def fail_after_commit(value):
            if any(e["reference_id"]=="projection-failure" for e in value.get("stock_events",[])):
                raise RuntimeError("write outage")
            await original(value)
        with monkeypatch.context() as patch:
            patch.setattr(stock,"project",fail_after_commit)
            with pytest.raises(RuntimeError):await stock.move(variant["_id"],"RECEIVE",2,reference_id="projection-failure")
        await stock.move(variant["_id"],"RECEIVE",2,reference_id="projection-failure")
        assert (await stock.get(variant["_id"]))["on_hand"]==7
        assert await database.stock_movements.count_documents({"reference_id":"projection-failure"})==1
    asyncio.run(run())


def test_cart_preserves_two_variants_and_merges_exact_duplicates():
    cart=normalize_cart([{"pid":"p","variant_id":"a","qty":1},{"pid":"p","variant_id":"b","qty":1},{"pid":"p","variant_id":"a","qty":1}])
    assert cart==[{"pid":"p","variant_id":"a","qty":2},{"pid":"p","variant_id":"b","qty":1}]


def test_physical_wallet_checkout_shipping_and_immutable_snapshot(physical):
    database,variant=physical
    async def run():
        from checkout import execute_checkout
        from storefront_routes import _finalize_store_balance_order
        user=await database.store_customers.find_one({"_id":"customer"})
        result=await execute_checkout({**user,"customer_id":"customer"},[{"pid":"physical","variant_id":variant["_id"],"qty":2}],purchase_source="WEB",shipping_address=ADDRESS)
        assert result["ok"],result
        order=result["order"]
        assert order["total"]==29000 and order["shipping_fee"]==5000
        assert order["shipping_address"]["country"]=="ID"
        line=order["items"][0]
        assert line["sku"]=="HOODIE-L" and line["variant_options"]["size"]=="L" and line["weight"]==300
        await database.products.update_one({"_id":"physical"},{"$set":{"name":"Changed","price_idr":99999}})
        await database.physical_variants.update_one({"_id":variant["_id"]},{"$set":{"option_values":{"size":"S"},"weight":1000}})
        await _finalize_store_balance_order(order["_id"])
        saved=await database.purchases.find_one({"_id":order["_id"]})
        assert saved["status"]=="physical_pending" and saved["items"][0]==line
        stock=await PhysicalStock(database).get(variant["_id"])
        assert (stock["on_hand"],stock["reserved"])==(3,0)
        assert (await database.store_customers.find_one({"_id":"customer"}))["balance_idr"]==71000
    asyncio.run(run())

@pytest.mark.parametrize("mode",["no-address","invalid-variant","inactive-variant","bot"])
def test_checkout_validation_before_payment(physical,mode):
    database,variant=physical
    async def run():
        from checkout import execute_checkout
        if mode=="inactive-variant":await database.physical_variants.update_one({"_id":variant["_id"]},{"$set":{"active":False}})
        user=await database.store_customers.find_one({"_id":"customer"})
        kwargs={"purchase_source":"BOT" if mode=="bot" else "WEB","shipping_address":None if mode=="no-address" else ADDRESS}
        try:
            result=await execute_checkout({**user,"customer_id":"customer"},[{"pid":"physical","variant_id":"foreign" if mode=="invalid-variant" else variant["_id"],"qty":1}],**kwargs)
            assert not result["ok"]
        except CommerceError:pass
        assert (await database.store_customers.find_one({"_id":"customer"}))["balance_idr"]==100000
        assert (await PhysicalStock(database).get(variant["_id"]))["reserved"]==0
    asyncio.run(run())


def test_fulfillment_insert_failure_rolls_back_physical_stock_and_wallet(physical,monkeypatch):
    database,variant=physical
    monkeypatch.setattr("checkout.ensure_order_fulfillments",AsyncMock(side_effect=RuntimeError("insert failed")))
    async def run():
        from checkout import execute_checkout
        user=await database.store_customers.find_one({"_id":"customer"})
        result=await execute_checkout({**user,"customer_id":"customer"},[{"pid":"physical","variant_id":variant["_id"],"qty":1}],purchase_source="WEB",shipping_address=ADDRESS)
        assert not result["ok"]
        assert (await database.store_customers.find_one({"_id":"customer"}))["balance_idr"]==100000
        stock=await PhysicalStock(database).get(variant["_id"])
        assert (stock["on_hand"],stock["reserved"])==(5,0)
        assert [e["type"] for e in stock["stock_events"]]==["RECEIVE","RESERVATION","RELEASE"]
    asyncio.run(run())


def test_qris_order_insert_failure_releases_reserved_stock(physical,monkeypatch):
    database,variant=physical
    collection_type = type(database.purchases)
    original_insert = collection_type.insert_one
    attempted = []
    async def failing_insert(self, document, *args, **kwargs):
        if self.name == "purchases":
            attempted.append(True)
            raise RuntimeError("order insert failed")
        return await original_insert(self, document, *args, **kwargs)
    monkeypatch.setattr(collection_type,"insert_one",failing_insert)
    monkeypatch.setattr("direct_checkout._run_node",lambda *args:{"image_base64":base64.b64encode(b"mock-qr").decode()})
    async def run():
        from direct_checkout import create_store_qris_order
        user=await database.store_customers.find_one({"_id":"customer"})
        with pytest.raises(RuntimeError, match="order insert failed"):await create_store_qris_order(user,[{"pid":"physical","variant_id":variant["_id"],"qty":1}],shipping_address=ADDRESS)
        assert attempted == [True]
        stock=await PhysicalStock(database).get(variant["_id"])
        assert (stock["on_hand"],stock["reserved"])==(5,0)
    asyncio.run(run())


def test_duplicate_qris_success_and_manual_shipment(physical,monkeypatch):
    database,variant=physical
    monkeypatch.setattr("direct_checkout._run_node",lambda *args:{"image_base64":base64.b64encode(b"mock-qr").decode()})
    async def run():
        from direct_checkout import create_store_qris_order,finalize_qris_order
        from commerce.physical.workflow import transition
        user=await database.store_customers.find_one({"_id":"customer"})
        result=await create_store_qris_order(user,[{"pid":"physical","variant_id":variant["_id"],"qty":1}],shipping_address=ADDRESS,idempotency_key="checkout-idempotency")
        order=result["order"]
        assert (await PhysicalStock(database).get(variant["_id"]))["reserved"]==1
        assert await finalize_qris_order(order["_id"],"mock-tx")
        assert not await finalize_qris_order(order["_id"],"mock-tx")
        record=await database.fulfillments.find_one({"order_id":order["_id"]})
        with pytest.raises(CommerceError):await transition(order["_id"],record["_id"],"delivered")
        for state in ("packing","ready_to_ship","shipped","delivered"):
            kwargs={"carrier_name":"Manual carrier","tracking_number":"TRACK123"} if state=="shipped" else {}
            await transition(order["_id"],record["_id"],state,**kwargs)
            await transition(order["_id"],record["_id"],state,**kwargs)
        shipment=await database.shipments.find_one({"fulfillment_id":record["_id"]})
        assert shipment["status"]=="delivered" and shipment["tracking_number"]=="TRACK123"
        assert (await database.purchases.find_one({"_id":order["_id"]}))["status"]=="delivered"
        assert await database.stock_movements.count_documents({"type":"SALE"})==1
    asyncio.run(run())


def test_mixed_wallet_one_payment_three_fulfillments_and_partial_delivery(physical):
    database,variant=physical
    async def run():
        from checkout import execute_checkout
        from storefront_routes import _finalize_store_balance_order
        from order_fulfillment import fulfillment
        from commerce.fulfillment.router import complete_service_records
        from commerce.physical.workflow import transition, refresh_order
        from commerce.fulfillment.router import current_repository
        await database.products.insert_many([
            {"_id":"digital","name":"Digital","active":True,"price_idr":1000,"delivery_type":"link","content":"synthetic-content"},
            {"_id":"service","name":"Service","active":True,"price_idr":2000,"delivery_type":"service","product_kind":"service"}])
        user=await database.store_customers.find_one({"_id":"customer"})
        result=await execute_checkout({**user,"customer_id":"customer"},[{"pid":"digital","qty":1},{"pid":"service","qty":1},{"pid":"physical","variant_id":variant["_id"],"qty":1}],purchase_source="WEB",shipping_address=ADDRESS)
        assert result["ok"],result
        order=result["order"]
        assert order["total"]==20000 and len(order["items"])==3
        await _finalize_store_balance_order(order["_id"])
        saved=await database.purchases.find_one({"_id":order["_id"]})
        assert saved["status"]=="service_waiting"
        data=await fulfillment(saved)
        assert len(data["products"])==1 and data["products"][0]["accounts"]==[{"Informasi produk":"synthetic-content"}]
        assert await database.fulfillments.count_documents({"order_id":order["_id"]})==3
        await complete_service_records(saved)
        await refresh_order(current_repository(),order["_id"])
        assert (await database.purchases.find_one({"_id":order["_id"]}))["status"]!="delivered"
        physical_record=await database.fulfillments.find_one({"type":"physical","order_id":order["_id"]})
        for state in ("packing","ready_to_ship","shipped","delivered"):
            await transition(order["_id"],physical_record["_id"],state,**({"carrier_name":"Manual","tracking_number":"MIXED-1"} if state=="shipped" else {}))
        assert (await database.purchases.find_one({"_id":order["_id"]}))["status"]=="delivered"
        assert (await database.store_customers.find_one({"_id":"customer"}))["balance_idr"]==80000
    asyncio.run(run())


def test_expiry_repeated_release_and_cancellation_compensates_sale(physical,monkeypatch):
    database,variant=physical
    monkeypatch.setattr("direct_checkout._run_node",lambda *args:{"image_base64":base64.b64encode(b"qr").decode()})
    async def run():
        from direct_checkout import create_store_qris_order,expire_qris_orders,finalize_qris_order
        from datetime import datetime,timedelta,timezone
        from commerce.physical.workflow import transition
        user=await database.store_customers.find_one({"_id":"customer"})
        result=await create_store_qris_order(user,[{"pid":"physical","variant_id":variant["_id"],"qty":1}],shipping_address=ADDRESS)
        order=result["order"]
        await database.purchases.update_one({"_id":order["_id"]},{"$set":{"expires_at":(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()}})
        await expire_qris_orders();await expire_qris_orders()
        assert (await PhysicalStock(database).get(variant["_id"]))["reserved"]==0
        assert await database.stock_movements.count_documents({"type":"RELEASE"})==1
        result=await create_store_qris_order(user,[{"pid":"physical","variant_id":variant["_id"],"qty":1}],shipping_address=ADDRESS)
        assert await finalize_qris_order(result["order"]["_id"],"paid")
        record=await database.fulfillments.find_one({"order_id":result["order"]["_id"]})
        await transition(record["order_id"],record["_id"],"cancelled")
        await transition(record["order_id"],record["_id"],"cancelled")
        assert (await PhysicalStock(database).get(variant["_id"]))["on_hand"]==5
        assert await database.stock_movements.count_documents({"type":"RETURN"})==1
    asyncio.run(run())


def test_shipment_projection_outage_recoverable_and_never_regresses(physical,monkeypatch):
    database,variant=physical
    async def run():
        from checkout import execute_checkout
        from storefront_routes import _finalize_store_balance_order
        from commerce.physical import workflow
        from commerce.fulfillment.router import current_repository
        user=await database.store_customers.find_one({"_id":"customer"})
        result=await execute_checkout({**user,"customer_id":"customer"},[{"pid":"physical","variant_id":variant["_id"],"qty":1}],purchase_source="WEB",shipping_address=ADDRESS)
        oid=result["order"]["_id"];await _finalize_store_balance_order(oid)
        record=await database.fulfillments.find_one({"order_id":oid});fid=record["_id"]
        for state in ("packing","ready_to_ship"):await workflow.transition(oid,fid,state)
        with monkeypatch.context() as patch:
            patch.setattr(workflow,"project_shipment",AsyncMock(side_effect=RuntimeError("shipment outage")))
            with pytest.raises(RuntimeError):await workflow.transition(oid,fid,"shipped",carrier_name="Manual",tracking_number="T1")
        shipped=await database.fulfillments.find_one({"_id":fid})
        assert shipped["status"]=="shipped" and shipped["shipment_snapshot"]["tracking_number"]=="T1"
        await workflow.transition(oid,fid,"shipped",carrier_name="Manual",tracking_number="T1")
        await workflow.transition(oid,fid,"delivered")
        await workflow.project_shipment(current_repository(),shipped)
        assert (await database.shipments.find_one({"fulfillment_id":fid}))["status"]=="delivered"
    asyncio.run(run())


def test_expiry_database_outage_retries_release_without_duplicate_legacy_stock(physical,monkeypatch):
    database,variant=physical
    monkeypatch.setattr("direct_checkout._run_node",lambda *args:{"image_base64":base64.b64encode(b"qr").decode()})
    async def run():
        import direct_checkout
        from datetime import datetime,timedelta,timezone
        from pymongo.errors import ServerSelectionTimeoutError
        await database.products.insert_one({"_id":"legacy-stock","name":"Legacy","delivery_type":"link","stock":3,"active":True,"price_idr":1000})
        customer=await database.store_customers.find_one({"_id":"customer"})
        result=await direct_checkout.create_store_qris_order(customer,[{"pid":"legacy-stock","qty":1},{"pid":"physical","variant_id":variant["_id"],"qty":1}],shipping_address=ADDRESS)
        oid=result["order"]["_id"]
        await database.purchases.update_one({"_id":oid},{"$set":{"expires_at":(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()}})
        with monkeypatch.context() as patch:
            patch.setattr(PhysicalStock,"release_order",AsyncMock(side_effect=ServerSelectionTimeoutError("synthetic outage")))
            with pytest.raises(ServerSelectionTimeoutError):await direct_checkout.expire_qris_orders()
        saved=await database.purchases.find_one({"_id":oid})
        assert saved["status"]=="expired" and saved["stock_release_pending"]
        await direct_checkout.expire_qris_orders();await direct_checkout.expire_qris_orders()
        await direct_checkout._release_order_stock(saved)
        assert (await PhysicalStock(database).get(variant["_id"]))["reserved"]==0
        assert (await database.products.find_one({"_id":"legacy-stock"}))["stock"]==3
        assert await database.stock_movements.count_documents({"type":"RELEASE"})==1
        assert not (await database.purchases.find_one({"_id":oid}))["stock_release_pending"]
    asyncio.run(run())



def test_return_requires_exact_sale_quantity_and_unpaid_shipment_blocked(physical):
    database,variant=physical
    async def run():
        from checkout import execute_checkout
        from storefront_routes import _finalize_store_balance_order
        from commerce.physical.workflow import transition
        stock=PhysicalStock(database)
        await stock.move(variant["_id"],"RESERVATION",1,reference_id="return-safety")
        await stock.move(variant["_id"],"SALE",1,reference_id="return-safety")
        with pytest.raises(CommerceError):await stock.move(variant["_id"],"RETURN",2,reference_id="return-safety")
        customer=await database.store_customers.find_one({"_id":"customer"})
        result=await execute_checkout({**customer,"customer_id":customer["_id"]},[{"pid":"physical","variant_id":variant["_id"],"qty":1}],purchase_source="WEB",shipping_address=ADDRESS)
        oid=result["order"]["_id"];await _finalize_store_balance_order(oid)
        fid=(await database.fulfillments.find_one({"order_id":oid}))["_id"]
        await database.purchases.update_one({"_id":oid},{"$set":{"status":"refunded"}})
        with pytest.raises(CommerceError,match="Paid order required"):await transition(oid,fid,"packing")
        assert (await database.fulfillments.find_one({"_id":fid}))["status"]=="pending"
    asyncio.run(run())



def test_physical_variant_discount_coupon_excludes_shipping_and_pricing_reconciles(physical):
    database,variant=physical
    async def run():
        from checkout import execute_checkout
        from storefront_routes import store_quote,QuoteBody
        await database.discounts.insert_one({"_id":"product-promo","active":True,"product_ids":["physical"],"mode":"percent","value":20,"min_qty":1})
        await database.promo_coupons.insert_one({"_id":"coupon","code":"PHYSICAL50","active":True,"currency":"IDR","type":"percent","value":50,"used_count":0,"quota_total":10,"per_user_limit":1})
        cart=[{"pid":"physical","variant_id":variant["_id"],"qty":2}]
        quote=await store_quote(QuoteBody(items=cart,coupon_code="PHYSICAL50"))
        assert quote["subtotal"]==24000 and quote["discount_total"]==12000 and quote["shipping_fee"]==5000 and quote["total"]==17000
        customer=await database.store_customers.find_one({"_id":"customer"})
        result=await execute_checkout({**customer,"customer_id":customer["_id"]},cart,coupon_code="PHYSICAL50",purchase_source="WEB",shipping_address=ADDRESS)
        assert result["ok"],result
        order=result["order"]
        assert order["items_subtotal"]-order["discount_total"]+order["shipping_fee"]+order["tax"]+order["payment_fee"]==order["grand_total"]==17000
        assert (await database.promo_coupons.find_one({"_id":"coupon"}))["used_count"]==1
    asyncio.run(run())
