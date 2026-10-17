"""History presentation from authorized immutable transaction records only."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from rich_tables import table_pages
from product_rich_views import _continuations


def wib(value):
    try:
        date = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.astimezone(ZoneInfo('Asia/Jakarta')).strftime('%d/%m/%Y %H:%M WIB')
    except (TypeError, ValueError):
        return 'Waktu tidak tersedia'


def history_pages(events, format_amount):
    pages = []
    # Keep transaction order; adjacent kinds form separate contextual tables.
    groups = []
    for kind, _, item in events:
        if not groups or groups[-1][0] != kind:
            groups.append((kind, []))
        groups[-1][1].append(item)
    for kind, items in groups:
        rows = []
        for item in items:
            currency = item.get('currency') or 'IDR'
            if kind == 'order':
                names = ', '.join(str(x.get('name') or 'Produk') for x in item.get('items', []))
                rows.append([str(item.get('invoice_id') or item['_id'])[:100], names[:160],
                             format_amount(item.get('total', 0), currency), wib(item.get('created_at')),
                             str(item.get('status') or 'unknown')[:50]])
            else:
                rows.append([str(item['_id'])[:100], str(item.get('method') or '—')[:80],
                             format_amount(item.get('amount', 0), currency), wib(item.get('created_at')),
                             str(item.get('status') or 'unknown')[:50]])
        headers = ['Order ID', 'Product', 'Harga Dibayar', 'Tanggal', 'Status'] if kind == 'order' else ['Deposit ID', 'Metode', 'Nominal', 'Tanggal', 'Status']
        pages.extend(table_pages('Riwayat Pembelian' if kind == 'order' else 'Riwayat Deposit', headers, rows, page_size=5))
    return pages or table_pages('Riwayat', ['Informasi', 'Detail'], [])


def transaction_detail_pages(record, kind, format_amount):
    currency = record.get('currency') or 'IDR'
    rows = [('Order ID' if kind == 'order' else 'Deposit ID', record['_id']),
            ('Status', record.get('status') or 'unknown'), ('Waktu', wib(record.get('created_at')))]
    if kind == 'order':
        rows += [('Invoice', record.get('invoice_id') or '—'),
                 ('Harga Dibayar', format_amount(record.get('total', 0), currency))]
        for item in record.get('items', []):
            rows.extend(_continuations('Product', item.get('name') or 'Produk'))
            rows.append(('Qty', str(item.get('qty') or 0)))
            # Never query today's catalog or invent historical warranty.
            snapshot = item.get('warranty_snapshot')
            if isinstance(snapshot, dict):
                from product_rich_views import warranty_label
                rows.extend(_continuations('Garansi', warranty_label({'warranty':snapshot})))
                if snapshot.get('enabled') is True:
                    for key, label in [('coverage','Cakupan'), ('terms','Syarat'), ('claim_process','Cara klaim')]:
                        if snapshot.get(key):
                            rows.extend(_continuations(label, snapshot[key]))
            else:
                rows.append(('Garansi', 'Snapshot historis tidak tersedia'))
    else:
        rows += [('Metode', record.get('method') or '—')]
        for key, label in [('amount','Nominal'), ('admin_fee','Biaya admin'), ('platform_code','Kode platform'),
                           ('payment_amount','Total pembayaran'), ('credited_amount','Saldo dikreditkan')]:
            if record.get(key) is not None:
                rows.append((label, format_amount(record[key], currency)))
    return table_pages('Detail Transaksi', ['Informasi', 'Detail'], rows)
