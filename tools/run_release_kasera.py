"""Isolated development webhook runtime; no Telegram, SMTP or live adapters."""
import os
import asyncio
from contextlib import asynccontextmanager
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
private = ROOT / 'backend/.release-kasera-private.json'
config = json.loads(private.read_text())
path = os.environ['PATH']
os.environ.clear()
os.environ.update(PATH=path, PYTHON_DOTENV_DISABLED='1', ENVIRONMENT='development',
                  PHASE3_SANDBOX_ENABLED='true', COMMERCE_LAUNCH_PROFILE='v1_kasera',
                  MONGO_URL='mongodb://127.0.0.1:27019/?serverSelectionTimeoutMS=3000',
                  DB_NAME=config['database'], PLATFORM_DB_NAME=config['database'],
                  JWT_SECRET=config['jwt'], INVENTORY_ENCRYPTION_KEY=config['encryption_key'])
if config.get('uat_bridge') is True:
    os.environ['KASERA_UAT_BRIDGE']='true'
from fastapi import FastAPI
from payments.public_webhook import router
from error_handlers import register_error_handlers
from db import client
@asynccontextmanager
async def lifespan(app):
    # Repair only already-authenticated durable receipts; no polling can stand
    # in for the genuine-callback acceptance check.
    from payments.webhook import process_receipt
    from payments.models import now
    from db import platform_db
    async def repair():
        while True:
            try:
                platform = platform_db()
                receipts = await platform.payment_events.find({'$or': [{'state': 'accepted'}, {'state': 'processing', 'lease_until': {'$lte': now()}}]}).limit(50).to_list(50)
                for receipt in receipts:
                    try:
                        await process_receipt(platform, client, receipt)
                    except Exception:
                        pass  # Receipt retains safe failure state for retry.
            except Exception:
                pass
            await asyncio.sleep(10)
    worker = asyncio.create_task(repair())
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        client.close()

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(router)
register_error_handlers(app)

@app.get('/health')
async def health():
    await client.admin.command('ping')
    return {'status': 'ok', 'environment': 'sandbox'}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8007, access_log=False)
