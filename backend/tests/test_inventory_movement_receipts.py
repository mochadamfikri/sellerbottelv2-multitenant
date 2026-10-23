import asyncio
from cryptography.fernet import Fernet
from mongomock_motor import AsyncMongoMockClient
import inventory
import stock_monitor
from bot_tenant_scope import BotTenantScope, use_bot_tenant


def test_atomic_receipts_and_repeated_transition_idempotency(monkeypatch):
    monkeypatch.setenv('INVENTORY_ENCRYPTION_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr(stock_monitor, 'schedule_stock_scan', lambda *a: None)
    async def run():
        db = AsyncMongoMockClient()['movement_test']
        with use_bot_tenant(BotTenantScope('test','test','movement_test',db_handle=db)):
            await inventory.add_records('p', [{'value':'PRIVATE'}], ['value'])
            await inventory.reserve_items('p', 1, 'r1')
            await inventory.release_items('r1')
            await inventory.release_items('r1')
            await inventory.reserve_items('p', 1, 'r2')
            await inventory.commit_items('r2', 'order1', 123)
            await inventory.commit_items('r2', 'order1', 123)
            item = await db.inventory_items.find_one({'product_id':'p'})
            receipts = item['movement_audit']
            assert [r['action'] for r in receipts] == ['in','reserved','release','reserved','sold']
            assert sum(r['quantity'] for r in receipts) == 0
            assert receipts[-1]['reference'] == 'order1'
            assert 'PRIVATE' not in str(receipts)
            assert item['status'] == 'sold'
    asyncio.run(run())
