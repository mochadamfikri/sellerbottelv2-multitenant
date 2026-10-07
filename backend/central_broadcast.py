"""Live templates for centralized system announcements."""
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo
import re

from fastapi import HTTPException

from broadcast_image import render_announcement_image, render_product_image
from checkout import stock_for
from db import db, get_settings
from pricing import _active_date, price_for_product
from promo_service import coupon_is_time_valid
from reseller_service import activation_fees
from services import fmt_amount

TOPICS = {"reseller_guide", "reseller_contest", "discount", "coupon",
          "product_update", "product_restock", "deposit_guide", "announcement"}


def date_wib(raw):
    if not raw:
        return "-"
    try:
        value = datetime.fromisoformat(str(raw))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%d %b %Y %H:%M WIB")
    except ValueError:
        return "-"


async def options():
    now = datetime.now(timezone.utc).isoformat()
    contests = await db.reseller_contests.find(
        {"status": "active", "ends_at": {"$gt": now}},
        {"_id": 1, "name": 1, "starts_at": 1, "ends_at": 1}).sort("ends_at", 1).to_list(100)
    discounts_raw = await db.discounts.find({"active": True},
                                             {"_id": 1, "name": 1, "starts_at": 1, "ends_at": 1}).to_list(100)
    discounts = [row for row in discounts_raw if _active_date(row)]
    coupons_raw = await db.promo_coupons.find({"active": True},
                                               {"_id": 1, "code": 1, "starts_at": 1, "ends_at": 1,
                                                "quota_total": 1, "used_count": 1}).to_list(100)
    coupons = [row for row in coupons_raw if coupon_is_time_valid(row)
               and (row.get("quota_total") is None or
                    int(row.get("used_count") or 0) < int(row["quota_total"]))]
    products = await db.products.find({"active": True}, {"_id": 1, "name": 1}).sort("name", 1).to_list(500)
    settings = await get_settings()
    return {"contests": contests, "discounts": discounts, "coupons": coupons,
            "products": products, "reseller_enabled": bool(settings.get("reseller_enabled")),
            "qris_enabled": bool(settings.get("qris_enabled")),
            "bank_enabled": bool(settings.get("bank_enabled"))}


async def _product_names(ids):
    if not ids:
        return "semua produk"
    products = await db.products.find({"_id": {"$in": ids}}, {"name": 1}).to_list(30)
    names = ", ".join(escape(str(row.get("name") or "Produk")) for row in products[:5])
    return names + (" dan produk lainnya" if len(products) > 5 else "") if names else "produk terpilih"


async def build_central_content(body):
    topic = body.topic
    if topic not in TOPICS:
        raise HTTPException(400, "Pilih jenis update yang tersedia.")
    extra = body.message.strip()
    if len(extra) > 700:
        raise HTTPException(400, "Catatan tambahan maksimal 700 karakter.")
    ref = body.reference_id
    settings = await get_settings()
    image = None
    highlights = []

    if topic == "reseller_guide":
        if not settings.get("reseller_enabled"):
            raise HTTPException(400, "Pendaftaran reseller sedang ditutup. Buka dulu di menu Bot Reseller.")
        fees = activation_fees(settings)
        if fees["total"] <= 0:
            raise HTTPException(400, "Biaya langganan reseller belum diatur.")
        reduction = int(settings.get("reseller_wholesale_reduction_idr") or 2000)
        title = "BUAT BOT RESELLER SENDIRI"
        text = ("🤖 <b>Bikin Bot Reseller Sendiri</b>\n\n"
                "<blockquote>Jual produk SellerBottel melalui bot Telegram milikmu. "
                "Katalog dan stok mengikuti bot pusat secara otomatis.</blockquote>\n\n"
                "<b>1. Dapatkan token bot</b>\n"
                "Buka @BotFather di Telegram → ketik <code>/newbot</code> → isi nama bot → "
                "isi username unik yang berakhiran <code>bot</code>. Salin token yang diberikan BotFather. "
                "Simpan seperti kata sandi; jangan kirim ke orang lain.\n\n"
                "<b>2. Dapatkan Telegram User ID</b>\n"
                "Buka @Idse_MarketBot → ketik <code>/id</code> → salin angka ID yang muncul. "
                "ID ini dipakai untuk admin bot reseller; boleh ID milikmu sendiri.\n\n"
                "<b>3. Daftarkan dan bayar</b>\n"
                "Di @Idse_MarketBot, pilih <b>Bikin Bot Sendiri</b> → <b>Daftarkan Bot</b>. "
                "Kirim token, lalu User ID admin. Bot pusat menampilkan biaya dan QRIS. "
                "Kamu juga bisa bayar dari saldo IDR. Setelah pembayaran terverifikasi, bot aktif otomatis.\n\n"
                f"💳 Langganan satu bulan: <b>{fmt_amount(fees['total'], 'IDR')}</b> "
                f"(bot {fmt_amount(fees['bot_price'], 'IDR')} + admin fee {fmt_amount(fees['admin_fee'], 'IDR')} "
                f"+ platform {fmt_amount(fees['platform_fee'], 'IDR')}).\n\n"
                "<b>4. Atur harga dan komisi</b>\n"
                "Di bot barumu, admin ketik <code>/settharga</code>. Bot mengirim template .txt; "
                "edit harga jual lalu kirim balik, atau balas angka markup untuk semua produk. "
                f"Modal awal adalah harga pusat dikurangi {fmt_amount(reduction, 'IDR')}; "
                "komisi per unit = harga jual dikurangi modal. Produk baru mengikuti markup default.\n\n"
                "<b>5. Pencairan komisi</b>\n"
                "Atur tujuan lewat <code>/rekening BANK|BCA|12345678|Nama</code> atau e-wallet, "
                "dan ambang lewat <code>/setkomisi 50000</code>. Minimal Rp50.000; "
                "bank transfer dianjurkan. E-wallet dipotong Rp2.500. "
                "Admin pusat mentransfer komisi secara manual.\n\n"
                "⚠️ Bot tanpa penjualan berbayar selama 14 hari dinonaktifkan. "
                "Biaya langganan yang telah dibayar tidak dikembalikan.\n"
                "📢 Pengguna bot reseller wajib join channel SellerBottel.")
        highlights = [f"Langganan {fmt_amount(fees['total'], 'IDR')} / bulan",
                      "Token: @BotFather /newbot", "User ID: @Idse_MarketBot /id"]
    elif topic == "reseller_contest":
        contest = await db.reseller_contests.find_one({"_id": ref, "status": "active"})
        if not contest or contest.get("ends_at", "") <= datetime.now(timezone.utc).isoformat():
            raise HTTPException(400, "Kontes tidak aktif atau sudah selesai.")
        title = contest["name"]
        text = (f"🏆 <b>Kontes Owner Bot Reseller: {escape(title)}</b>\n\n"
                "<blockquote>Owner dengan omzet penjualan berbayar tertinggi selama periode kontes "
                "memenangkan hadiah jika mencapai target minimal.</blockquote>\n\n"
                f"🎁 Hadiah: <b>{fmt_amount(contest['prize_idr'], 'IDR')}</b>\n"
                f"🎯 Target minimal omzet: <b>{fmt_amount(contest['target_sales_idr'], 'IDR')}</b>\n"
                f"🗓️ Mulai: {date_wib(contest['starts_at'])}\n"
                f"🏁 Selesai: {date_wib(contest['ends_at'])}\n\n"
                "Penjualan dari beberapa bot milik owner yang sama digabung. "
                "Transaksi gagal atau refund tidak dihitung. "
                "Buat bot melalui menu <b>Bikin Bot Sendiri</b> di @Idse_MarketBot untuk ikut.")
        highlights = [f"Hadiah {fmt_amount(contest['prize_idr'], 'IDR')}",
                      f"Target omzet {fmt_amount(contest['target_sales_idr'], 'IDR')}",
                      f"Berakhir {date_wib(contest['ends_at'])}"]
    elif topic == "discount":
        discount = await db.discounts.find_one({"_id": ref, "active": True})
        if not discount or not _active_date(discount):
            raise HTTPException(400, "Diskon tidak aktif atau tidak ditemukan.")
        title = discount.get("name") or "Diskon Produk"
        if discount.get("mode") == "percent":
            value = f"{float(discount['value']):g}%"
        else:
            value = f"{fmt_amount(discount['value'], discount.get('fixed_currency') or 'IDR')} per unit"
        scope = await _product_names(discount.get("product_ids") or [])
        text = (f"🎉 <b>{escape(title)}</b>\n\n"
                f"<blockquote>Potongan {escape(value)} untuk {scope}.</blockquote>\n\n"
                f"🛍️ Produk: {scope}\n"
                + (f"📦 Berlaku mulai pembelian {int(discount.get('min_qty') or 1)} unit"
                   + (f" sampai {int(discount['max_qty'])} unit" if discount.get("max_qty") else "")
                   + ".\n" if discount.get("mode") == "fixed" else "")
                + (f"🗓️ Mulai: {date_wib(discount['starts_at'])}\n" if discount.get("starts_at") else "")
                + (f"⏰ Selesai: {date_wib(discount['ends_at'])}\n" if discount.get("ends_at") else "")
                + "\nBuka @Idse_MarketBot → pilih produk → lihat harga yang berlaku saat checkout.")
        highlights = [f"Potongan {value}", f"Produk: {scope}", "Belanja di @Idse_MarketBot"]
    elif topic == "coupon":
        coupon = await db.promo_coupons.find_one({"_id": ref, "active": True})
        if not coupon or not coupon_is_time_valid(coupon):
            raise HTTPException(400, "Kupon tidak aktif atau kedaluwarsa.")
        if coupon.get("quota_total") is not None and int(coupon.get("used_count") or 0) >= int(coupon["quota_total"]):
            raise HTTPException(400, "Kuota kupon sudah habis.")
        title = f"KUPON {coupon['code']}"
        value = f"{float(coupon['value']):g}%" if coupon["type"] == "percent" else fmt_amount(coupon["value"], coupon.get("currency") or "IDR")
        scope = await _product_names(coupon.get("product_ids") or [])
        text = (f"🎟️ <b>Kupon Belanja {escape(coupon['code'])}</b>\n\n"
                f"<blockquote>Hemat {escape(value)} untuk {scope}.</blockquote>\n\n"
                f"💳 Minimal belanja: {fmt_amount(coupon.get('min_purchase') or 0, coupon.get('currency') or 'IDR')}\n"
                f"👤 Batas per pengguna: {int(coupon.get('per_user_limit') or 1)} kali\n"
                + (f"🎫 Sisa kuota: {int(coupon['quota_total']) - int(coupon.get('used_count') or 0)}\n" if coupon.get("quota_total") is not None else "")
                + (f"⏰ Selesai: {date_wib(coupon['ends_at'])}\n" if coupon.get("ends_at") else "")
                + f"\nCara pakai: buka @Idse_MarketBot, ketik <code>/coupon {escape(coupon['code'])}</code>, "
                  "pilih produk, lalu checkout. Kupon berlaku sesuai syarat di atas.")
        highlights = [f"Kode {coupon['code']}", f"Hemat {value}", f"Untuk {scope}"]
    elif topic in {"product_update", "product_restock"}:
        product = await db.products.find_one({"_id": ref, "active": True})
        if not product:
            raise HTTPException(400, "Produk tidak aktif atau tidak ditemukan.")
        stock = await stock_for(product)
        if stock is not None and stock <= 0:
            raise HTTPException(400, "Stok produk habis.")
        title = product.get("name") or "Produk"
        pricing = await price_for_product(product, "IDR")
        price = fmt_amount(pricing["unit_price"], "IDR")
        description = str(product.get("description") or "").strip()
        description = re.sub(r"<[^>]*>", " ", description)
        description = " ".join(description.split())[:550]
        heading = "📦 <b>Produk Tersedia</b>" if topic == "product_update" else "🔄 <b>Produk Sudah Restock</b>"
        text = (f"{heading}\n\n✨ <b>{escape(title)}</b>\n"
                f"💰 Harga: <b>{price}</b>\n"
                f"📊 Stok: {'tersedia' if stock is None else int(stock)}\n"
                + (f"🎉 Diskon aktif: hemat {fmt_amount(pricing['discount_per_unit'], 'IDR')} per unit\n"
                   if pricing["discount_per_unit"] > 0 else "")
                + (f"\n<blockquote>{escape(description)}</blockquote>\n" if description else "")
                + "\n🛒 Beli melalui @Idse_MarketBot → Produk.")
        image = render_product_image(title, price, stock, description,
                                     title="RESTOCK PRODUK" if topic == "product_restock" else "INFO PRODUK")
        highlights = []
    elif topic == "deposit_guide":
        title = "CARA DEPOSIT & BELANJA"
        methods = []
        if settings.get("qris_enabled"):
            methods.append("QRIS otomatis")
        if settings.get("bank_enabled") and settings.get("bank_account_number"):
            methods.append("transfer bank")
        if not methods:
            raise HTTPException(400, "Metode deposit IDR belum aktif.")
        text = ("💳 <b>Cara Deposit dan Belanja</b>\n\n"
                f"<blockquote>Isi saldo IDR melalui {' atau '.join(methods)}, lalu beli produk langsung di bot pusat.</blockquote>\n\n"
                "1️⃣ Buka @Idse_MarketBot → pilih <b>Deposit</b>.\n"
                "2️⃣ Pilih metode yang tersedia dan ikuti nominal/instruksi yang ditampilkan bot.\n"
                "3️⃣ Setelah saldo masuk, pilih <b>Produk</b> → masukkan ke keranjang → checkout.\n\n"
                "Saldo di bot pusat juga dapat dipakai untuk belanja di bot reseller yang terhubung. "
                "Harga dan stok mengikuti sistem pusat.")
        highlights = ["Deposit lewat " + " / ".join(methods), "Pilih produk dan checkout", "Saldo terpusat di SellerBottel"]
    else:
        title = body.title.strip()
        if not title or not extra:
            raise HTTPException(400, "Isi judul dan pesan pengumuman.")
        if len(title) > 80:
            raise HTTPException(400, "Judul maksimal 80 karakter.")
        text = f"📢 <b>{escape(title)}</b>\n\n<blockquote>{escape(extra)}</blockquote>\n\n🔎 Info resmi: @Idse_MarketBot"
        extra = ""
        highlights = [title, "Update resmi SellerBottel", "Buka @Idse_MarketBot"]

    if extra:
        text += f"\n\n📝 <b>Catatan:</b> {escape(extra)}"
    if len(text) > 4000:
        raise HTTPException(400, "Pesan terlalu panjang untuk Telegram. Ringkas catatan tambahan.")
    if image is None:
        image = render_announcement_image(title, highlights, label=topic.replace("_", " "))
    return text, image
