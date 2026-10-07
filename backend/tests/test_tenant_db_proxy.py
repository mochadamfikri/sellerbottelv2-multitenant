"""Isolation test: the db proxy must resolve per installed BotTenantScope.

Uses the local dev MongoDB (27018).  Inserts a marker into two databases and
asserts the proxy reads the right one depending on the ambient scope, and the
legacy default when no scope is installed.
"""
import asyncio
import os
from functools import wraps

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27018")
os.environ.setdefault("DB_NAME", "sellerbottel_test_proxy_default")

import db  # noqa: E402
from bot_tenant_scope import BotTenantScope, use_bot_tenant  # noqa: E402


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


@async_test
async def test_db_proxy_isolates_tenants():
    # Seed two databases directly through the raw client.
    await db.client["sellerbottel_test_tenant_a"]["settings"].delete_many({})
    await db.client["sellerbottel_test_tenant_b"]["settings"].delete_many({})
    await db.client["sellerbottel_test_tenant_a"]["settings"].insert_one(
        {"_id": "main", "marker": "A"})
    await db.client["sellerbottel_test_tenant_b"]["settings"].insert_one(
        {"_id": "main", "marker": "B"})

    scope_a = BotTenantScope(
        tenant_id="a", slug="a", database_name="sellerbottel_test_tenant_a",
        db_handle=db.client["sellerbottel_test_tenant_a"])
    scope_b = BotTenantScope(
        tenant_id="b", slug="b", database_name="sellerbottel_test_tenant_b",
        db_handle=db.client["sellerbottel_test_tenant_b"])

    with use_bot_tenant(scope_a):
        doc = await db.db.settings.find_one({"_id": "main"})
        assert doc["marker"] == "A"
    with use_bot_tenant(scope_b):
        doc = await db.db.settings.find_one({"_id": "main"})
        assert doc["marker"] == "B"

    # No scope -> proxy resolves to the legacy default database.
    assert db._resolve_db() is db._default_db

    # Cleanup.
    await db.client.drop_database("sellerbottel_test_tenant_a")
    await db.client.drop_database("sellerbottel_test_tenant_b")
