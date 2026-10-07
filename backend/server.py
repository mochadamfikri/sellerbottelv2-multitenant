from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import asyncio
import logging
from fastapi import FastAPI, APIRouter, Request, HTTPException, Depends
from starlette.middleware.cors import CORSMiddleware

from config import validate_environment
from db import client, db, ensure_settings, ensure_indexes
from auth import get_current_admin
from auth import router as auth_router, seed_admin
from admin_routes import router as admin_router
from admin_user_routes import router as admin_user_router
from promo_routes import router as promo_router
from promo_routes_accounts import router as promo_accounts_router
from promo_campaign_routes import router as promo_campaign_router
from promo_reply_routes import router as promo_reply_router
from promo_runtime import start_promo_runtime, stop_promo_runtime
from broadcast_composer import router as broadcast_composer_router
from daily_recap import router as daily_recap_router, run_daily_recap
from post_purchase import router as followup_router, run_followup
from reseller_routes import admin_router as reseller_admin_router, webhook_router as reseller_webhook_router
from reseller_signup import run_subscription_monitor
from inventory_transform import router as inventory_transform_router
from stock_monitor import run_stock_monitor, router as stock_events_router
from bot_moderation_routes import router as bot_moderation_router
from storefront_routes import router as storefront_router
from balance_admin import router as balance_admin_router
from marketing_campaigns import router as marketing_router, run_marketing
from analytics_routes import router as analytics_router, public_router as analytics_public_router
from error_handlers import register_error_handlers
from inventory import encryption_status
from bot import process_update, resume_service_waiters
from bot2 import process_update2, run_bot2_payment_monitor
from i18n import load_overrides
from tgapi import tg
from gopay_provider import run_gopay_monitor
from v2_platform_routes import router as v2_platform_router
from public_registration import router as public_registration_router
from tenant_full_routes import router as tenant_full_router
from promo_config import router as promo_config_router
from v2_customer_config_routes import (
    customer_router as v2_customer_config_customer_router,
    platform_router as v2_customer_config_platform_router,
)
from v2_tenant_routes import router as v2_tenant_router
from dependencies import get_tenant_registry
from tenant_context import configure_tenant_registry_resolver


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

app = FastAPI()
api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"message": "Toko Digital Bot API"}


@api_router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    import hmac

    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    received = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not expected or not received or not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=403, detail="Invalid webhook token")

    update = await request.json()
    update_id = update.get("update_id")
    if update_id is not None:
        try:
            await db.processed_updates.insert_one({"_id": str(update_id), "update_id": update_id})
        except Exception:
            return {"ok": True, "duplicate": True}

    asyncio.create_task(process_update(update))
    return {"ok": True}


@api_router.post("/telegram/bot2/webhook")
async def telegram_webhook_bot2(request: Request):
    import hmac

    expected = os.environ.get("BOT2_WEBHOOK_SECRET", "")
    received = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not expected or not received or not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=403, detail="Invalid Bot 2 webhook token")

    update = await request.json()
    update_id = update.get("update_id")
    if update_id is not None:
        try:
            await db.processed_updates_bot2.insert_one({"_id": str(update_id), "update_id": update_id})
        except Exception:
            return {"ok": True, "duplicate": True}

    asyncio.create_task(process_update2(update))
    return {"ok": True}


app.include_router(api_router)
app.include_router(analytics_public_router)


@app.get("/api/internal/tls-ask")
async def tls_ask(domain: str = ""):
    """Endpoint untuk Caddy on-demand TLS 'ask'.
    PENTING: Caddy mengartikan HTTP 2xx sebagai 'boleh terbitkan sertifikat'.
    Hanya return 200 untuk domain yang benar-benar terdaftar di domain_registry.
    Selain itu return 403/404 agar Caddy menolak issuance.
    """
    from fastapi.responses import JSONResponse

    # 1. Normalize: lowercase, strip whitespace dan trailing dot
    domain = (domain or "").strip().lower().rstrip(".")

    # Domain di luar idseconnect.my.id → 403
    # (custom domain user di-handle terpisah, untuk sekarang tolak)
    if not domain.endswith(".idseconnect.my.id"):
        return JSONResponse(status_code=403, content={"error": "foreign domain"})
    # Harus ada subdomain
    sub = domain[: -len(".idseconnect.my.id")]
    if not sub or "." in sub.strip("."):
        # Boleh ada titik di subdomain (misal imelda.store), tapi jangan kosong
        pass
    if not sub:
        return JSONResponse(status_code=403, content={"error": "invalid format"})

    try:
        from db import client as db_client
        from tenant_db import resolve_platform_database_name
        import domain_registry
        import os
        # Cari domain di registry
        reg = await domain_registry.resolve_domain(db_client, domain)
        if not reg or reg.get("purpose") != "storefront":
            return JSONResponse(status_code=404, content={"error": "unknown domain"})
        # Cek tenant masih aktif
        pdb = db_client[resolve_platform_database_name(os.environ)]
        tenant = await pdb["tenants"].find_one({"_id": reg.get("tenant_id")})
        # Fallback: cari by slug/id juga
        if not tenant:
            tid = str(reg.get("tenant_id") or "")
            tenant = await pdb["tenants"].find_one({
                "$or": [{"_id": tid}, {"slug": tid}]
            })
        if not tenant:
            return JSONResponse(status_code=404, content={"error": "unknown tenant"})
        status = (tenant.get("status") or "").lower()
        if status in ("suspended", "deleted", "disabled", "banned"):
            return JSONResponse(status_code=403, content={"error": "tenant not eligible"})
        return {"ok": True}
    except Exception:
        return JSONResponse(status_code=500, content={"error": "internal error"})
app.include_router(auth_router)
app.include_router(admin_user_router)
app.include_router(admin_router)
app.include_router(analytics_router)
app.include_router(broadcast_composer_router)
app.include_router(daily_recap_router)
app.include_router(followup_router)
app.include_router(reseller_admin_router)
app.include_router(reseller_webhook_router)
app.include_router(inventory_transform_router)
app.include_router(stock_events_router)
app.include_router(bot_moderation_router)
app.include_router(storefront_router)
app.include_router(balance_admin_router)
app.include_router(marketing_router)
app.include_router(v2_platform_router)
app.include_router(public_registration_router)
app.include_router(tenant_full_router)
app.include_router(promo_config_router)
app.include_router(v2_customer_config_platform_router)
app.include_router(v2_customer_config_customer_router)
app.include_router(v2_tenant_router, prefix="/api/v2/tenant")

# Import and mount v2_commerce_routes
from v2_commerce_routes import router as v2_commerce_router
app.include_router(v2_commerce_router, prefix="/api/v2/tenant")

if os.environ.get("PROMOTION_ENABLED", "").lower() in {"1", "true", "yes"}:
    app.include_router(promo_router)
    app.include_router(promo_accounts_router, prefix="/api/admin/promo", dependencies=[Depends(get_current_admin)])
    app.include_router(promo_campaign_router, prefix="/api/admin/promo", dependencies=[Depends(get_current_admin)])
    app.include_router(promo_reply_router, prefix="/api/admin/promo", dependencies=[Depends(get_current_admin)])

register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    environment = validate_environment()
    logger.info("Environment mode: %s", environment)

    if not os.environ.get("CORS_ORIGINS"):
        raise RuntimeError("CORS_ORIGINS wajib di-set.")
    if not os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET wajib di-set.")

    logger.info(
        "Promotion module: %s",
        "enabled" if os.environ.get("PROMOTION_ENABLED", "").lower() in {"1", "true", "yes"} else "disabled",
    )
    logger.info(
        "Bot 2: %s",
        "enabled" if os.environ.get("BOT2_ENABLED", "").lower() in {"1", "true", "yes"} else "disabled",
    )

    # Wire the persistent tenant registry resolver before any routes are exercised.
    mongo_registry = get_tenant_registry()
    configure_tenant_registry_resolver(mongo_registry, client)
    logger.info("Tenant registry resolver configured (MongoTenantRegistry)")

    # Ensure platform indexes exist before any tenant operations
    from platform_indexes import ensure_platform_indexes
    platform_db = client[mongo_registry.platform_database_name]
    await ensure_platform_indexes(platform_db)
    logger.info("Platform indexes ensured")

    await ensure_settings()
    await ensure_indexes()
    await load_overrides(db.bot_messages)
    await seed_admin()
    app.state.marketing_stop = asyncio.Event()
    app.state.marketing_task = asyncio.create_task(run_marketing(app.state.marketing_stop))
    app.state.stock_monitor_stop = asyncio.Event()
    app.state.stock_monitor_task = asyncio.create_task(run_stock_monitor(app.state.stock_monitor_stop))
    app.state.daily_recap_stop = asyncio.Event()
    app.state.daily_recap_task = asyncio.create_task(run_daily_recap(app.state.daily_recap_stop))
    app.state.followup_stop = asyncio.Event()
    app.state.followup_task = asyncio.create_task(run_followup(app.state.followup_stop))
    app.state.reseller_monitor_stop = asyncio.Event()
    app.state.reseller_monitor_task = asyncio.create_task(run_subscription_monitor(app.state.reseller_monitor_stop))

    try:
        inv = await encryption_status()
        if not inv["valid"] or inv["data_readable"] is False:
            logger.error("INVENTORY: %s", inv["message"])
    except Exception as exc:
        logger.error("INVENTORY: gagal mengecek konfigurasi enkripsi: %s", exc)

    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

    if os.environ.get("GOPAY_ENABLED", "").lower() in {"1", "true", "yes"}:
        app.state.gopay_stop = asyncio.Event()
        app.state.gopay_task = asyncio.create_task(run_gopay_monitor(app.state.gopay_stop))

    if (
        os.environ.get("BOT2_ENABLED", "").lower() in {"1", "true", "yes"}
        and os.environ.get("BOT2_TELEGRAM_TOKEN")
        and os.environ.get("GOPAY_ENABLED", "").lower() in {"1", "true", "yes"}
    ):
        app.state.bot2_payment_stop = asyncio.Event()
        app.state.bot2_payment_task = asyncio.create_task(
            run_bot2_payment_monitor(app.state.bot2_payment_stop)
        )

    await resume_service_waiters()
    await start_promo_runtime()

    if base and os.environ.get("TELEGRAM_TOKEN"):
        try:
            res = await tg(
                "setWebhook",
                url=f"{base}/api/telegram/webhook",
                secret_token=os.environ["TELEGRAM_WEBHOOK_SECRET"],
                allowed_updates=["message", "callback_query"],
            )
            logger.info("Bot 1 webhook set: %s", res)
        except Exception as exc:
            logger.error("Bot 1 webhook setup failed: %s", exc)

    bot2_base = os.environ.get("BOT2_PUBLIC_BASE_URL", "").rstrip("/") or base
    if (
        os.environ.get("BOT2_ENABLED", "").lower() in {"1", "true", "yes"}
        and bot2_base
        and os.environ.get("BOT2_TELEGRAM_TOKEN")
        and os.environ.get("BOT2_WEBHOOK_SECRET")
    ):
        try:
            from bot2 import tg2
            res = await tg2(
                "setWebhook",
                url=f"{bot2_base}/api/telegram/bot2/webhook",
                secret_token=os.environ["BOT2_WEBHOOK_SECRET"],
                allowed_updates=["message", "callback_query"],
            )
            logger.info("Bot 2 webhook set: %s", res)
            commands = await tg2(
                "setMyCommands",
                commands=[
                    {"command": "start", "description": "Mulai / buka menu"},
                    {"command": "stock", "description": "Lihat stok produk"},
                    {"command": "help", "description": "Cara order"},
                    {"command": "deposit", "description": "Deposit saldo IDR"},
                ],
            )
            logger.info("Bot 2 commands set: %s", commands)
        except Exception as exc:
            logger.error("Bot 2 webhook setup failed: %s", exc)


@app.on_event("shutdown")
async def shutdown_db_client():
    app.state.marketing_stop.set()
    app.state.marketing_task.cancel()
    await asyncio.gather(app.state.marketing_task, return_exceptions=True)
    await stop_promo_runtime()
    app.state.stock_monitor_stop.set()
    app.state.stock_monitor_task.cancel()
    app.state.daily_recap_stop.set()
    app.state.daily_recap_task.cancel()
    app.state.followup_stop.set()
    app.state.followup_task.cancel()
    app.state.reseller_monitor_stop.set()
    app.state.reseller_monitor_task.cancel()

    stop = getattr(app.state, "gopay_stop", None)
    task = getattr(app.state, "gopay_task", None)
    if stop:
        stop.set()
    if task:
        task.cancel()

    bot2_stop = getattr(app.state, "bot2_payment_stop", None)
    bot2_task = getattr(app.state, "bot2_payment_task", None)
    if bot2_stop:
        bot2_stop.set()
    if bot2_task:
        bot2_task.cancel()

    client.close()
