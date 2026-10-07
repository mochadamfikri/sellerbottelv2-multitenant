"""Deterministic product artwork: local brand mark, plan and duration."""
import hashlib
import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw
from broadcast_image import _font, _fit, _wrap_lines
from product_catalog import catalog_name

ASSETS = Path(__file__).parent / "assets" / "brands"


async def image_response(product, catalog=False):
    from fastapi import Response
    from storage import get_object
    if product.get("image_path"):
        try:
            data, detected_type = await get_object(product["image_path"])
            return Response(data, media_type=product.get("image_content_type") or detected_type,
                            headers={"Cache-Control": "private, max-age=300"})
        except FileNotFoundError:
            pass
    data = render_product_artwork(str(product.get("name") or "Produk"), catalog_name(product), catalog)
    return Response(data, media_type="image/webp", headers={"Cache-Control": "private, max-age=300"})
BRANDS = (
    (r"\bclaude\b", "claude", "Claude", "#D97757", "#F8F2EA"),
    (r"\bchat\s*gpt\b|\bopenai\b", "openai", "ChatGPT", "#13745E", "#EDF7F1"),
    (r"\baws\b", "amazonwebservices", "AWS", "#E58B19", "#FFF7E9"),
    (r"\btelegram\b", "telegram", "Telegram", "#229ED9", "#EBF6FD"),
    (r"\bgmail\b", "gmail", "Gmail", "#D44638", "#FFF2EE"),
    (r"\bnetflix\b", "netflix", "Netflix", "#E50914", "#FFF0F1"),
    (r"\b(?:youtube|yt)\b", "youtube", "YouTube", "#E62117", "#FFF3F1"),
)


def artwork_labels(name, catalog="", catalog_only=False):
    text = str(name or "Produk Digital")
    brand = next((row[1:] for row in BRANDS if re.search(row[0], text, re.I)), None)
    if brand is None:
        brand = next((row[1:] for row in BRANDS if re.search(row[0], catalog, re.I)), (None, catalog or "Digital", "#13745E", "#EDF7F1"))
    # "Bukan Trial" must not be rendered as TRIAL.
    plan_text = re.sub(r"\b(?:bukan|non|not|tanpa)[\s-]+trial\b", "", text, flags=re.I)
    plan = next((label for pattern, label in ((r"\btrial\b", "TRIAL"), (r"\bpro\b", "PRO"), (r"\bplus\b", "PLUS"), (r"\bpremium\b", "PREMIUM"), (r"\bmax\b", "MAX")) if re.search(pattern, plan_text, re.I)), "DIGITAL")
    duration = re.search(r"\b(\d+)\s*(bulan|months?|bln|tahun|years?|hari|days?|minggu|weeks?)\b", text, re.I)
    duration_label = ""
    if duration:
        unit = duration[2].lower()
        unit = "BULAN" if unit in {"bulan", "month", "months", "bln"} else "TAHUN" if unit in {"tahun", "year", "years"} else "HARI" if unit in {"hari", "day", "days"} else "MINGGU"
        duration_label = f"{duration[1]} {unit}"
    return {"icon": brand[0], "brand": brand[1], "accent": brand[2], "background": brand[3],
            "plan": "KATALOG" if catalog_only else plan, "duration": "PILIH VARIAN" if catalog_only else duration_label,
            "name": catalog if catalog_only else text}


def artwork_urls(product, admin=False):
    name = str(product.get("name") or "")
    catalog = catalog_name(product)
    version = hashlib.sha256(f"artwork-v2:{name}:{catalog}:{product.get('updated_at', '')}:{product.get('image_path', '')}".encode()).hexdigest()[:16]
    root = f"/api/{'admin' if admin else 'store'}/products/{product['_id']}/image"
    return {"image_url": f"{root}?v={version}", "catalog_image_url": f"{root}?catalog=true&v={version}",
            "image_source": "uploaded" if product.get("image_path") else "generated"}


@lru_cache(maxsize=128)
def render_product_artwork(name, catalog="", catalog_only=False):
    labels = artwork_labels(name, catalog, catalog_only)
    image = Image.new("RGB", (1200, 1200), labels["background"])
    draw = ImageDraw.Draw(image)
    accent = labels["accent"]
    draw.rounded_rectangle((38, 38, 1162, 1162), 56, outline=accent, width=3)
    draw.text((92, 88), "IDSE MARKETPLACE", font=_font(27, True), fill="#64756D")
    plan = labels["plan"]
    plan_font = _font(42, True)
    badge_width = max(210, draw.textbbox((0, 0), plan, font=plan_font)[2] + 90)
    draw.rounded_rectangle(((1200-badge_width)/2, 185, (1200+badge_width)/2, 273), 28, fill=accent)
    draw.text(((1200-draw.textbbox((0, 0), plan, font=plan_font)[2])/2, 203), plan, font=plan_font, fill="white")
    icon_path = ASSETS / f"{labels['icon']}.png"
    if labels["icon"] and icon_path.exists():
        icon = Image.open(icon_path).convert("RGBA").resize((310, 310), Image.Resampling.LANCZOS)
        colored = Image.new("RGBA", icon.size, accent); colored.putalpha(icon.getchannel("A"))
        image.paste(colored, (445, 345), colored)
    else:
        initials = "".join(word[0] for word in labels["brand"].split()[:2]).upper()
        draw.rounded_rectangle((445, 345, 755, 655), 60, fill=accent)
        font = _font(110, True); width = draw.textbbox((0, 0), initials, font=font)[2]
        draw.text(((1200-width)/2, 425), initials, font=font, fill="white")
    font = _font(68, True); text = _fit(draw, labels["brand"], font, 990)
    draw.text(((1200-draw.textbbox((0, 0), text, font=font)[2])/2, 700), text, font=font, fill="#182A22")
    if labels["duration"]:
        font = _font(48, True); text = labels["duration"]
        draw.text(((1200-draw.textbbox((0, 0), text, font=font)[2])/2, 808), text, font=font, fill=accent)
    font = _font(28)
    for index, line in enumerate(_wrap_lines(draw, labels["name"], font, 950, 2)):
        line = _fit(draw, line, font, 950)
        draw.text(((1200-draw.textbbox((0, 0), line, font=font)[2])/2, 965+index*43), line, font=font, fill="#64756D")
    output = BytesIO(); image.save(output, format="WEBP", quality=90)
    return output.getvalue()
