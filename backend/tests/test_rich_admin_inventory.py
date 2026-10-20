import asyncio
from mongomock_motor import AsyncMongoMockClient
import bot
import rich_table_transport
from bot_tenant_scope import BotTenantScope, use_bot_tenant


def test_admin_inventory_denies_customer_and_counts_only_current_tenant(monkeypatch):
    monkeypatch.setenv('TELEGRAM_RICH_TABLES_ENABLED', 'true')
    sent, denied = [], []
    async def send(chat, page, kb=None):
        sent.append(page)
        return {'ok': True, 'result': {'message_id': 8}}
    async def plain(chat, text, kb=None):
        denied.append(text)
    monkeypatch.setattr(rich_table_transport, 'send_table', send)
    monkeypatch.setattr(bot, 'send_message', plain)
    async def run():
        client = AsyncMongoMockClient()
        a, b = client['a'], client['b']
        await a.products.insert_one({'_id':'p','name':'Local'})
        await b.products.insert_one({'_id':'p','name':'OTHER'})
        await a.inventory_items.insert_many([
            {'_id':str(i), 'product_id':'p', 'status':status, 'secret':'PRIVATE'}
            for i, status in enumerate(['available','available','reserved','sold','marketing_allocated'])])
        await b.inventory_items.insert_one({'product_id':'p','status':'available'})
        with use_bot_tenant(BotTenantScope('a','a','a',db_handle=a,admin_ids=[10])):
            await bot.show_admin_inventory_tables(9, {'telegram_id':9})
            assert not sent and denied == ['Akses ditolak.']
            await bot.show_admin_inventory_tables(10, {'telegram_id':10})
        assert len(sent) == 1
        assert 'Available: 2' in sent[0].fallback
        assert 'Reserved: 1' in sent[0].fallback and 'Sold: 1' in sent[0].fallback
        assert 'Total Masuk: Belum terverifikasi' in sent[0].fallback
        assert 'OTHER' not in str(sent) and 'PRIVATE' not in str(sent)
    asyncio.run(run())
