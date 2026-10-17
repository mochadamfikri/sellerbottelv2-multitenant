import asyncio
import pytest
from mongomock_motor import AsyncMongoMockClient
import bot
import rich_table_transport
from bot_tenant_scope import BotTenantScope, use_bot_tenant
from product_catalog import catalog_token


@pytest.mark.parametrize('success', [True, False])
@pytest.mark.parametrize('view', ['catalog', 'detail', 'stock'])
def test_native_catalog_scope_buttons_and_safe_replacement(monkeypatch, success, view):
    monkeypatch.setenv('TELEGRAM_RICH_TABLES_ENABLED', 'true')
    calls, deleted = [], []
    async def send(chat, page, kb):
        calls.append((page, kb))
        return {'ok': success, 'result': {'message_id': 99}}
    async def delete(chat, mid):
        deleted.append(mid)
    monkeypatch.setattr(rich_table_transport, 'send_table', send)
    monkeypatch.setattr(bot, '_delete_flow_messages', delete)
    async def run():
        client = AsyncMongoMockClient()
        a, b = client['rich_a'], client['rich_b']
        product = {'_id':'a1', 'active':True, 'name':'Product <A>', 'catalog_name':'Category',
                   'product_kind':'service', 'delivery_type':'service', 'price_idr':36000,
                   'description':'Public description', 'secret':'NEVER_RENDER'}
        await a.products.insert_one(product)
        await b.products.insert_one({**product, '_id':'b1', 'name':'OTHER_TENANT'})
        await a.products.insert_one({**product, '_id':'hidden', 'active':False})
        scope = BotTenantScope('a', 'a', 'rich_a', db_handle=a)
        with use_bot_tenant(scope):
            bot._EDIT_TARGETS[123] = 10
            user = {'currency':'IDR', 'lang':'id', 'telegram_id':123}
            if view == 'catalog':
                await bot.show_products(123, user, catalog=catalog_token(product))
            elif view == 'detail':
                await bot.show_product_detail(123, user, 'a1')
            else:
                await bot.show_stock_view(123, user)
        page, kb = calls[0]
        for header in ['Product','Stock','Harga','Garansi','Deskripsi']:
            assert header in page.html
        assert 'OTHER_TENANT' not in page.html and 'NEVER_RENDER' not in page.html
        assert '&lt;A&gt;' in page.html and 'Public description' in page.html
        callbacks = [v['callback_data'] for r in kb['inline_keyboard'] for v in r]
        expected = {'catalog':'prod:a1', 'detail':'buy:a1', 'stock':'stockadd:1:a1'}[view]
        assert expected in callbacks
        assert all('hidden' not in c for c in callbacks)
        assert deleted == ([10] if success else [])
    asyncio.run(run())
