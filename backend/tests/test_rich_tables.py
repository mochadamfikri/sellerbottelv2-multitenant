import asyncio
import httpx
import pytest
from rich_tables import table_pages, idr
import rich_table_transport as transport


def test_escape_and_plain_fallback():
    page = table_pages('Catalog <x>', ['Product', 'Stock'], [['<script>&"', 0]])[0]
    assert '<script>' not in page.html
    assert '&lt;script&gt;&amp;&quot;' in page.html
    assert 'Product: <script>&"' in page.fallback
    assert '<table bordered striped compact>' in page.html


def test_pages_preserve_rows_and_empty_state():
    pages = table_pages('Products', ['ID'], [[str(i)] for i in range(21)])
    assert len(pages) == 3
    assert sum(p.html.count('<td ') for p in pages) == 21
    assert table_pages('Empty', ['ID'], [])[0].fallback.endswith('Belum ada data.')


@pytest.mark.parametrize('kwargs', [{'align':['injected']}, {'page_size':0}])
def test_invalid_options(kwargs):
    with pytest.raises(ValueError):
        table_pages('T', ['ID'], [['x']], **kwargs)


def test_long_row_rejected_without_silent_truncation():
    with pytest.raises(ValueError):
        table_pages('T', ['ID'], [['x'*5000]])


def test_currency():
    assert idr(36000) == 'Rp36.000'
    for value in [-1, 'NaN', 'Infinity']:
        with pytest.raises(ValueError):
            idr(value)


@pytest.mark.parametrize('mode', ['off', 'success', 'reject', 'timeout', 'rate', 'server'])
def test_transport(monkeypatch, mode):
    calls = []
    monkeypatch.setenv('TELEGRAM_RICH_TABLES_ENABLED', 'false' if mode == 'off' else 'true')
    async def fake(method, **payload):
        calls.append((method, payload))
        if method == 'sendRichMessage':
            if mode == 'timeout':
                raise httpx.ReadTimeout('secret must not be logged')
            if mode in {'reject', 'rate', 'server'}:
                return {'ok': False, 'error_code': {'reject':400, 'rate':429, 'server':500}[mode]}
        return {'ok': True, 'result': {'message_id':1}}
    monkeypatch.setattr(transport, 'tg', fake)
    kb = {'inline_keyboard': [[{'text':'Back', 'callback_data':'menu:main'}]]}
    result = asyncio.run(transport.send_table(123, table_pages('T', ['ID'], [['a']])[0], kb))
    assert len(calls) == (2 if mode == 'reject' else 1)
    assert all(p['reply_markup'] == kb for _, p in calls)
    if mode in {'off', 'reject'}:
        assert calls[-1][0] == 'sendMessage'
        assert 'parse_mode' not in calls[-1][1]
        assert '<table' not in calls[-1][1]['text']
    if mode == 'timeout':
        assert result['delivery_status'] == 'unknown'
    if mode == 'success':
        assert set(calls[0][1]['rich_message']) == {'html', 'skip_entity_detection'}
