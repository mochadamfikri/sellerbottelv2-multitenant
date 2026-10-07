"""Sales summaries for Telegram broadcasts. All dates use Jakarta time."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from db import db
from services import fmt_amount

JAKARTA = ZoneInfo("Asia/Jakarta")


def report_window(kind: str, period: str = "30d", day: str | None = None):
    today = datetime.now(JAKARTA).date()
    if kind == "daily_recap":
        chosen = datetime.strptime(day, "%Y-%m-%d").date() if day else today - timedelta(days=1)
        if chosen > today:
            raise ValueError("Tanggal rekap tidak boleh di masa depan.")
        start = datetime(chosen.year, chosen.month, chosen.day, tzinfo=JAKARTA)
        end = start + timedelta(days=1)
        label = chosen.strftime("%d/%m/%Y")
    elif period in {"7d", "30d"}:
        end = datetime.now(JAKARTA)
        start = end - timedelta(days=7 if period == "7d" else 30)
        label = "7 hari terakhir" if period == "7d" else "30 hari terakhir"
    elif period == "all":
        return None, None, "sepanjang waktu"
    else:
        raise ValueError("Periode tidak valid.")
    return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat(), label


async def sales_summary(kind: str, period: str = "30d", day: str | None = None):
    start, end, label = report_window(kind, period, day)
    query = {"status": "delivered"}
    if start:
        query["created_at"] = {"$gte": start, "$lt": end}
    totals = defaultdict(float)
    products = defaultdict(lambda: {"name": "", "qty": 0, "sales": defaultdict(float)})
    units = 0
    async for order in db.purchases.find(query, {"items": 1, "total": 1, "currency": 1}):
        currency = order.get("currency") or "IDR"
        total = float(order.get("total") or 0)
        items = order.get("items") or []
        subtotal = sum(float(item.get("subtotal") or 0) for item in items)
        totals[currency] += total
        for item in items:
            qty = int(item.get("qty") or 0)
            if qty <= 0:
                continue
            key = str(item.get("product_id") or item.get("name") or "unknown")
            row = products[key]
            row["name"] = str(item.get("name") or row["name"] or "Produk")
            row["qty"] += qty
            units += qty
            # A coupon can discount the entire order. Allocate paid revenue by line value.
            line = float(item.get("subtotal") or 0)
            row["sales"][currency] += total * line / subtotal if subtotal else total * qty / max(1, sum(int(i.get("qty") or 0) for i in items))
    ranked = sorted(products.values(), key=lambda row: (-row["qty"], row["name"].casefold()))
    return {"label": label, "totals": dict(totals), "units": units,
            "products": [{"name": row["name"], "qty": row["qty"], "sales": dict(row["sales"])} for row in ranked]}


def amounts(values: dict) -> str:
    return " + ".join(fmt_amount(values[cur], cur) for cur in ("IDR", "USD") if cur in values) or "Rp 0"


def format_report(kind: str, summary: dict) -> str:
    if kind == "daily_recap":
        top = summary["products"][0] if summary["products"] else None
        return (f"📊 <b>Rekap Penjualan Harian</b>\n🗓️ {escape(summary['label'])} WIB\n\n"
                "<blockquote>"
                f"💰 Total penjualan: <b>{escape(amounts(summary['totals']))}</b>\n"
                f"📦 Produk terjual: <b>{summary['units']} unit</b>\n"
                f"🏆 Produk terlaris: <b>{escape(top['name']) if top else 'Belum ada'}</b>"
                + (f" ({top['qty']} unit)" if top else "")
                + "</blockquote>\n\n✅ Berdasarkan pesanan yang selesai dikirim.")
    lines = [f"🏆 <b>Produk Terlaris</b>\n🗓️ {escape(summary['label'])}"]
    if not summary["products"]:
        lines.append("\n<blockquote>📭 Belum ada produk terjual pada periode ini.</blockquote>")
    for index, row in enumerate(summary["products"][:5], 1):
        lines.extend(["", f"{index}. <b>{escape(row['name'])}</b>",
                      "<blockquote>"
                      f"📦 Terjual: <b>{row['qty']} unit</b>\n"
                      f"💰 Penjualan: <b>{escape(amounts(row['sales']))}</b>"
                      "</blockquote>"])
    lines.append("\n✅ Berdasarkan pesanan yang selesai dikirim.")
    return "\n".join(lines)
