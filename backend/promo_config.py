"""Promo landing page configuration (idseconnect.my.id).

Everything on the landing page is data-driven: the panel at
panel.idseconnect.my.id edits this config, the public landing page
renders from it. No code changes needed to reword, reorder, relink,
recolor, or hide any section.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(tags=["promo-config"])

BUTTON_STYLES = ("primary", "secondary", "outline")
ACCENTS = ("emerald", "blue", "amber", "rose", "violet", "cyan")


def _default_config() -> dict[str, Any]:
    return {
        "site_name": "IDSEConnect",
        "promo_domain": "",
        "whatsapp_number": "6285835158504",
        "accent": "emerald",
        "hero": {
            "badge": "PLATFORM TOKO DIGITAL OTOMATIS",
            "title": "Jualan Produk Digital di Telegram.",
            "title_accent": "Jalan Sendiri 24/7.",
            "subtitle": (
                "Katalog rapi, pembayaran QRIS terverifikasi otomatis, dan produk "
                "terkirim dalam hitungan detik. Semua operasional tokomu dalam satu dashboard."
            ),
            "visible": True,
        },
        "buttons": [
            {"id": "daftar", "label": "Mulai Buat Toko Gratis", "url": "/daftar", "style": "primary", "visible": True},
            {"id": "wa_chat", "label": "Chat Admin WA", "url": "https://wa.me/6285835158504", "style": "secondary", "visible": True},
            {"id": "wa_group", "label": "Gabung Grup WA", "url": "", "style": "outline", "visible": True},
            {"id": "tg_channel", "label": "Join Channel Telegram", "url": "", "style": "outline", "visible": False},
            {"id": "tg_group", "label": "Join Grup Telegram", "url": "", "style": "outline", "visible": False},
            {"id": "wa_channel", "label": "Join Channel WhatsApp", "url": "", "style": "outline", "visible": False},
        ],
        "highlights": ["Bot atas nama brandmu", "QRIS otomatis", "Kirim produk instan"],
        "sections": {
            "simulation": True,
            "features": True,
            "steps": True,
            "faq": True,
            "final_cta": True,
        },
        "features_title": "Semua Kebutuhan Tokomu, Dalam Satu Dashboard",
        "steps_title": "Dari Daftar Sampai Pesanan Pertama",
        "faq_title": "Sering Ditanyakan",
        "final_cta": {
            "badge": "SIAP MEMULAI?",
            "title": "Biarkan Bot Melayani Pelangganmu, Kapan Pun.",
            "subtitle": (
                "Berhenti balas chat satu per satu. Daftarkan tokomu sekarang "
                "dan rasakan jualan yang jalan sendiri."
            ),
            "button_label": "Buat Toko Gratis Sekarang",
        },
    }


def _platform_config_collection():
    from db import db
    from tenant_db import resolve_platform_database_name
    import os

    return db.client[resolve_platform_database_name(os.environ)]["platform_config"]


async def get_promo_config() -> dict[str, Any]:
    coll = _platform_config_collection()
    doc = await coll.find_one({"_id": "promo_config"})
    if not doc:
        return _default_config()
    config = _default_config()
    stored = {k: v for k, v in doc.items() if k != "_id"}
    # Shallow merge: stored keys win; nested dicts merge one level.
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    return config


class PromoConfigBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    site_name: str | None = None
    whatsapp_number: str | None = None
    accent: str | None = None
    hero: dict[str, Any] | None = None
    buttons: list[dict[str, Any]] | None = None
    highlights: list[str] | None = None
    sections: dict[str, bool] | None = None
    features_title: str | None = None
    steps_title: str | None = None
    faq_title: str | None = None
    final_cta: dict[str, Any] | None = None


def _sanitize_buttons(buttons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean = []
    for b in buttons:
        style = str(b.get("style") or "outline")
        if style not in BUTTON_STYLES:
            style = "outline"
        clean.append(
            {
                "id": str(b.get("id") or "")[:40],
                "label": str(b.get("label") or "")[:80],
                "url": str(b.get("url") or "")[:500],
                "style": style,
                "visible": bool(b.get("visible", True)),
            }
        )
    return [b for b in clean if b["id"]]


@router.get("/api/public/promo-config")
async def public_promo_config() -> dict[str, Any]:
    return await get_promo_config()
