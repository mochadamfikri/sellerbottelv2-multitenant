import asyncio
import pytest
from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import DuplicateKeyError
from domain_registry import register_domain, ensure_domain_indexes, resolve_domain, list_domains
from tenant_db import resolve_platform_database_name
import os


def test_domain_ownership_idempotency_and_unique_index():
    async def run():
        client = AsyncMongoMockClient()
        await ensure_domain_indexes(client)
        await ensure_domain_indexes(client)
        first = await register_domain(client, domain=" Shop.Example.Test. ", tenant_id="A", purpose="storefront")
        again = await register_domain(client, domain="shop.example.test", tenant_id="A", purpose="storefront")
        assert again["created_at"] == first["created_at"]
        import json
        json.dumps(again)
        json.dumps(await list_domains(client))
        with pytest.raises(ValueError, match="tenant lain"):
            await register_domain(client, domain="shop.example.test", tenant_id="B", purpose="storefront")
        assert (await resolve_domain(client, "shop.example.test:443"))["tenant_id"] == "A"
        domains = client[resolve_platform_database_name(os.environ)].domains
        with pytest.raises(DuplicateKeyError):
            await domains.insert_one({"domain": "shop.example.test", "tenant_id": "B"})
    asyncio.run(run())


def test_competing_domain_claims_allow_one_owner():
    async def run():
        client = AsyncMongoMockClient()
        results = await asyncio.gather(*[
            register_domain(client, domain="race.example.test", tenant_id=owner, purpose="storefront")
            for owner in ("A", "B")
        ], return_exceptions=True)
        assert sum(isinstance(row, ValueError) for row in results) == 1
        assert sum(isinstance(row, dict) for row in results) == 1
    asyncio.run(run())
