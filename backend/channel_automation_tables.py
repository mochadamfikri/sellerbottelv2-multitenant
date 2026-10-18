"""Telegram Rich Message Table Composer for Channel Automation.

Strict 4-field table format:
- sendRichMessage with InputRichMessage / InputRichBlockTable compatible HTML
- is_bordered: true, is_compact: true (via <table bordered striped compact>)
- Product name deep-linking (https://t.me/<BOT_USERNAME>?start=prod_<PRODUCT_ID>)
- Formats:
  1. Real Verified Transaction (TRANSAKSI BERHASIL)
  2. Scheduled Simulation (SIMULASI — BUKAN TRANSAKSI NYATA)
"""
from dataclasses import dataclass
from html import escape
import os
from typing import Dict, Any, List, Optional
from channel_automation_utils import (
    mask_username,
    mask_user_id,
    format_idr,
    generate_dummy_username,
    generate_dummy_user_id,
)


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
    """Format 1: Real Verified Transaction.
    
    🥳 ㊗️🔊TRANSAKSI BERHASIL🔊㊗️
    
    Informasi| Detail
    👤 name| @Ra*******
    🆔 user| 129*****38
    📦 Produk| Gemini Pro 18 Bulan
    🔢 Nominal| Rp15.106
    
    Terima kasih sudah berbelanja 🙏
    """
    masked_name = mask_username(customer_name)
    masked_tid = mask_user_id(customer_telegram_id)
    formatted_amount = format_idr(final_amount)
    prod_url = make_product_url(bot_username, product_id)
    escaped_prod_name = escape(product_name)

    html = (
        "<p>🥳 ㊗️🔊<b>TRANSAKSI BERHASIL</b>🔊㊗️</p>"
        "<table bordered striped compact>"
        "<tr><th>Informasi</th><th>Detail</th></tr>"
        f"<tr><td>👤 name</td><td>{escape(masked_name)}</td></tr>"
        f"<tr><td>🆔 user</td><td>{escape(masked_tid)}</td></tr>"
        f'<tr><td>📦 Produk</td><td><a href="{escape(prod_url)}">{escaped_prod_name}</a></td></tr>'
        f"<tr><td>🔢 Nominal</td><td><code>{escape(formatted_amount)}</code></td></tr>"
        "</table>"
        "<p>Terima kasih sudah berbelanja 🙏</p>"
    )

    fallback = (
        "🥳 ㊗️🔊TRANSAKSI BERHASIL🔊㊗️\n\n"
        f"Informasi: Detail\n"
        f"👤 name: {masked_name}\n"
        f"🆔 user: {masked_tid}\n"
        f"📦 Produk: {product_name} ({prod_url})\n"
        f"🔢 Nominal: {formatted_amount}\n\n"
        "Terima kasih sudah berbelanja 🙏"
    )

    return RenderedRichMessage(html=html, fallback_text=fallback, message_type="verified_transaction")


def render_simulation_table(
    product_name: str,
    product_id: str,
    price: int,
    bot_username: str = "Idse_MarketBot",
    dummy_name: Optional[str] = None,
    dummy_user_id: Optional[str] = None,
) -> RenderedRichMessage:
    """Format 2: Scheduled Simulation.
    
    Tabel yang sama persis (4 field), dengan judul tegas:
    🧪 SIMULASI — BUKAN TRANSAKSI NYATA
    
    Informasi| Detail
    👤 name| @Ra*******
    🆔 user| 129*****38
    📦 Produk| Gemini Pro 18 Bulan
    🔢 Nominal| Rp15.106
    """
    name_to_display = dummy_name or generate_dummy_username()
    if dummy_user_id:
        id_to_display = mask_user_id(dummy_user_id)
    else:
        _, id_to_display = generate_dummy_user_id()

    formatted_amount = format_idr(price)
    prod_url = make_product_url(bot_username, product_id)
    escaped_prod_name = escape(product_name)

    html = (
        "<p>🧪 <b>SIMULASI — BUKAN TRANSAKSI NYATA</b></p>"
        "<table bordered striped compact>"
        "<tr><th>Informasi</th><th>Detail</th></tr>"
        f"<tr><td>👤 name</td><td>{escape(name_to_display)}</td></tr>"
        f"<tr><td>🆔 user</td><td>{escape(id_to_display)}</td></tr>"
        f'<tr><td>📦 Produk</td><td><a href="{escape(prod_url)}">{escaped_prod_name}</a></td></tr>'
        f"<tr><td>🔢 Nominal</td><td><code>{escape(formatted_amount)}</code></td></tr>"
        "</table>"
        "<p><i>Catatan: Ini adalah simulasi otomatis — bukan transaksi nyata.</i></p>"
    )

    fallback = (
        "🧪 SIMULASI — BUKAN TRANSAKSI NYATA\n\n"
        f"Informasi: Detail\n"
        f"👤 name: {name_to_display}\n"
        f"🆔 user: {id_to_display}\n"
        f"📦 Produk: {product_name} ({prod_url})\n"
        f"🔢 Nominal: {formatted_amount}\n\n"
        "Catatan: Ini adalah simulasi otomatis — bukan transaksi nyata."
    )

    return RenderedRichMessage(html=html, fallback_text=fallback, message_type="simulation")
