"""Catalog labels for existing products and explicit admin assignments."""
import re
import hashlib


def catalog_name(product):
    explicit = " ".join(str(product.get("catalog_name") or "").split())
    if explicit:
        return explicit
    name = str(product.get("name") or "")
    if product.get("product_kind") == "service":
        return "Jasa Payment"
    for pattern, label in (
        (r"\bclaude\b", "Claude Pro"),
        (r"\bchat\s*gpt\b", "ChatGPT"),
        (r"\baws\b", "AWS"),
        (r"\btelegram\b", "Telegram"),
        (r"\bgmail\b", "Gmail"),
        (r"\bemail\b", "Email"),
        (r"\bnetflix\b", "Netflix"),
        (r"\b(?:youtube|yt)\b", "YouTube Premium"),
    ):
        if re.search(pattern, name, re.I):
            return label
    return "Produk Lainnya"


def catalog_token(product):
    """Stable short callback ID, independent of product order and label length."""
    return hashlib.sha256(catalog_name(product).casefold().encode()).hexdigest()[:16]


def catalog_groups(products):
    groups = {}
    for product in products:
        token = catalog_token(product)
        group = groups.setdefault(token, {"token": token, "name": catalog_name(product), "products": []})
        group["products"].append(product)
    for group in groups.values():
        group["products"].sort(key=lambda p: [int(v) if v.isdigit() else v.casefold() for v in re.split(r"(\d+)", p.get("name", ""))])
    return sorted(groups.values(), key=lambda group: group["name"].casefold())


def catalog_slice(products, token=None, page=1, size=8):
    groups = catalog_groups(products)
    group = next((g for g in groups if g["token"] == token), None) if token else None
    entries = group["products"] if group else ([] if token else groups)
    pages = max(1, (len(entries) + size - 1) // size)
    page = max(1, min(int(page), pages))
    return group, entries[(page - 1) * size:page * size], page, pages
