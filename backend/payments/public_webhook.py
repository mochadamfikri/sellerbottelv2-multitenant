"""Public Kasera-only ingress. Raw bytes are verified before financial effects."""
from fastapi import APIRouter, HTTPException, Request
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
    return await receive(platform_db(), client, 'kasera', bytes(raw), signature)
