from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import os

BG = (8, 24, 22)
PANEL = (16, 43, 37)
PURPLE = (91, 220, 172)
WHITE = (248, 245, 255)
MUTED = (169, 196, 185)
GREEN = (92, 224, 154)

def _font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def _fit(draw, text, font, max_width):
    text = str(text)
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    while len(text) > 4 and draw.textbbox((0, 0), text + "…", font=font)[2] > max_width:
        text = text[:-1]
    return text + "…"

def render_transaction_image(total_qty, total_amount, currency="IDR", title="PENJUALAN BERHASIL"):
    width, height = 1200, 700
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    for r in range(360, 20, -20):
        alpha = int(32 * (1 - r / 380))
        c = (PURPLE[0] // 3 + alpha, PURPLE[1] // 3 + alpha, PURPLE[2] // 3 + alpha)
        draw.ellipse((width - r, -r // 2, width + r, r // 2), outline=c, width=3)
    draw.rounded_rectangle((55, 55, width - 55, height - 55), 28, fill=PANEL, outline=(42, 83, 66), width=2)
    brand_font = _font(32, True)
    title_font = _font(66, True)
    big_font = _font(92, True)
    label_font = _font(25, True)
    value_font = _font(42, True)
    draw.text((95, 90), "IDSE MARKETPLACE", font=brand_font, fill=PURPLE)
    draw.text((95, 155), title, font=title_font, fill=WHITE)
    cx, cy = 1060, 180
    draw.ellipse((cx - 45, cy - 45, cx + 45, cy + 45), fill=(32, 80, 62), outline=GREEN, width=3)
    draw.line((cx - 20, cy, cx - 5, cy + 16), fill=GREEN, width=8)
    draw.line((cx - 5, cy + 16, cx + 24, cy - 18), fill=GREEN, width=8)
    draw.text((95, 285), "TOTAL ORDER", font=label_font, fill=MUTED)
    qty = _fit(draw, f"{int(total_qty):,} ITEM", big_font, 480)
    draw.text((95, 320), qty, font=big_font, fill=WHITE)
    draw.text((650, 285), "TOTAL TRANSAKSI", font=label_font, fill=MUTED)
    if currency == "IDR":
        amount = f"Rp {float(total_amount):,.0f}".replace(",", ".")
    else:
        amount = f"${float(total_amount):,.2f}"
    amount = _fit(draw, amount, value_font, 440)
    draw.text((650, 330), amount, font=value_font, fill=WHITE)
    draw.rounded_rectangle((95, 515, width - 95, 605), 18, fill=(31, 63, 51), outline=GREEN, width=2)
    status_font = _font(28, True)
    status = "✓ TRANSACTION COMPLETED"
    bbox = draw.textbbox((0, 0), status, font=status_font)
    draw.text(((width - (bbox[2] - bbox[0])) / 2, 543), status, font=status_font, fill=GREEN)
    out = BytesIO()
    image.save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()

def render_product_image(product_name, price, stock=None, description="", title="PRODUCT UPDATE"):
    width, height = 1200, 700
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((55, 55, width - 55, height - 55), 28, fill=PANEL, outline=(42, 83, 66), width=2)
    brand_font = _font(30, True)
    title_font = _font(62, True)
    value_font = _font(46, True)
    label_font = _font(24, True)
    small_font = _font(24, False)
    draw.text((95, 90), "IDSE MARKETPLACE", font=brand_font, fill=PURPLE)
    draw.text((95, 155), _fit(draw, title, title_font, 1000), font=title_font, fill=WHITE)
    name = _fit(draw, product_name, _font(50, True), 1000)
    draw.text((95, 255), name, font=_font(50, True), fill=WHITE)
    draw.text((95, 350), "HARGA", font=label_font, fill=MUTED)
    draw.text((95, 390), str(price), font=value_font, fill=WHITE)
    if stock is not None:
        draw.text((650, 350), "STOCK", font=label_font, fill=MUTED)
        draw.text((650, 390), f"{int(stock):,}", font=value_font, fill=WHITE)
    if description:
        for index, line in enumerate(_wrap_lines(draw, description, small_font, 1000, 3)):
            draw.text((95, 500 + index * 32), _fit(draw, line, small_font, 1000), font=small_font, fill=MUTED)
    out = BytesIO()
    image.save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()


def _wrap_lines(draw, value, font, width, limit=3):
    words = str(value or "").split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = _fit(draw, lines[-1] + "…", font, width)
    return lines


def render_product_collection(products, title="PILIHAN PRODUK"):
    """One readable poster for one to ten selected products."""
    if not 1 <= len(products) <= 10:
        raise ValueError("Jumlah produk harus 1 sampai 10.")
    width, card_height = 1200, 260
    height = 235 + card_height * len(products)
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.text((70, 45), "IDSE MARKETPLACE", font=_font(27, True), fill=PURPLE)
    draw.text((70, 95), _fit(draw, title, _font(52, True), 1050), font=_font(52, True), fill=WHITE)
    draw.text((70, 160), f"{len(products)} pilihan produk · Pilih varian sesuai kebutuhan", font=_font(22), fill=MUTED)
    for index, product in enumerate(products):
        top = 215 + index * card_height
        draw.rounded_rectangle((60, top, 1140, top + 235), 24, fill=PANEL, outline=(42, 83, 66), width=2)
        draw.text((85, top + 20), _fit(draw, product.get("catalog") or "PRODUK DIGITAL", _font(21, True), 760), font=_font(21, True), fill=PURPLE)
        draw.text((85, top + 55), _fit(draw, product.get("name") or "Produk", _font(34, True), 1010), font=_font(34, True), fill=WHITE)
        draw.text((85, top + 102), _fit(draw, product.get("price") or "", _font(31, True), 740), font=_font(31, True), fill=GREEN)
        stock = product.get("stock")
        label = "Tersedia" if stock is None else f"Stok {int(stock)}"
        draw.text((890, top + 109), _fit(draw, label, _font(22), 210), font=_font(22), fill=MUTED)
        for line_number, line in enumerate(_wrap_lines(draw, product.get("summary") or "", _font(24), 990, 2)):
            draw.text((85, top + 155 + line_number * 30), _fit(draw, line, _font(24), 990), font=_font(24), fill=MUTED)

    out = BytesIO()
    image.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def render_sales_report(kind, summary):
    """Generate a readable Telegram poster from the same numbers as the message."""
    from broadcast_reports import amounts

    daily = kind == "daily_recap"
    width = 1200
    rows = summary.get("products", [])[:5]
    height = 760 if daily else 325 + 160 * max(1, len(rows))
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((45, 45, width - 45, height - 45), 30, fill=PANEL, outline=(42, 83, 66), width=2)
    draw.rounded_rectangle((75, 75, 89, 148), 7, fill=PURPLE)
    draw.text((110, 78), "IDSE MARKETPLACE", font=_font(26, True), fill=PURPLE)
    title = "REKAP PENJUALAN HARIAN" if daily else "PRODUK TERLARIS"
    draw.text((80, 155), title, font=_font(51, True), fill=WHITE)
    draw.text((82, 220), str(summary.get("label") or ""), font=_font(28), fill=MUTED)

    if daily:
        cards = [
            ("TOTAL PENJUALAN", amounts(summary.get("totals") or {})),
            ("PRODUK TERJUAL", f"{int(summary.get('units') or 0):,} unit"),
            ("PRODUK TERLARIS", (rows[0]["name"] if rows else "Belum ada penjualan")),
        ]
        for index, (label, value) in enumerate(cards):
            top = 285 + index * 130
            draw.rounded_rectangle((80, top, 1120, top + 112), 19, fill=BG, outline=(59, 42, 80), width=2)
            draw.text((110, top + 15), label, font=_font(22, True), fill=MUTED)
            draw.text((110, top + 49), _fit(draw, value, _font(40, True), 960), font=_font(40, True), fill=GREEN if index == 0 else WHITE)
        draw.text((84, 677), "Berdasarkan pesanan selesai  |  WIB", font=_font(19), fill=MUTED)
    else:
        if not rows:
            draw.rounded_rectangle((80, 285, 1120, 445), 22, fill=BG)
            draw.text((115, 342), "Belum ada penjualan pada periode ini", font=_font(30, True), fill=MUTED)
        for index, row in enumerate(rows):
            top = 285 + index * 160
            draw.rounded_rectangle((80, top, 1120, top + 139), 20, fill=BG, outline=(59, 42, 80), width=2)
            draw.text((108, top + 21), f"{index + 1:02d}", font=_font(40, True), fill=PURPLE)
            draw.text((185, top + 17), _fit(draw, row["name"], _font(34, True), 890), font=_font(34, True), fill=WHITE)
            draw.text((185, top + 76), f"{int(row['qty']):,} unit terjual", font=_font(24, True), fill=MUTED)
            revenue = _fit(draw, amounts(row.get("sales") or {}), _font(27, True), 540)
            draw.text((630, top + 75), revenue, font=_font(27, True), fill=GREEN)
    out = BytesIO()
    image.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def render_message_poster(message, title="PENGUMUMAN"):
    """Automatically attach a simple image to text-only broadcasts."""
    width, height = 1200, 630
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((45, 45, 1155, 585), 30, fill=PANEL, outline=(42, 83, 66), width=2)
    draw.rounded_rectangle((80, 80, 95, 147), 7, fill=PURPLE)
    draw.text((120, 89), "IDSE MARKETPLACE", font=_font(28, True), fill=PURPLE)
    draw.text((80, 175), _fit(draw, title, _font(60, True), 1040), font=_font(60, True), fill=WHITE)
    for index, line in enumerate(_wrap_lines(draw, message, _font(31), 990, 5)):
        draw.text((85, 285 + index * 48), _fit(draw, line, _font(31), 990), font=_font(31), fill=MUTED)
    out = BytesIO()
    image.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def render_announcement_image(title, highlights, label="UPDATE SISTEM"):
    """Create a branded poster for a centralized broadcast template."""
    width, height = 1200, 700
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((45, 45, 1155, 655), 30, fill=PANEL, outline=(42, 83, 66), width=2)
    draw.rounded_rectangle((78, 75, 94, 145), 7, fill=PURPLE)
    draw.text((120, 78), "IDSE MARKETPLACE", font=_font(28, True), fill=PURPLE)
    draw.text((80, 157), _fit(draw, label.upper(), _font(30, True), 1040), font=_font(30, True), fill=GREEN)
    title_font = _font(57, True)
    for index, line in enumerate(_wrap_lines(draw, title, title_font, 1030, 2)):
        draw.text((80, 210 + index * 69), _fit(draw, line, title_font, 1030), font=title_font, fill=WHITE)
    top = 390
    for value in [str(item).strip() for item in highlights if str(item).strip()][:3]:
        draw.rounded_rectangle((80, top, 1120, top + 66), 15, fill=BG)
        draw.ellipse((104, top + 27, 116, top + 39), fill=PURPLE)
        draw.text((138, top + 15), _fit(draw, value, _font(29, True), 940), font=_font(29, True), fill=WHITE)
        top += 78
    out = BytesIO()
    image.save(out, format="JPEG", quality=89, optimize=True)
    return out.getvalue()
