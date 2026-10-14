"""Registered-host binding for every customer API, including authentication."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError
from bot_tenant_scope import BotTenantScope, use_bot_tenant


def install_store_scope(app):
    @app.middleware("http")
    async def bind_store(request, call_next):
        if not request.url.path.startswith("/api/store/"):
            return await call_next(request)
        try:
            from storefront_routes import _tenant_slug_from_host, _resolve_tenant_store
            slug = await _tenant_slug_from_host(request)
            path_slug = request.url.path.split("/")[4] if request.url.path.startswith("/api/store/t/") else None
            if slug and path_slug and slug != path_slug:
                raise HTTPException(400, "Store context mismatch")
            slug = slug or path_slug
            if not slug:
                return await call_next(request)
            tenant, database = await _resolve_tenant_store(slug)
            if tenant.get("status") != "active":
                raise HTTPException(403, "Store unavailable")
            scope = BotTenantScope(tenant_id=str(tenant["_id"]), slug=tenant["slug"], database_name=database.name, db_handle=database, bot_token="unconfigured-tenant-bot")
            async with use_bot_tenant(scope):
                return await call_next(request)
        except HTTPException as error:
            return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
        except PyMongoError:
            return JSONResponse(status_code=503, content={"detail": "Store database unavailable; retry"})
