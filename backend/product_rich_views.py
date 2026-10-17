"""Product presentation only. Callers supply authorized product, stock and price."""
from rich_tables import table_pages


def warranty_label(product):
    warranty = product.get('warranty')
    if not isinstance(warranty, dict) or not isinstance(warranty.get('enabled'), bool):
        return 'Belum diinformasikan'
    if not warranty['enabled']:
        return 'Tidak Ada'
    return str(warranty.get('duration') or 'Ada; durasi belum diinformasikan')


def _continuations(label, value):
    # 600 code points fits even astral emoji and HTML escaping budgets.
    value = str(value)
    return [(label if start == 0 else label + ' (lanjutan)', value[start:start+600])
            for start in range(0, len(value), 600)] or [(label, '—')]


def product_detail_pages(product, stock, price_text):
    rows = []
    for label, value in [('Product', product.get('name') or '—'),
                         ('Stock', 'Unlimited' if stock is None else str(stock)),
                         ('Harga', price_text), ('Garansi', warranty_label(product)),
                         ('Deskripsi', product.get('description') or 'Belum dilengkapi')]:
        rows.extend(_continuations(label, value))
    pages = table_pages('Detail Produk', ['Informasi', 'Detail'], rows)
    warranty = product.get('warranty')
    if isinstance(warranty, dict) and warranty.get('enabled') is True:
        terms = []
        for key, label in [('duration','Durasi'), ('coverage','Cakupan'),
                           ('terms','Syarat'), ('claim_process','Cara klaim')]:
            if warranty.get(key):
                terms.extend(_continuations(label, warranty[key]))
        if terms:
            pages += table_pages('Garansi', ['Aspek Garansi', 'Ketentuan'], terms)
    return pages
