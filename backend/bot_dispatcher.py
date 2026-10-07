"""Multi-tenant Telegram bot dispatcher.

Runs one long-polling worker per provisioned tenant.  Each worker:
  1. loads the tenant's encrypted bot token (decrypted in memory only),
  2. long-polls Telegram getUpdates for that token,
  3. installs a BotTenantScope (tenant DB + token) and calls
     ``bot.process_update(update)``.

A supervisor reconciles workers against the platform tenant registry every
60 seconds: new tenants get workers, suspended/deleted/rotated tenants lose
theirs.  One tenant's crash never affects the others.

Isolation is enforced structurally: the worker only ever holds its own
tenant's database handle and token.  Tokens are never logged.

Usage:
    python -m bot_dispatcher            # runs forever
    python -m bot_dispatcher --once     # single reconcile pass (debug)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

import httpx

logger = logging.getLogger("bot_dispatcher")

# Imported lazily inside functions where possible so unit tests can import
# this module without pulling the full backend dependency chain.

RECONCILE_INTERVAL = 60
POLL_TIMEOUT = 30


def _http_client() -> httpx.AsyncClient:
    # trust_env=False: the sandbox NO_PROXY carries bracketed IPv6 entries
    # that this httpx version cannot parse.  Proxy and CA bundle are set
    # explicitly instead (the proxy MITMs TLS with a custom CA).
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    verify = os.environ.get("SSL_CERT_FILE") or True
    return httpx.AsyncClient(timeout=POLL_TIMEOUT + 10, proxy=proxy,
                             trust_env=False, verify=verify)


async def _load_active_bot_tenants():
    """Return [(tenant_doc, plaintext_token)] for runnable tenants."""
    from db import client
    from dependencies import get_tenant_registry
    from inventory import _fernet
    from tenant_db import tenant_database_name

    registry = get_tenant_registry()
    tenants = await registry.list_tenants()
    fernet = _fernet()
    runnable = []
    for t in tenants:
        if t.get("status") != "active":
            continue
        metadata = t.get("metadata") or {}
        bot_config = metadata.get("bot_config") or {}
        enc = bot_config.get("token_encrypted")
        if not enc:
            continue
        slug = t.get("slug") or t.get("tenant_id")
        try:
            token = fernet.decrypt(enc.encode()).decode()
        except Exception:
            logger.exception("cannot decrypt token for tenant %s", slug)
            continue
        database_name = t.get("database_name") or tenant_database_name(slug)
        runnable.append((t, token, database_name))
    return runnable


async def _load_central_bot():
    """Return (token, brand_name, database_name) for the platform central bot.

    The central bot is the platform owner's own shop bot (e.g. @deve_idsebot
    for IDSE).  Its token is stored encrypted in the platform database under
    platform_config/_id="central_bot".  It is scoped to the owner's tenant
    database so it serves the owner's own shop data.  Returns None when no
    central bot is provisioned.
    """
    from db import client
    from dependencies import get_tenant_registry
    from inventory import _fernet
    from tenant_db import tenant_database_name, resolve_platform_database_name

    platform_db = client[resolve_platform_database_name(os.environ)]
    doc = await platform_db["platform_config"].find_one({"_id": "central_bot"})
    if not doc or not doc.get("token_encrypted"):
        return None
    try:
        token = _fernet().decrypt(doc["token_encrypted"].encode()).decode()
    except Exception:
        logger.exception("cannot decrypt central bot token")
        return None
    # Scope the central bot to the owner's tenant database.
    registry = get_tenant_registry()
    tenants = await registry.list_tenants()
    owner_slug = (doc.get("owner_tenant_slug")
                  or next((t.get("slug") for t in tenants
                           if t.get("status") == "active"), "idse"))
    database_name = tenant_database_name(owner_slug)
    from welcome_banner import normalize_welcome_media
    welcome_media = normalize_welcome_media(doc)
    admin_ids = doc.get("admin_ids") or []
    # Central bot: reseller entry active by default; tenant bots: opt-in.
    reseller_enabled = doc.get("reseller_enabled", True)
    return token, doc.get("brand_name", ""), welcome_media, admin_ids, reseller_enabled, database_name


async def _mark_provisioning_running(slug: str) -> None:
    """Flip a tenant's bot_provisioning status to running once its worker starts."""
    try:
        from dependencies import get_tenant_registry
        from datetime import datetime
        registry = get_tenant_registry()
        tenant = await registry.get_tenant(slug)
        if not tenant:
            return
        metadata = dict(tenant.get("metadata") or {})
        bot_config = dict(metadata.get("bot_config") or {})
        prov = bot_config.get("bot_provisioning") or {}
        if not isinstance(prov, dict) or prov.get("status") != "provisioning":
            return
        prov["status"] = "running"
        prov["running_at"] = datetime.now().isoformat()
        bot_config["bot_provisioning"] = prov
        metadata["bot_config"] = bot_config
        await registry.set_metadata(slug, metadata)
        logger.info("provisioning marked running for tenant %s", slug)
    except Exception:
        logger.exception("failed to mark provisioning running for %s", slug)


async def _poll_worker(tenant_id: str, slug: str, database_name: str,
                       token: str, brand_name: str, welcome_media: dict,
                       admin_ids: list, reseller_enabled: bool,
                       stop_event: asyncio.Event):
    """Long-poll one bot token and dispatch updates under its tenant scope."""
    from db import client
    from bot import process_update
    from bot_tenant_scope import BotTenantScope, use_bot_tenant

    db_handle = client[database_name]
    scope = BotTenantScope(
        tenant_id=tenant_id, slug=slug, database_name=database_name,
        db_handle=db_handle, bot_token=token, brand_name=brand_name,
        welcome_media=welcome_media or {},
        admin_ids=[int(x) for x in (admin_ids or [])],
        reseller_enabled=bool(reseller_enabled),
    )
    offset = None
    api = f"https://api.telegram.org/bot{token}"
    logger.info("worker started for tenant %s", slug)
    async with _http_client() as http:
        # Resolve the BotFather display name once; the /start greeting uses
        # it instead of the generic "Bot Store" fallback.
        try:
            r = await http.post(f"{api}/getMe")
            data = r.json()
            if data.get("ok"):
                scope.bot_display_name = (
                    data.get("result") or {}).get("first_name", "")
        except Exception:
            logger.exception("getMe failed for %s", slug)
    async with _http_client() as http:
        while not stop_event.is_set():
            try:
                params = {"timeout": POLL_TIMEOUT}
                if offset is not None:
                    params["offset"] = offset
                r = await http.post(f"{api}/getUpdates", json=params)
                data = r.json()
                if not data.get("ok"):
                    logger.warning("getUpdates not ok for %s: %s", slug, data)
                    await asyncio.sleep(5)
                    continue
                for update in data.get("result", []):
                    update_id = update.get("update_id")
                    if update_id is not None:
                        offset = update_id + 1
                        try:
                            # Namespaced by slug: two bots sharing one database
                            # (e.g. central + tenant) have independent
                            # update_id sequences.
                            await db_handle.processed_updates.insert_one(
                                {"_id": f"{slug}:{update_id}",
                                 "update_id": update_id})
                        except Exception:
                            continue  # duplicate: skip
                    async with use_bot_tenant(scope):
                        try:
                            await process_update(update)
                        except Exception:
                            logger.exception("process_update failed for %s", slug)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("poll loop error for %s; backing off", slug)
                await asyncio.sleep(5)
    logger.info("worker stopped for tenant %s", slug)


class Dispatcher:
    def __init__(self):
        self._workers: dict[str, tuple[asyncio.Task, asyncio.Event, str, str]] = {}
        # slug -> (task, stop_event, token_fingerprint, media_fingerprint)

    @staticmethod
    def _fingerprint(token: str) -> str:
        return token[:6] + "..." + token[-4:]

    @staticmethod
    def _media_fingerprint(welcome_media: dict, admin_ids: list | None = None,
                           reseller_enabled: bool = True) -> str:
        import hashlib, json
        payload = {"media": welcome_media or {},
                   "admins": sorted(int(x) for x in (admin_ids or [])),
                   "reseller": bool(reseller_enabled)}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()[:12]

    async def reconcile(self):
        from welcome_banner import normalize_welcome_media
        desired: dict[str, tuple] = {}
        for tenant, token, database_name in await _load_active_bot_tenants():
            slug = tenant.get("slug") or tenant.get("tenant_id")
            metadata = tenant.get("metadata") or {}
            bot_config = metadata.get("bot_config") or {}
            brand = bot_config.get("brand_name", "")
            welcome_media = normalize_welcome_media(bot_config)
            admin_ids = bot_config.get("admin_ids") or []
            reseller_enabled = bot_config.get("reseller_enabled", False)
            desired[slug] = (str(tenant.get("_id") or slug), database_name,
                             token, brand, welcome_media, admin_ids,
                             reseller_enabled)

        # Central (platform owner) bot worker, reconciled like a tenant.
        central = await _load_central_bot()
        if central is not None:
            token, brand, welcome_media, admin_ids, reseller_enabled, database_name = central
            desired["central"] = ("platform:central", database_name,
                                  token, brand, welcome_media, admin_ids,
                                  reseller_enabled)

        # Stop workers that are gone, suspended, rotated, or whose
        # welcome-media/admin/reseller config changed.
        for slug, (task, stop_event, fp, mfp) in list(self._workers.items()):
            want = desired.get(slug)
            if (want is None
                    or self._fingerprint(want[2]) != fp
                    or self._media_fingerprint(want[4], want[5], want[6]) != mfp):
                logger.info("stopping worker for %s", slug)
                stop_event.set()
                task.cancel()
                del self._workers[slug]

        # Start missing workers.
        for slug, (tenant_id, database_name, token, brand,
                   welcome_media, admin_ids, reseller_enabled) in desired.items():
            if slug not in self._workers:
                stop_event = asyncio.Event()
                task = asyncio.create_task(
                    _poll_worker(tenant_id, slug, database_name, token,
                                 brand, welcome_media, admin_ids,
                                 reseller_enabled, stop_event))
                self._workers[slug] = (task, stop_event,
                                       self._fingerprint(token),
                                       self._media_fingerprint(welcome_media,
                                                               admin_ids,
                                                               reseller_enabled))
                logger.info("started worker for tenant %s", slug)
                if slug != "central":
                    await _mark_provisioning_running(slug)

    async def run_forever(self):
        while True:
            try:
                await self.reconcile()
            except Exception:
                logger.exception("reconcile failed")
            await asyncio.sleep(RECONCILE_INTERVAL)


async def _amain(once: bool):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # Never log request URLs: they embed the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    dispatcher = Dispatcher()
    if once:
        await dispatcher.reconcile()
        print("workers:", sorted(dispatcher._workers))
        for _, (task, stop_event, _, _) in dispatcher._workers.items():
            stop_event.set()
            task.cancel()
        return
    await dispatcher.run_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(_amain(args.once))


if __name__ == "__main__":
    main()
