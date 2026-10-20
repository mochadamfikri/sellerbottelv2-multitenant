"""Pure, bounded native Telegram HTML tables; no database or transport imports."""
from dataclasses import dataclass
from decimal import Decimal
from html import escape


@dataclass(frozen=True)
class TablePage:
    html: str
    fallback: str


def idr(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("Invalid monetary amount")
    return "Rp" + format(amount.quantize(Decimal('1')), ',').replace(',', '.')


def table_pages(title, headers, rows, *, page_size=8, align=None):
    """Preserve every cell; reject oversized single rows rather than drop data.

    Fallback is plain labelled text (never parsed as HTML). Conservative limits
    keep each page suitable for both rich messages and sendMessage fallback.
    Input ordering is preserved; callers own stable sorting and tenant checks.
    """
    if not 1 <= len(headers) <= 20 or not 1 <= page_size <= 10:
        raise ValueError("Invalid table dimensions")
    headers = tuple(str(x) for x in headers)
    align = tuple(align or ['left'] * len(headers))
    if len(align) != len(headers) or any(x not in ('left', 'center', 'right') for x in align):
        raise ValueError("Invalid alignment")
    title = str(title)
    if len(title) > 200:
        raise ValueError("Title too long")
    normalized = []
    for row in rows:
        if len(row) != len(headers):
            raise ValueError("Row width mismatch")
        normalized.append(tuple(str(x) if x is not None else '—' for x in row))

    def render(batch):
        html = '<h3>' + escape(title) + '</h3><table bordered striped compact><tr>'
        html += ''.join('<th>' + escape(x) + '</th>' for x in headers) + '</tr>'
        text = [title]
        for row in batch:
            html += '<tr>' + ''.join(f'<td align="{a}">{escape(v)}</td>' for a, v in zip(align, row)) + '</tr>'
            text.append('\n'.join(f'{h}: {v}' for h, v in zip(headers, row)))
        html += '</table>'
        return TablePage(html, '\n\n'.join(text))

    if not normalized:
        return [TablePage('<p>' + escape(title) + '</p><p>Belum ada data.</p>', title + '\n\nBelum ada data.')]
    pages, batch = [], []
    for row in normalized:
        candidate = render(batch + [row])
        if len(batch) >= page_size or len(candidate.fallback.encode('utf-16-le')) // 2 > 3900 or len(candidate.html.encode()) > 30000:
            if batch:
                pages.append(render(batch))
            batch = []
            candidate = render([row])
        if len(candidate.fallback.encode('utf-16-le')) // 2 > 3900 or len(candidate.html.encode()) > 30000:
            raise ValueError('Single row exceeds page budget; use detail continuation')
        batch.append(row)
    if batch:
        pages.append(render(batch))
    return pages
