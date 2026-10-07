"""Auto-generated welcome banner for Telegram bots.

When a tenant enables ``welcome_media`` in ``auto`` mode, the system builds a
branded banner from the BotFather display name (detected via getMe) — no
designer needed.  Banners are cached per bot slug under the runtime dir and
regenerated only when the brand name changes.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1280, 720
CACHE_SUBDIR = "welcome_media"

_FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
_FONT_REG_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _font(candidates, size):
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _runtime_base() -> Path:
    here = Path(__file__).resolve()
    # backend/ -> repo/ -> sellerbottel-v2/ ; runtime/ sits next to repo/
    runtime = here.parent.parent.parent / "runtime"
    base = runtime / CACHE_SUBDIR
    base.mkdir(parents=True, exist_ok=True)
    return base


def _slug_dir(slug: str) -> Path:
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in slug) or "bot"
    d = _runtime_base() / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _brand_key(brand: str) -> str:
    return hashlib.sha256(brand.encode("utf-8")).hexdigest()[:12]


def auto_banner_path(slug: str, brand: str) -> Path:
    """Filesystem path of the cached auto banner for this brand."""
    return _slug_dir(slug) / f"banner-auto-{_brand_key(brand)}.png"


def _vertical_gradient(draw: ImageDraw.ImageDraw):
    top = (15, 12, 41)      # deep navy
    mid = (48, 43, 99)      # indigo
    bot = (24, 20, 46)      # dark purple
    for y in range(HEIGHT):
        if y < HEIGHT // 2:
            t = y / (HEIGHT // 2)
            r = int(top[0] + (mid[0] - top[0]) * t)
            g = int(top[1] + (mid[1] - top[1]) * t)
            b = int(top[2] + (mid[2] - top[2]) * t)
        else:
            t = (y - HEIGHT // 2) / (HEIGHT // 2)
            r = int(mid[0] + (bot[0] - mid[0]) * t)
            g = int(mid[1] + (bot[1] - mid[1]) * t)
            b = int(mid[2] + (bot[2] - mid[2]) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))


def _glow(img: Image.Image, cx: int, cy: int, radius: int, color, alpha: int):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i in range(radius, 0, -6):
        a = int(alpha * (1 - i / radius) ** 1.5)
        d.ellipse([cx - i, cy - i, cx + i, cy + i],
                  fill=color + (a,))
    img.alpha_composite(layer)


def _centered(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text(((WIDTH - w) / 2, y), text, font=font, fill=fill)
    return y + (bbox[3] - bbox[1])


def generate_banner(brand: str, tagline: str = "DIGITAL STORE") -> Image.Image:
    """Render a 1280x720 branded banner."""
    brand = (brand or "Bot Store").strip()
    img = Image.new("RGBA", (WIDTH, HEIGHT), (15, 12, 41, 255))
    draw = ImageDraw.Draw(img)
    _vertical_gradient(draw)

    # Ambient glows.
    _glow(img, 200, 140, 320, (88, 60, 220), 90)
    _glow(img, 1080, 600, 360, (0, 200, 220), 70)
    _glow(img, 640, 360, 200, (255, 180, 60), 40)
    draw = ImageDraw.Draw(img)

    # Subtle dot grid.
    for gx in range(60, WIDTH, 80):
        for gy in range(60, HEIGHT, 80):
            draw.ellipse([gx - 2, gy - 2, gx + 2, gy + 2],
                         fill=(255, 255, 255, 18))

    font_brand = _font(_FONT_BOLD_CANDIDATES, 110)
    font_tag = _font(_FONT_BOLD_CANDIDATES, 44)
    font_sub = _font(_FONT_REG_CANDIDATES, 30)

    # Fit long brand names.
    while True:
        bbox = draw.textbbox((0, 0), brand, font=font_brand)
        if bbox[2] - bbox[0] <= WIDTH - 160 or font_brand.size <= 48:
            break
        font_brand = _font(_FONT_BOLD_CANDIDATES, font_brand.size - 8)

    y = 200
    y = _centered(draw, y, "✦", _font(_FONT_BOLD_CANDIDATES, 54), (255, 200, 90, 255))
    y = _centered(draw, y + 18, brand, font_brand, (255, 255, 255, 255))

    # Accent divider.
    y += 30
    draw.rounded_rectangle([WIDTH / 2 - 130, y, WIDTH / 2 + 130, y + 6],
                           radius=3, fill=(0, 220, 230, 255))
    y = _centered(draw, y + 28, tagline, font_tag, (255, 210, 120, 255))
    _centered(draw, y + 22, "Selamat datang & selamat berbelanja",
              font_sub, (200, 200, 220, 255))

    return img.convert("RGB")


def ensure_auto_banner(slug: str, brand: str,
                       tagline: str = "DIGITAL STORE") -> str:
    """Return the cached banner path, generating it on first use/brand change."""
    path = auto_banner_path(slug, brand)
    if not path.is_file():
        # Drop stale banners for previous brand names.
        for old in _slug_dir(slug).glob("banner-auto-*.png"):
            try:
                old.unlink()
            except OSError:
                pass
        generate_banner(brand, tagline).save(str(path), "PNG")
    return str(path)


def normalize_welcome_media(bot_config: dict | None) -> dict:
    """Normalize the welcome_media config from a tenant's bot_config.

    Accepts the new dict form plus the legacy plain-string ``welcome_photo``.
    Always returns a dict with keys: enabled, mode, file, tagline.
    """
    cfg = bot_config or {}
    raw = cfg.get("welcome_media")
    if isinstance(raw, dict):
        media = dict(raw)
    elif isinstance(raw, str) and raw:
        media = {"enabled": True, "mode": "upload", "file": raw}
    else:
        legacy = cfg.get("welcome_photo")
        if isinstance(legacy, str) and legacy:
            media = {"enabled": True, "mode": "upload", "file": legacy}
        else:
            media = {}
    return {
        "enabled": bool(media.get("enabled", False)),
        "mode": media.get("mode") or "auto",
        "file": media.get("file") or "",
        "tagline": media.get("tagline") or "DIGITAL STORE",
    }


def upload_media_path(slug: str, filename: str) -> Path:
    """Destination path for an admin-uploaded welcome media file."""
    d = _slug_dir(slug)
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in filename)
    return d / f"upload-{safe}"
