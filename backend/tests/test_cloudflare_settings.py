from __future__ import annotations

import asyncio
from functools import wraps

import httpx
import pytest
from fastapi import HTTPException


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return wrapper


@async_test
async def test_verify_cloudflare_token_requires_every_managed_zone(monkeypatch):
    from cloudflare_settings import verify_cloudflare_token
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer cf_test_token_never_persisted"
        if request.url.path.endswith("/user/tokens/verify"):
            return httpx.Response(200, json={"success": True, "result": {"status": "active"}})
        if request.url.params.get("name") == "idsestock.my.id":
            return httpx.Response(200, json={"success": True, "result": [{"name": "idsestock.my.id"}]})
        return httpx.Response(200, json={"success": True, "result": []})

    class Client:
        def __init__(self, *args, **kwargs):
            self.client = real_async_client(transport=httpx.MockTransport(handler), base_url="https://api.cloudflare.com")
        async def __aenter__(self): return self.client
        async def __aexit__(self, *args): await self.client.aclose()

    monkeypatch.setattr("cloudflare_settings.httpx.AsyncClient", Client)
    with pytest.raises(HTTPException, match="idseconnect.my.id"):
        await verify_cloudflare_token("cf_test_token_never_persisted")


def test_cloudflare_status_never_returns_encrypted_token():
    from cloudflare_settings import _public_status

    result = _public_status({
        "token_encrypted": "ciphertext-must-not-leak",
        "token_hint": "cf_tok_...1234",
        "status": "verified",
        "verified_zones": ["idsestock.my.id"],
    })
    assert result["configured"] is True
    assert result["token_hint"] == "cf_tok_...1234"
    assert "token_encrypted" not in result
