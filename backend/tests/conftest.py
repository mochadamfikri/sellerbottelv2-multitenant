"""All tests in this directory are offline, even when run without the runner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Install MongoDB mocks BEFORE test collection imports any application module.
# This also blocks outbound sockets, including legacy HTTP integration tests.
import run_offline_tests  # noqa: F401,E402

import asyncio
import inspect
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run async offline tests without requiring a network-installed plugin."""
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
    asyncio.run(pyfuncitem.obj(**kwargs))
    return True


@pytest.fixture(scope="module", autouse=True)
def isolate_mock_database_modules():
    """Discard mock data AND indexes left by unrelated test modules."""
    from db import client
    from mongomock_motor import AsyncMongoMockClient
    assert isinstance(client, AsyncMongoMockClient), "Tests must use mock MongoDB"

    async def reset():
        for name in await client.list_database_names():
            database = client[name]
            for collection in await database.list_collection_names():
                await database.drop_collection(collection)

    asyncio.run(reset())
    yield
    asyncio.run(reset())
