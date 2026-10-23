import asyncio
import pytest
from mongomock_motor import AsyncMongoMockClient
import bot
import rich_table_transport
from bot_tenant_scope import BotTenantScope, use_bot_tenant


@pytest.mark.parametrize('kind', ['order', 'deposit'])
def test_detail_ownership_and_tenant_rechecked(monkeypatch, kind):
    monkeypatch.setenv('TELEGRAM_RICH_TABLES_ENABLED', 'true')
    rendered, errors = [], []
    async def send(chat, page, kb=None):
        rendered.append(page)
        return {'ok':True, 'result':{'message_id':5}}
    async def plain(chat, text, kb=None):
        errors.append(text)
    monkeypatch.setattr(rich_table_transport, 'send_table', send)
    monkeypatch.setattr(bot, 'send_message', plain)
    async def run():
        client = AsyncMongoMockClient()
        a, b = client['a'], client['b']
        coll = 'purchases' if kind == 'order' else 'deposits'
        base = {'user_tid':123, 'status':'approved', 'total':10, 'amount':10, 'items':[], 'secret':'PRIVATE'}
        await a[coll].insert_one({**base, '_id':'owned'})
        await a[coll].insert_one({**base, '_id':'other', 'user_tid':999})
        await b[coll].insert_one({**base, '_id':'cross'})
        fn = bot.show_order_history_detail if kind == 'order' else bot.show_deposit_history_detail
        with use_bot_tenant(BotTenantScope('a','a','a',db_handle=a)):
            for identifier in ['other','cross']:
                await fn(123, {'telegram_id':123,'lang':'id'}, identifier)
            assert not rendered and len(errors) == 2
            await fn(123, {'telegram_id':123,'lang':'id'}, 'owned')
        assert rendered and 'PRIVATE' not in str(rendered)
    asyncio.run(run())
