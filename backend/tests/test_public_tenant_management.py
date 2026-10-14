"""HTTP regression for the public tenant owner management boundary."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

import dependencies
import public_registration as registration
import tenant_full_routes
from auth import create_access_token, hash_password
from bot_tenant_scope import get_current_scope
from db import client
from tenant_registry import MongoTenantRegistry


@pytest.fixture
def management(monkeypatch):
    async def clear():
        for name in await client.list_database_names():
            for collection in await client[name].list_collection_names():
                await client[name].drop_collection(collection)
    asyncio.run(clear())
    registry = MongoTenantRegistry(environment={"PLATFORM_DB_NAME": "sellerbottel_mock_only"}, client=client)
    monkeypatch.setattr(dependencies, "get_tenant_registry", lambda: registry)
    monkeypatch.setenv("INVENTORY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(registration, "_notify_owner_new_registration", AsyncMock())
    app = FastAPI()
    app.include_router(registration.router)
    app.include_router(tenant_full_routes.router)
    return registry, app


async def seed(registry, slug, status="active"):
    tenant = await registry.create_tenant(slug, slug.upper(), "demo")
    await registry.update_status(slug, status)
    owner = {"tenant_id": tenant["_id"], "tenant_slug": slug, "email": f"{slug}@gmail.com",
             "store_name": slug.upper(), "password_hash": hash_password("audit-password-123")}
    result = await registration._owners_collection().insert_one(owner)
    token = create_access_token(str(result.inserted_id), owner["email"])
    return tenant, {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("status,expected", [("active", 200), ("suspended", 403), ("disabled", 403),
    ("failed", 403), ("provisioning", 403)])
def test_login_and_both_api_families_recheck_lifecycle(management, status, expected):
    registry, app = management
    async def run():
        tenant, headers = await seed(registry, "lifecycle-shop", status)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock") as http:
            login = await http.post("/api/public/tenant/login", json={"email": "  LIFECYCLE-SHOP@gmail.com ", "password": "audit-password-123"})
            assert login.status_code == expected
            for path in ("/api/public/tenant/me", "/api/public/tenant/full/products"):
                assert (await http.get(path, headers=headers)).status_code == expected
            if status == "active":
                await registry.update_status("lifecycle-shop", "suspended")
                assert (await http.get("/api/public/tenant/full/products", headers=headers)).status_code == 403
                assert (await http.get("/api/public/tenant/me", headers=headers)).status_code == 403
            await registry.collection.delete_one({"_id": tenant["_id"]})
            assert (await http.get("/api/public/tenant/full/products", headers=headers)).status_code == 404
        assert get_current_scope() is None
    asyncio.run(run())


def test_inventory_product_catalog_and_order_contracts_are_isolated(management, monkeypatch):
    import admin_routes
    import storefront_routes
    monkeypatch.setattr(admin_routes, "send_message", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(storefront_routes, "send_order_completion_email", AsyncMock(return_value=True))
    registry, app = management
    async def run():
        a, ha = await seed(registry, "inventory-a")
        b, hb = await seed(registry, "inventory-b")
        da, db = client[a["database_name"]], client[b["database_name"]]
        await db.products.insert_one({"_id": "private-b", "name": "B secret", "active": True})
        await db.purchases.insert_one({"_id": "order-b", "status": "service_waiting"})
        await da.bot_users.insert_one({"telegram_id": 1, "balance_idr": 0})
        await db.bot_users.insert_one({"telegram_id": 1, "balance_idr": 700})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock", headers=ha) as http:
            # Header/parameter overrides cannot select another tenant.
            response = await http.get("/api/public/tenant/full/products", headers={"X-Tenant-ID": "inventory-b"})
            assert response.json() == []
            response = await http.post("/api/public/tenant/full/products", data={"name": "A product", "price_usd": "1", "price_idr": "16000", "delivery_type": "inventory"})
            assert response.status_code == 200, response.text
            pid = response.json().get("product", response.json()).get("_id")
            if not pid:
                product = await da.products.find_one({"name": "A product"})
                pid = product["_id"]
            root = f"/api/public/tenant/full/products/{pid}/inventory"
            assert (await http.put(root + "/schema", json={"fields": ["email", "password"]})).status_code == 200
            assert (await http.post(root + "/validate", data={"content": "email|password\na@example.test|secret"})).status_code == 200
            imported = await http.post(root + "/import", data={"content": "email|password\na@example.test|secret"})
            assert imported.status_code == 200, imported.text
            listed = await http.get(root)
            assert listed.status_code == 200, listed.text
            item = listed.json()["items"][0]
            schema = listed.json()["schema"]
            record = {field: f"replacement-{i}" for i, field in enumerate(schema)}
            assert (await http.put(root + "/" + item["_id"], json={"data": record})).status_code == 200
            assert (await http.post(root + "/manual", json={"data": {field: f"manual-{i}" for i, field in enumerate(schema)}})).status_code == 200
            assert (await http.get(root + "/summary")).json()["available"] == 2
            assert (await http.get(root + "/template?format=csv")).status_code == 200
            assert (await http.put(root + "/schema", json={"fields": schema})).status_code == 409
            assert (await http.delete(root + "/" + item["_id"])).status_code == 200
            assert (await http.post("/api/public/tenant/full/catalogs", json={"name": ""})).status_code == 422
            assert (await http.post("/api/public/tenant/full/catalogs", json={"name": "A catalog"})).status_code == 200
            assert (await http.put("/api/public/tenant/full/catalogs/assign", json={"name": "A catalog", "product_ids": [pid]})).status_code == 200
            assert (await http.put("/api/public/tenant/full/catalogs/rename", json={"old_name": "A catalog", "name": "Renamed A"})).status_code == 200
            assert (await http.put("/api/public/tenant/full/catalogs/assign", json={"name": "Renamed A", "product_ids": ["private-b"]})).status_code == 404
            assert (await http.get("/api/public/tenant/full/catalogs")).status_code == 200
            await da.purchases.insert_many([
                {"_id": "refund-a", "status": "failed", "currency": "IDR", "total": 50, "user_tid": 1, "invoice_id": "A-1"},
                {"_id": "service-a", "status": "service_waiting"},
                {"_id": "email-a", "status": "delivered", "delivery_email_status": "failed", "customer_email": "a@example.test"},
            ])
            orders = await http.get("/api/public/tenant/full/orders?search=A-1")
            assert [row["_id"] for row in orders.json()] == ["refund-a"]
            assert (await http.get("/api/public/tenant/full/orders/order-b")).status_code == 404
            assert (await http.post("/api/public/tenant/full/orders/order-b/complete")).status_code == 404
            assert (await http.post("/api/public/tenant/full/orders/refund-a/refund")).status_code == 200
            assert (await http.post("/api/public/tenant/full/orders/refund-a/refund")).status_code == 400
            assert (await http.post("/api/public/tenant/full/orders/service-a/complete")).status_code == 200
            assert (await http.post("/api/public/tenant/full/orders/email-a/email/retry")).status_code == 200
            assert (await http.delete("/api/public/tenant/full/products/private-b")).status_code == 404
            assert (await http.get(f"/api/public/tenant/full/products/{pid}/image")).status_code == 200
            assert (await http.get(root, headers=hb)).status_code == 404
        assert (await db.bot_users.find_one({"telegram_id": 1}))["balance_idr"] == 700
        assert (await da.bot_users.find_one({"telegram_id": 1}))["balance_idr"] == 50
        assert await db.products.find_one({"_id": "private-b"})
        assert (await db.purchases.find_one({"_id": "order-b"}))["status"] == "service_waiting"
        assert get_current_scope() is None
    asyncio.run(run())


@pytest.mark.parametrize("conflict", [False, True])
def test_registration_normalization_store_name_and_domain_conflict_rollback(management, conflict):
    registry, app = management
    async def run():
        from domain_registry import register_domain
        from platform_indexes import ensure_platform_indexes
        await ensure_platform_indexes(registration._platform_db())
        domain = "new-shop.idseconnect.my.id"
        if conflict:
            await register_domain(client, domain=domain, tenant_id="someone-else", purpose="storefront")
        email = "newowner@gmail.com"
        await registration._platform_db().public_reg_verified.insert_one({"email": email, "verify_token": "verified", "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)})
        body = {"username": "new-shop", "email": "  NewOwner@GMAIL.COM ", "store_name": "New Store", "password": "audit-password-123", "whatsapp": "08123456789", "verify_token": "verified"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock") as http:
            response = await http.post("/api/public/register", json=body)
            assert response.status_code == (409 if conflict else 201), response.text
            tenant = await registry.get_tenant("new-shop")
            owner = await registration._owners_collection().find_one({"email": email})
            if conflict:
                assert tenant is None and owner is None
                assert await registration._platform_db().public_reg_verified.find_one({"email": email})
            else:
                assert tenant["status"] == "active"
                assert owner["store_name"] == "New Store"
                login = await http.post("/api/public/tenant/login", json={"email": email.upper(), "password": "audit-password-123"})
                assert login.status_code == 200 and login.json()["store_name"] == "New Store"
                assert (await client[tenant["database_name"]].settings.find_one({"_id": "main"}))["store_name"] == "New Store"
                retry = await http.post("/api/public/register", json=body)
                assert retry.status_code == 422  # verification consumed only after success
    asyncio.run(run())


def test_registration_rolls_back_on_atomic_domain_claim_race(management, monkeypatch):
    import domain_registry
    registry, app = management
    monkeypatch.setattr(domain_registry, "register_domain", AsyncMock(side_effect=ValueError("conflict")))
    async def run():
        await registration._platform_db().public_reg_verified.insert_one({"email": "race@gmail.com", "verify_token": "verified", "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock") as http:
            response = await http.post("/api/public/register", json={"username": "race-shop", "email": "race@gmail.com", "store_name": "Race", "password": "audit-password-123", "whatsapp": "08123456789", "verify_token": "verified"})
            assert response.status_code == 409
        assert await registry.get_tenant("race-shop") is None
        assert await registration._owners_collection().find_one({"email": "race@gmail.com"}) is None
    asyncio.run(run())


def test_custom_host_config_and_managed_tls_lifecycle(management):
    from domain_registry import register_domain
    from server import tls_ask
    registry, app = management
    async def run():
        tenant, _ = await seed(registry, "host-shop")
        for domain, origin in [("host-shop.idseconnect.my.id", "owner_subdomain"), ("custom.example.test", "custom")]:
            await register_domain(client, domain=domain, tenant_id=tenant["_id"], purpose="storefront", origin=origin)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://custom.example.test") as http:
            assert (await http.get("/api/public/host-config")).json()["tenant_slug"] == "host-shop"
        assert await tls_ask("host-shop.idseconnect.my.id") == {"ok": True}
        for status in ("suspended", "disabled", "failed", "provisioning"):
            await registry.update_status("host-shop", status)
            assert (await tls_ask("host-shop.idseconnect.my.id")).status_code == 403
        assert (await tls_ask("custom.example.test")).status_code == 403
    asyncio.run(run())


def test_inventory_transform_and_session_replacement_use_own_database(management):
    registry, app = management
    async def run():
        tenant, headers = await seed(registry, "files-shop")
        database = client[tenant["database_name"]]
        await database.products.insert_many([
            {"_id": "table", "name": "Table", "active": True, "product_kind": "digital", "inventory_schema": ["email", "password"]},
            {"_id": "session", "name": "Session", "active": True, "product_kind": "digital", "inventory_mode": "telegram_session", "inventory_schema": ["Session File"]},
        ])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock", headers=headers) as http:
            file = ("table.csv", b"email,password\na@old.test,oldpassword\n", "text/csv")
            root = "/api/public/tenant/full/products/table/inventory/transform"
            inspected = await http.post(root + "/inspect", files={"file": file})
            assert inspected.status_code == 200 and inspected.json()["row_count"] == 1
            transformed = await http.post(root, files={"file": file}, data={"email_column": "email", "new_domain": "new.test", "password_column": "password", "password_mode": "fixed", "fixed_password": "updated"})
            assert transformed.status_code == 200, transformed.text
            from openpyxl import load_workbook
            from io import BytesIO
            assert list(load_workbook(BytesIO(transformed.content)).active.values)[1] == ("a@new.test", "updated")
            assert await database.inventory_items.count_documents({"product_id": "table"}) == 0
            session_root = "/api/public/tenant/full/products/session/inventory"
            imported = await http.post(session_root + "/import", files={"file": ("original.session", b"original-session", "application/octet-stream")})
            assert imported.status_code == 200, imported.text
            items = (await http.get(session_root)).json()["items"]
            replaced = await http.post(session_root + "/" + items[0]["_id"] + "/file", files={"file": ("replacement.session", b"replacement-session", "application/octet-stream")})
            assert replaced.status_code == 200, replaced.text
            fresh = (await http.get(session_root)).json()["items"]
            assert fresh[0]["item"]["file"] == "replacement.session"
    asyncio.run(run())


def test_owner_email_unique_index_and_otp_canonical_form(management):
    from pymongo.errors import DuplicateKeyError
    from platform_indexes import ensure_platform_indexes
    async def run():
        database = registration._platform_db()
        await ensure_platform_indexes(database)
        await ensure_platform_indexes(database)
        assert registration.VerifyCodeBody(email="  OWNER@GMAIL.COM ", code="123456").email == "owner@gmail.com"
        await database.tenant_owners.insert_one({"email": "owner@gmail.com"})
        with pytest.raises(DuplicateKeyError):
            await database.tenant_owners.insert_one({"email": "owner@gmail.com"})
    asyncio.run(run())


def test_tenant_broadcast_executes_scoped_worker_and_respects_suspend(management, monkeypatch):
    import admin_routes
    from inventory import _fernet
    registry, app = management
    sent = []
    async def capture(tid, text, kb=None):
        scope = get_current_scope()
        sent.append((scope.slug, scope.bot_token, tid, text))
        return {"ok": True}
    monkeypatch.setattr(admin_routes, "send_message", capture)
    async def run():
        a, headers = await seed(registry, "broadcast-a")
        b, _ = await seed(registry, "broadcast-b")
        await registry.set_metadata("broadcast-a", {"bot_config": {"token_encrypted": _fernet().encrypt(b"123:tenant-a").decode()}})
        await client[a["database_name"]].bot_users.insert_one({"telegram_id": 111})
        await client[b["database_name"]].bot_users.insert_one({"telegram_id": 222})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock", headers=headers) as http:
            response = await http.post("/api/public/tenant/full/broadcasts", json={"message": "Only A"})
            assert response.status_code == 200, response.text
            for _ in range(20):
                await asyncio.sleep(0.01)
                result = await client[a["database_name"]].broadcasts.find_one({"_id": response.json()["_id"]})
                if result["status"] == "completed": break
            assert result["status"] == "completed" and result["success"] == 1
            assert sent == [("broadcast-a", "123:tenant-a", 111, "Only A")]
            assert await client[b["database_name"]].broadcasts.count_documents({}) == 0
            await registry.update_status("broadcast-a", "suspended")
            assert (await http.post("/api/public/tenant/full/broadcasts", json={"message": "Blocked"})).status_code == 403
    asyncio.run(run())


def test_otp_delivery_failure_is_reported_and_retry_is_not_locked(management, monkeypatch):
    monkeypatch.setattr(registration, "_send_otp_email", AsyncMock(side_effect=RuntimeError("mock failure")))
    _, app = management
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock") as http:
            for _ in range(2):
                assert (await http.post("/api/public/register/request-code", json={"email": " OTP@GMAIL.COM "})).status_code == 503
                assert await registration._otp_collection().find_one({"email": "otp@gmail.com"}) is None
    asyncio.run(run())


def test_registry_rejects_database_alias_collision(management):
    registry, _ = management
    async def run():
        await registry.create_tenant("tenant-a", "A", "demo")
        with pytest.raises(ValueError):
            await registry.create_tenant("tenant_a", "Imposter A", "demo")
        assert len(await registry.list_tenants()) == 1
    asyncio.run(run())


def test_registration_provisioning_failure_removes_only_new_tenant_database(management, monkeypatch):
    import tenant_provisioning
    registry, app = management
    original = tenant_provisioning.provision_tenant_database
    async def fail_after_initialization(slug, db_client):
        await original(slug, db_client)
        raise RuntimeError("mock provisioning failure")
    monkeypatch.setattr(tenant_provisioning, "provision_tenant_database", fail_after_initialization)
    async def run():
        await client["existing_tenant"].records.insert_one({"_id": "keep"})
        await registration._platform_db().public_reg_verified.insert_one({"email": "rollback@gmail.com", "verify_token": "verified", "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock") as http:
            response = await http.post("/api/public/register", json={"username": "rollback-shop", "email": "rollback@gmail.com", "store_name": "Rollback", "password": "audit-password-123", "whatsapp": "08123456789", "verify_token": "verified"})
            assert response.status_code == 503
        assert await registry.get_tenant("rollback-shop") is None
        assert "sellerbottel_tenant_rollback_shop" not in await client.list_database_names()
        assert await client["existing_tenant"].records.find_one({"_id": "keep"})
        assert await registration._owners_collection().find_one({"email": "rollback@gmail.com"}) is None
        assert await registration._platform_db().domains.find_one({"domain": "rollback-shop.idseconnect.my.id"}) is None
    asyncio.run(run())


@pytest.mark.parametrize("editing", [False, True])
def test_failed_product_save_cleans_new_image_preserves_existing(management, monkeypatch, tmp_path, editing):
    import io
    from PIL import Image
    from mongomock_motor import AsyncMongoMockCollection
    import storage
    monkeypatch.setattr(storage, "STORAGE_ROOT", tmp_path)
    registry, app = management
    async def run():
        tenant, headers = await seed(registry, "image-failure")
        database = client[tenant["database_name"]]
        await storage.put_object("old.webp", b"existing-image", "image/webp")
        await database.products.insert_one({"_id": "existing", "name": "Existing", "price_usd": 1, "active": True, "image_path": "old.webp"})
        original = AsyncMongoMockCollection.update_one if editing else AsyncMongoMockCollection.insert_one
        async def fail_products(collection, *args, **kwargs):
            if collection.name == "products":
                raise RuntimeError("controlled product save failure")
            return await original(collection, *args, **kwargs)
        monkeypatch.setattr(AsyncMongoMockCollection, "update_one" if editing else "insert_one", fail_products)
        image = io.BytesIO()
        Image.new("RGB", (64, 64)).save(image, format="PNG")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://mock") as http:
            response = await http.request("PUT" if editing else "POST", "/api/public/tenant/full/products" + ("/existing" if editing else ""), headers=headers,
                data={"name": "Changed", "price_usd": "2"}, files={"image": ("image.png", image.getvalue(), "image/png")})
            assert response.status_code == 500
        assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == ["old.webp"]
        assert (await database.products.find_one({"_id": "existing"}))["image_path"] == "old.webp"
    asyncio.run(run())


def test_owner_database_outage_returns_retryable_service_error(management, monkeypatch):
    from mongomock_motor import AsyncMongoMockCollection
    from pymongo.errors import ServerSelectionTimeoutError
    registry, app = management
    async def run():
        _, headers = await seed(registry, "owner-outage")
        original = AsyncMongoMockCollection.find_one
        async def fail_owner(collection, *args, **kwargs):
            if collection.name == "tenant_owners":
                raise ServerSelectionTimeoutError("controlled development outage")
            return await original(collection, *args, **kwargs)
        monkeypatch.setattr(AsyncMongoMockCollection, "find_one", fail_owner)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://mock") as http:
            response = await http.get("/api/public/tenant/me", headers=headers)
            assert response.status_code == 503
            assert response.json()["detail"]
    asyncio.run(run())


def test_stock_panel_managed_tls_and_host_binding(management, monkeypatch):
    from domain_registry import register_domain
    from server import tls_ask
    monkeypatch.setenv('TENANT_PANEL_DOMAIN', 'idsestock.my.id')
    registry, app = management
    async def run():
        tenant, _ = await seed(registry, 'panel-shop')
        await register_domain(client, domain='panel-shop.idsestock.my.id', tenant_id=tenant['_id'], purpose='stock_panel')
        await register_domain(client, domain='wrong.idsestock.my.id', tenant_id=tenant['_id'], purpose='storefront')
        assert await tls_ask('panel-shop.idsestock.my.id') == {'ok': True}
        assert (await tls_ask('wrong.idsestock.my.id')).status_code == 404
        assert (await tls_ask('unknown.idsestock.my.id')).status_code == 404
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://panel-shop.idsestock.my.id') as http:
            assert (await http.get('/api/public/host-config')).json()['tenant_slug'] == 'panel-shop'
        await registry.update_status('panel-shop', 'suspended')
        assert (await tls_ask('panel-shop.idsestock.my.id')).status_code == 403
    asyncio.run(run())


def test_registration_panel_domain_and_conflict_rollback(management, monkeypatch):
    from domain_registry import register_domain
    monkeypatch.setenv('TENANT_PANEL_DOMAIN', 'idsestock.my.id')
    registry, app = management
    async def run():
        await register_domain(client, domain='blocked-panel.idsestock.my.id', tenant_id='other', purpose='stock_panel')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://idseconnect.my.id') as http:
            for slug, status in [('new-panel', 201), ('blocked-panel', 409)]:
                email=slug+'@gmail.com'
                await registration._platform_db().public_reg_verified.insert_one({'email':email,'verify_token':'verified','expires_at':datetime.now(timezone.utc)+timedelta(minutes=10)})
                response=await http.post('/api/public/register',json={'username':slug,'email':email,'store_name':slug,'password':'audit-password-123','whatsapp':'08123456789','verify_token':'verified'})
                assert response.status_code == status
                if status==201:
                    assert (await registration._platform_db().domains.find_one({'domain':slug+'.idsestock.my.id'}))['purpose']=='stock_panel'
                else:
                    assert await registry.get_tenant(slug) is None
                    assert await registration._platform_db().domains.find_one({'domain':slug+'.idseconnect.my.id'}) is None
                    assert (await registration._platform_db().domains.find_one({'domain':slug+'.idsestock.my.id'}))['tenant_id']=='other'
    asyncio.run(run())
