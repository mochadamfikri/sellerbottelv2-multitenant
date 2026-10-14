"""Authenticated physical owner/customer boundaries, including identical IDs."""
import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest
from tests.test_public_tenant_management import management, seed
from tests.test_physical_commerce import ADDRESS
from db import client
from bot_tenant_scope import get_current_scope

@pytest.fixture
def physical_api(management,monkeypatch,tmp_path):
    registry,app=management
    monkeypatch.setenv("LOCAL_STORAGE_DIR",str(tmp_path))
    import physical_routes,storefront_routes,error_handlers
    from store_tenant_scope import install_store_scope
    app.include_router(physical_routes.router)
    app.include_router(storefront_routes.router)
    install_store_scope(app)
    error_handlers.register_error_handlers(app)
    monkeypatch.setattr("stock_monitor.schedule_stock_scan",lambda *args:None)
    monkeypatch.setattr("services.notify_transaction_channel_safely",AsyncMock())
    monkeypatch.setattr("services.notify_admin",AsyncMock())
    return registry,app

def test_authoring_sku_and_owner_isolation(physical_api):
    registry,app=physical_api
    async def run():
        a,ha=await seed(registry,"physical-a");b,hb=await seed(registry,"physical-b")
        base="/api/public/tenant/full/physical"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="https://mock") as http:
            ids=[]
            for headers in (ha,hb):
                response=await http.post(base+"/products",headers=headers,json={"name":"Physical","price_idr":10000})
                assert response.status_code==200,response.text
                pid=response.json()["_id"]
                import io
                from PIL import Image
                image=io.BytesIO();Image.new("RGB",(64,64),"green").save(image,"PNG")
                uploaded=await http.post(base+f"/products/{pid}/image",headers=headers,files={"image":("physical.png",image.getvalue(),"image/png")})
                assert uploaded.status_code==200,uploaded.text
                photo=await http.get(f"/api/public/tenant/full/products/{pid}/image",headers=headers)
                assert photo.status_code==200 and photo.headers["content-type"].startswith("image/webp")

                response=await http.post(base+f"/products/{pid}/variants",headers=headers,json={"sku":"same-sku","option_values":{"material":"cotton"}})
                assert response.status_code==200,response.text
                vid=response.json()["_id"];ids.append((pid,vid))
                response=await http.post(base+f"/variants/{vid}/stock",headers=headers,json={"type":"RECEIVE","quantity":3,"reason":"Opening","reference_id":"opening-unique"})
                assert response.status_code==200,response.text
                assert (await http.get(base+f"/products/{pid}/variants",headers=headers)).json()[0]["available"]==3
                assert (await http.post(base+f"/products/{pid}/variants",headers=headers,json={"sku":"SAME-SKU"})).status_code==422
                assert (await http.put(base+f"/products/{pid}",headers=headers,json={"name":"Edited","price_idr":12000})).status_code==200
                assert (await http.delete(f"/api/public/tenant/full/products/{pid}",headers=headers)).status_code==409
            pid,vid=ids[1]
            for method,path,body in [("GET",f"/products/{pid}/variants",None),("PUT",f"/products/{pid}",{"name":"Attack","price_idr":1}),("PUT",f"/variants/{vid}",{"sku":"SAME-SKU"}),("GET",f"/variants/{vid}/stock-movements",None),("POST",f"/variants/{vid}/stock",{"type":"DAMAGE","quantity":1,"reason":"Attack","reference_id":"attack-id"}),("GET","/orders/foreign-order",None),("POST","/orders/foreign-order/fulfillments/foreign-fid",{"status":"packing"})]:
                response=await http.request(method,base+path,headers=ha,json=body)
                assert response.status_code==404,(path,response.text)
            pid,vid=ids[0]
            assert (await http.put(base+f"/variants/{vid}",headers=ha,json={"sku":"OTHER"})).status_code==422
            assert (await http.put(base+f"/variants/{vid}",headers=ha,json={"sku":"SAME-SKU","active":False})).status_code==200
            assert (await http.delete(base+f"/variants/{vid}",headers=ha)).status_code==405
            assert (await client[b["database_name"]].physical_variants.find_one({"_id":ids[1][1]}))["on_hand"]==3
            await registry.update_status("physical-a","suspended")
            assert (await http.get(base+"/shipping",headers=ha)).status_code==403
        assert get_current_scope() is None
    asyncio.run(run())

def test_customer_cookie_same_id_cannot_cross_tenants_and_address_scoped(physical_api):
    registry,app=physical_api
    async def run():
        from auth import hash_password
        for slug in ("buyer-a","buyer-b"):
            tenant,_=await seed(registry,slug)
            await client[tenant["database_name"]].store_customers.insert_one({"_id":"identical-customer","email":"c2-buyer@gmail.com","password_hash":hash_password("strong-password-123"),"balance_idr":100000})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="https://mock") as http:
            response=await http.post("/api/store/t/buyer-a/login",json={"email":"c2-buyer@gmail.com","password":"strong-password-123"})
            assert response.status_code==200,response.text
            assert (await http.put("/api/store/t/buyer-a/address",json=ADDRESS)).status_code==200
            assert (await http.get("/api/store/t/buyer-a/address")).json()["city"]=="Bandung"
            assert (await http.get("/api/store/t/buyer-b/me")).status_code==401
            assert (await http.get("/api/store/t/buyer-b/address")).status_code==401
            assert (await http.get("/api/store/me")).status_code==401
            await registry.update_status("buyer-a","suspended")
            assert (await http.get("/api/store/t/buyer-a/me")).status_code==403
        assert get_current_scope() is None
    asyncio.run(run())


def test_identical_variant_order_fulfillment_ids_are_database_scoped(physical_api):
    registry,app=physical_api
    async def run():
        from datetime import datetime,timezone
        scopes=[]
        for slug in ("same-a","same-b"):
            tenant,headers=await seed(registry,slug);database=client[tenant["database_name"]];scopes.append((tenant,headers,database))
            await database.products.insert_one({"_id":"same-product","name":slug,"fulfillment_type":"physical","active":True})
            await database.physical_variants.insert_one({"_id":"same-variant","product_id":"same-product","sku":"SAME","option_values":{"owner":slug},"on_hand":0,"reserved":0,"stock_version":0,"stock_events":[],"active":True})
            await database.purchases.insert_one({"_id":"same-order","tenant_id":tenant["_id"],"status":"physical_pending","items":[{"line_id":"same-line","variant_id":"same-variant","sku":"SAME","fulfillment_type":"physical","qty":1}],"shipping_address":{**ADDRESS,"recipient_name":slug}})
            await database.fulfillments.insert_one({"_id":"same-fulfillment","tenant_id":tenant["_id"],"order_id":"same-order","line_id":"same-line","item_refs":["same-line"],"type":"physical","status":"pending","execution_status":"done","updated_at":datetime.now(timezone.utc)})
        base="/api/public/tenant/full/physical"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="https://mock") as http:
            for tenant,headers,database in scopes:
                assert (await http.get(base+"/orders/same-order",headers=headers)).json()["shipping_address"]["recipient_name"]==tenant["slug"]
                response=await http.post(base+"/variants/same-variant/stock",headers=headers,json={"type":"RECEIVE","quantity":2,"reference_id":"same-reference","reason":tenant["slug"]})
                assert response.status_code==200,response.text
                ledger=(await http.get(base+"/variants/same-variant/stock-movements",headers=headers)).json()
                assert len(ledger)==1 and ledger[0]["reason"]==tenant["slug"]
            for status in ("packing","ready_to_ship","shipped"):
                response=await http.post(base+"/orders/same-order/fulfillments/same-fulfillment",headers=scopes[0][1],json={"status":status,"carrier_name":"A Carrier","tracking_number":"A-TRACK"})
                assert response.status_code==200,response.text
            assert (await scopes[1][2].fulfillments.find_one({"_id":"same-fulfillment"}))["status"]=="pending"
            assert await scopes[1][2].shipments.count_documents({})==0
            assert (await http.get(base+"/orders/same-order",headers=scopes[1][1])).json()["fulfillments"][0].get("shipment_snapshot") is None
        assert get_current_scope() is None
    asyncio.run(run())
