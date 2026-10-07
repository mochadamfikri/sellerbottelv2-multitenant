"""Tests for bot_tenant_scope + the db proxy (no Telegram I/O)."""
import asyncio
import os
from functools import wraps

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27018")
os.environ.setdefault("DB_NAME", "sellerbottel_test_proxy")

from bot_tenant_scope import BotTenantScope, get_current_scope, use_bot_tenant  # noqa: E402


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def test_no_scope_by_default():
    assert get_current_scope() is None


def test_scope_install_and_reset():
    scope = BotTenantScope(tenant_id="t1", slug="t1", database_name="db1")
    with use_bot_tenant(scope):
        assert get_current_scope() is scope
    assert get_current_scope() is None


def test_nested_scopes_restore_outer():
    outer = BotTenantScope(tenant_id="o", slug="o", database_name="dbo")
    inner = BotTenantScope(tenant_id="i", slug="i", database_name="dbi")
    with use_bot_tenant(outer):
        with use_bot_tenant(inner):
            assert get_current_scope() is inner
        assert get_current_scope() is outer
    assert get_current_scope() is None


@async_test
async def test_async_context_manager():
    scope = BotTenantScope(tenant_id="a", slug="a", database_name="dba")
    async with use_bot_tenant(scope):
        assert get_current_scope() is scope
    assert get_current_scope() is None
