from product_rich_views import product_detail_pages, warranty_label


def test_unknown_and_no_warranty_are_distinct():
    assert warranty_label({}) == 'Belum diinformasikan'
    p = {'name':'X', 'description':'D', 'warranty':{'enabled':False, 'coverage':'stale'}}
    pages = product_detail_pages(p, 0, 'Rp0')
    assert len(pages) == 1
    assert 'Tidak Ada' in pages[0].html
    assert 'stale' not in pages[0].html
    for field in ['Product', 'Stock', 'Harga', 'Garansi', 'Deskripsi']:
        assert field in pages[0].html


def test_actual_warranty_only_and_escaping():
    p = {'name':'<X>', 'warranty':{'enabled':True, 'coverage':'<replace>'}}
    pages = product_detail_pages(p, None, 'Rp10.000')
    assert len(pages) == 2
    assert '&lt;replace&gt;' in pages[1].html
    assert 'Cara klaim' not in pages[1].html
    assert '30 hari' not in str(pages)


def test_long_unicode_description_preserved_with_bounded_pages():
    text = '😀<&>' * 2000
    pages = product_detail_pages({'name':'X', 'description':text}, 2, 'Rp10')
    assert len(pages) > 1
    assert sum(p.fallback.count('😀') for p in pages) == 2000
    assert all(len(p.fallback.encode('utf-16-le')) // 2 <= 3900 for p in pages)
    assert all(len(p.html.encode()) <= 30000 for p in pages)
