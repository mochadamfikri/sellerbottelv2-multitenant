"""Ambient per-tenant scope for bot workers (dispatcher).

The legacy bot code was written single-tenant: modules do ``from db import db``
and call ``tgapi.send_message(...)`` with an env-baked token.  Rather than
rewriting hundreds of call sites, the dispatcher installs a
:class:`BotTenantScope` around each processed update; the ``db`` proxy
(see db.py) and ``tgapi`` resolve the current tenant's database handle and
bot token from here.

This is separate from ``tenant_context.py``, which resolves tenants for HTTP
requests via the ``X-Tenant-ID`` header.  This module is the ambient execution
context for background bot workers.

When no scope is installed (plain API server, legacy single-tenant flows),
all resolvers fall back to the historical defaults, so existing behaviour is
unchanged.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class BotTenantScope:
    tenant_id: str
    slug: str
    database_name: str
    db_handle: Any = None
    bot_token: Optional[str] = None
    brand_name: str = ""
    # BotFather display name (first_name from getMe), resolved once per
    # worker at startup.  Used for the /start greeting header.
    bot_display_name: str = ""
    # Welcome media config for /start.  Normalized dict:
    #   {"enabled": bool, "mode": "auto" | "upload",
    #    "file": "<file_id|url|local path>",   # upload mode
    #    "tagline": "<banner tagline>"}          # auto mode
    # Empty/disabled = text-only welcome (legacy behaviour).
    welcome_media: dict = None
    # Telegram user IDs treated as bot admins/owners (per-bot).
    admin_ids: list = None
    # Whether the "Bikin Bot Sendiri" reseller entry is active for this bot.
    # Central bot defaults True; tenant bots default False (platform admin
    # enables per tenant).
    reseller_enabled: bool = False

    def __post_init__(self):
        if self.welcome_media is None:
            self.welcome_media = {}
        if self.admin_ids is None:
            self.admin_ids = []


_scope: contextvars.ContextVar[Optional[BotTenantScope]] = contextvars.ContextVar(
    "sellerbottel_bot_tenant", default=None
)


def get_current_scope() -> Optional[BotTenantScope]:
    return _scope.get()


def _install(scope: Optional[BotTenantScope]):
    return _scope.set(scope)


def _restore(token) -> None:
    _scope.reset(token)


class use_bot_tenant:
    """Sync/async context manager installing a BotTenantScope."""

    def __init__(self, scope: BotTenantScope):
        self._scope = scope
        self._token = None

    def __enter__(self):
        self._token = _install(self._scope)
        return self._scope

    def __exit__(self, *exc):
        _restore(self._token)
        return False

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, *exc):
        return self.__exit__(*exc)


from collections.abc import MutableMapping


class TenantScopedDict(MutableMapping):
    """Legacy in-memory flow state partitioned by database and bot identity."""

    def __init__(self):
        self._values = {}

    def _bucket(self):
        import hashlib
        scope = get_current_scope()
        key = None if scope is None else (
            scope.database_name, scope.slug,
            hashlib.sha256((scope.bot_token or "").encode()).hexdigest(),
        )
        return self._values.setdefault(key, {})

    def __getitem__(self, key):
        return self._bucket()[key]

    def __setitem__(self, key, value):
        self._bucket()[key] = value

    def __delitem__(self, key):
        del self._bucket()[key]

    def __iter__(self):
        return iter(self._bucket())

    def __len__(self):
        return len(self._bucket())
