"""Public Kasera-only ingress. Raw bytes are verified before financial effects."""
import json
import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from db import client, platform_db
from .webhook import receive

router = APIRouter()

@router.post('/api/payments/webhooks/kasera')
async def kasera_callback(request: Request):
    signature = request.headers.get('kasera-signature-v1', '')
    if not signature:
        raise HTTPException(422, 'Kasera signature required')
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > 65536:
            raise HTTPException(413, 'Webhook too large')
    # The existing development payment host retains its original namespace.
    # Only explicitly prefixed UAT references are forwarded to the isolated
    # full backend. The destination is fixed loopback, never payload-controlled.
    if os.getenv('KASERA_UAT_BRIDGE') == 'true' and os.getenv('ENVIRONMENT') == 'development':
        try:
            reference = json.loads(raw).get('data', {}).get('external_id')
        except (ValueError, AttributeError):
            reference = None
        if isinstance(reference, str) and reference.startswith('uat-'):
            import httpx
            async with httpx.AsyncClient(timeout=25, follow_redirects=False) as http:
                result = await http.post('http://127.0.0.1:8010/api/payments/webhooks/kasera', content=bytes(raw), headers={'Kasera-Signature-V1': signature, 'Content-Type': 'application/json'})
            return Response(content=result.content, status_code=result.status_code, media_type='application/json')
    return await receive(platform_db(), client, 'kasera', bytes(raw), signature)
