import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import FastAPI
from payments import public_webhook

@pytest.mark.parametrize('environment,enabled,reference,forward', [('development','true','uat-payment',True),('production','true','uat-payment',False),('development','false','uat-payment',False),('development','true','legacy-payment',False)])
def test_bridge_routes_only_explicit_uat_and_preserves_raw_signature(monkeypatch,environment,enabled,reference,forward):
    monkeypatch.setenv('ENVIRONMENT',environment)
    monkeypatch.setenv('KASERA_UAT_BRIDGE',enabled)
    receive=AsyncMock(return_value={'ok':True});monkeypatch.setattr(public_webhook,'receive',receive)
    original=httpx.AsyncClient
    raw=('{ "data": { "external_id": "'+reference+'" } }').encode()
    async def run():
        app=FastAPI();app.include_router(public_webhook.router)
        async with original(transport=httpx.ASGITransport(app=app),base_url='http://test') as caller:
            class Bridge:
                def __init__(self,**kwargs):assert kwargs['follow_redirects'] is False
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                async def post(self,url,content,headers):
                    assert url=='http://127.0.0.1:8010/api/payments/webhooks/kasera'
                    assert content==raw and headers['Kasera-Signature-V1']=='raw-signature'
                    return httpx.Response(403,json={'detail':'Invalid signature'})
            monkeypatch.setattr(httpx,'AsyncClient',Bridge)
            response=await caller.post('/api/payments/webhooks/kasera',content=raw,headers={'Kasera-Signature-V1':'raw-signature'})
            assert response.status_code==(403 if forward else 200)
            assert receive.await_count==(0 if forward else 1)
    asyncio.run(run())
