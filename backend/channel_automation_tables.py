"""Telegram Rich Message Table Composer for Channel Automation.

Strict 4-field table format:
- sendRichMessage with native Telegram table
- is_bordered: true, is_compact: true (via <table bordered striped compact>)
- Product name deep-linking (https://t.me/<BOT_USERNAME>?start=prod_<PRODUCT_ID>)

Header resmi seragam:
🥳 ㊗️🔊TRANSAKSI BERHASIL🔊㊗️

Informasi| Detail
👤 name| @Ra*******
🆔 user| 129*****38
📦 Produk| Gemini Pro 18 Bulan
🔢 Nominal| Rp15.106

Terima kasih sudah berbelanja 🙏
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


def render_transaction_table(
    name: str,
    user_id: str,
    product_name: str,
    product_id: str,
    amount: int,
    bot_username: str = "Idse_MarketBot",
    message_type: str = "transaction",
) -> RenderedRichMessage:
    """Render exact official 4-field transaction table.
    
    🥳 ㊗️🔊TRANSAKSI BERHASIL🔊㊗️
    
    Informasi| Detail
    👤 name| @Ra*******
    🆔 user| 129*****38
    📦 Produk| Gemini Pro 18 Bulan
    🔢 Nominal| Rp15.106
    
    Terima kasih sudah berbelanja 🙏
    """
    masked_name = mask_username(name)
    masked_tid = mask_user_id(user_id)
    formatted_amount = format_idr(amount)
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

    return RenderedRichMessage(html=html, fallback_text=fallback, message_type=message_type)


def render_verified_transaction_table(
    customer_name: str,
    customer_telegram_id: str,
    product_name: str,
    product_id: str,
    final_amount: int,
    bot_username: str = "Idse_MarketBot",
) -> RenderedRichMessage:
    """Real verified customer transaction table."""
    return render_transaction_table(
        name=customer_name,
        user_id=customer_telegram_id,
        product_name=product_name,
        product_id=product_id,
        amount=final_amount,
        bot_username=bot_username,
        message_type="verified_transaction",
    )


def render_scheduled_transaction_table(
    product_name: str,
    product_id: str,
    price: int,
    bot_username: str = "Idse_MarketBot",
    dummy_name: Optional[str] = None,
    dummy_user_id: Optional[str] = None,
) -> RenderedRichMessage:
    """Scheduled Channel Automation transaction table.
    
    Uses identical header '🥳 ㊗️🔊TRANSAKSI BERHASIL🔊㊗️' and 4-field table.
    No simulation labels.
    """
    raw_name = dummy_name or generate_dummy_username()
    if dummy_user_id:
        raw_id = dummy_user_id
    else:
        raw_id, _ = generate_dummy_user_id()

    return render_transaction_table(
        name=raw_name,
        user_id=raw_id,
        product_name=product_name,
        product_id=product_id,
        amount=price,
        bot_username=bot_username,
        message_type="scheduled_transaction",
    )
