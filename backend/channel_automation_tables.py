"""Telegram Rich Message Table Composer for Channel Automation.

Renders pure native Telegram rich message HTML tables:
- sendRichMessage with InputRichMessage / InputRichBlockTable compatible HTML
- is_bordered: true, is_compact: true (via <table bordered striped compact>)
- Product name deep-linking (https://t.me/<BOT_USERNAME>?start=prod_<PRODUCT_ID>)
- Formats:
  A. Verified Transaction (TRANSAKSI BERHASIL)
  B. Scheduled Product Promotion (PRODUK TERSEDIA)
  C. Simulation / Testing (SIMULASI — BUKAN TRANSAKSI NYATA)
"""
from dataclasses import dataclass
from html import escape
import os
from typing import Dict, Any, List, Optional
from channel_automation_utils import mask_username, mask_user_id, format_idr


@dataclass(frozen=True)
class RenderedRichMessage:
    html: str
    fallback_text: str
    message_type: str


def make_product_url(bot_username: str, product_id: str) -> str:
    clean_bot = bot_username.lstrip("@").strip()
    return f"https://t.me/{clean_bot}?start=prod_{product_id}"


def render_verified_transaction_table(
    customer_name: str,
    customer_telegram_id: str,
    product_name: str,
    product_id: str,
    final_amount: int,
    bot_username: str = "Idse_MarketBot",
) -> RenderedRichMessage:
    """Template A: Real Verified Transaction.
    
    🥳 ㊗️🔊 TRANSAKSI BERHASIL 🔊㊗️
    
    Informasi | Detail
    👤 Name   | @Ra*******
    🆔 User   | 129*****38
    📦 Produk | <a href="...">Gemini Pro 18 Bulan</a>
    🔢 Nominal| Rp15.106
    
    Terima kasih sudah berbelanja 🙏
    """
    masked_name = mask_username(customer_name)
    masked_tid = mask_user_id(customer_telegram_id)
    formatted_amount = format_idr(final_amount)
    prod_url = make_product_url(bot_username, product_id)
    escaped_prod_name = escape(product_name)

    # HTML for sendRichMessage
    html = (
        "<p>🥳 ㊗️🔊 <b>TRANSAKSI BERHASIL</b> 🔊㊗️</p>"
        "<table bordered striped compact>"
        "<tr><th>Informasi</th><th>Detail</th></tr>"
        f"<tr><td>👤 Name</td><td>{escape(masked_name)}</td></tr>"
        f"<tr><td>🆔 User</td><td>{escape(masked_tid)}</td></tr>"
        f'<tr><td>📦 Produk</td><td><a href="{escape(prod_url)}">{escaped_prod_name}</a></td></tr>'
        f"<tr><td>🔢 Nominal</td><td><code>{escape(formatted_amount)}</code></td></tr>"
        "</table>"
        "<p>Terima kasih sudah berbelanja 🙏</p>"
    )

    fallback = (
        "🥳 ㊗️🔊 TRANSAKSI BERHASIL 🔊㊗️\n\n"
        f"Informasi: Detail\n"
        f"👤 Name: {masked_name}\n"
        f"🆔 User: {masked_tid}\n"
        f"📦 Produk: {product_name} ({prod_url})\n"
        f"🔢 Nominal: {formatted_amount}\n\n"
        "Terima kasih sudah berbelanja 🙏"
    )

    return RenderedRichMessage(html=html, fallback_text=fallback, message_type="verified_transaction")


def render_promo_product_table(
    product_name: str,
    product_id: str,
    price: int,
    bot_username: str = "Idse_MarketBot",
) -> RenderedRichMessage:
    """Template B: Scheduled Product Promotion.
    
    🎉 📦 PRODUK TERSEDIA 📦 🎉
    
    Informasi   | Detail
    📦 Produk   | <a href="...">Gemini Pro 18 Bulan</a>
    💰 Harga    | Rp15.000
    🛒 Pemesanan| Klik nama produk
    ✅ Status   | Stok tersedia
    """
    formatted_price = format_idr(price)
    prod_url = make_product_url(bot_username, product_id)
    escaped_prod_name = escape(product_name)

    html = (
        "<p>🎉 📦 <b>PRODUK TERSEDIA</b> 📦 🎉</p>"
        "<table bordered striped compact>"
        "<tr><th>Informasi</th><th>Detail</th></tr>"
        f'<tr><td>📦 Produk</td><td><a href="{escape(prod_url)}">{escaped_prod_name}</a></td></tr>'
        f"<tr><td>💰 Harga</td><td><code>{escape(formatted_price)}</code></td></tr>"
        f'<tr><td>🛒 Pemesanan</td><td><a href="{escape(prod_url)}">Klik nama produk</a></td></tr>'
        "<tr><td>✅ Status</td><td>Stok tersedia</td></tr>"
        "</table>"
    )

    fallback = (
        "🎉 📦 PRODUK TERSEDIA 📦 🎉\n\n"
        f"📦 Produk: {product_name} ({prod_url})\n"
        f"💰 Harga: {formatted_price}\n"
        f"🛒 Pemesanan: Klik nama produk ({prod_url})\n"
        f"✅ Status: Stok tersedia"
    )

    return RenderedRichMessage(html=html, fallback_text=fallback, message_type="scheduled_promo")


def render_simulation_table(
    product_name: str,
    product_id: str,
    price: int,
    bot_username: str = "Idse_MarketBot",
) -> RenderedRichMessage:
    """Template C: Simulation / Testing.
    
    🧪 SIMULASI — BUKAN TRANSAKSI NYATA
    """
    formatted_price = format_idr(price)
    prod_url = make_product_url(bot_username, product_id)
    escaped_prod_name = escape(product_name)

    html = (
        "<p>🧪 <b>SIMULASI — BUKAN TRANSAKSI NYATA</b></p>"
        "<table bordered striped compact>"
        "<tr><th>Informasi</th><th>Detail</th></tr>"
        f"<tr><td>👤 Name (Simulasi)</td><td>@Te*******</td></tr>"
        f"<tr><td>🆔 User (Simulasi)</td><td>999*****01</td></tr>"
        f'<tr><td>📦 Produk</td><td><a href="{escape(prod_url)}">{escaped_prod_name}</a></td></tr>'
        f"<tr><td>🔢 Nominal (Estimasi)</td><td><code>{escape(formatted_price)}</code></td></tr>"
        "</table>"
        "<p><i>Catatan: Ini adalah pengujian modul Channel Automation.</i></p>"
    )

    fallback = (
        "🧪 SIMULASI — BUKAN TRANSAKSI NYATA\n\n"
        f"👤 Name (Simulasi): @Te*******\n"
        f"🆔 User (Simulasi): 999*****01\n"
        f"📦 Produk: {product_name} ({prod_url})\n"
        f"🔢 Nominal (Estimasi): {formatted_price}\n\n"
        "Catatan: Ini adalah pengujian modul Channel Automation."
    )

    return RenderedRichMessage(html=html, fallback_text=fallback, message_type="simulation")
