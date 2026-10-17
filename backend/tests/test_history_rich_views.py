from history_rich_views import history_pages, transaction_detail_pages, wib


def money(value, currency):
    return f'{currency} {value}'


def test_history_historical_amount_and_no_secrets():
    order = {'_id':'o', 'total':120, 'items':[{'name':'Old product', 'qty':2}],
             'created_at':'2026-10-17T00:00:00Z', 'status':'delivered', 'secret':'PRIVATE'}
    pages = history_pages([('order','',order)], money)
    assert 'IDR 120' in pages[0].html
    assert 'Old product' in pages[0].html
    assert '07:00 WIB' in pages[0].html
    assert 'PRIVATE' not in str(pages)
    assert 'Snapshot historis tidak tersedia' in str(transaction_detail_pages(order, 'order', money))


def test_deposit_context_and_fee_detail():
    dep = {'_id':'d', 'amount':100, 'payment_amount':110, 'admin_fee':10, 'status':'approved'}
    pages = history_pages([('deposit','',dep)], money)
    assert 'Nominal' in pages[0].html and 'IDR 100' in pages[0].html
    detail = transaction_detail_pages(dep, 'deposit', money)
    assert 'IDR 110' in str(detail) and 'Biaya admin' in str(detail)


def test_snapshot_and_invalid_date():
    order = {'_id':'o', 'items':[{'name':'X', 'warranty_snapshot':{'enabled':True, 'duration':'7 hari', 'coverage':'Actual'}}]}
    result = str(transaction_detail_pages(order, 'order', money))
    assert '7 hari' in result and 'Actual' in result
    assert wib(None) == 'Waktu tidak tersedia'
