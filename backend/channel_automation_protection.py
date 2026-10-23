"""Channel Automation Protected Products Policy.

Strictly excludes protected products from:
- Automatic selection
- Inventory reservation
- Stock deduction
- Restoration through this module
- Automated promotion campaigns
- Status changes
- Price modifications
- Product metadata modification
- Simulations using real inventory
"""
import re
import unicodedata
from typing import Dict, Any, Optional

# Permanently protected product IDs identified from catalog
PROTECTED_PRODUCT_IDS = {
    "74f5569c-f093-5143-9e06-2564c1be3dd1",  # Claude Startup ($1000) 6 bulan — Head Account
    "41f6aaa3-063a-5aaf-9ba5-d4df0879393e",  # Claude Invite Startup per seat per bulan
    "7d8930a2-6f2e-5a79-897b-baa9240ea0f0",  # Claude Invite Startup per seat 6 bulan
}

PROTECTED_EXACT_OR_KEYWORD_NAMES = [
    "claude start up",
    "claude invite startup 6 bulan",
    "claude invite startup 1 bulan",
    "claude startup",
    "claude invite startup",
]


def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def is_product_protected(product_or_id: Any) -> bool:
    """Check if a product is protected.
    
    If uncertain, blocks execution rather than taking risks.
    """
    if not product_or_id:
        return True  # If empty or uncertain, BLOCK execution

    if isinstance(product_or_id, str):
        pid = product_or_id.strip()
        if pid in PROTECTED_PRODUCT_IDS:
            return True
        return False

    if isinstance(product_or_id, dict):
        pid = str(product_or_id.get("_id") or product_or_id.get("id") or "").strip()
        if pid in PROTECTED_PRODUCT_IDS:
            return True

        sku = str(product_or_id.get("sku") or "").strip()
        if sku in {"PRD008", "SRV002", "SRV003"}:
            return True

        name = product_or_id.get("name") or product_or_id.get("product_name") or ""
        norm_name = normalize_text(name)
        if not norm_name:
            return True  # Unknown/uncertain product name -> BLOCK

        # Check Claude Startup variations
        if "claude" in norm_name and "startup" in norm_name:
            return True

        for p_name in PROTECTED_EXACT_OR_KEYWORD_NAMES:
            norm_p = normalize_text(p_name)
            if norm_p in norm_name or norm_name in norm_p:
                return True

    return False


def assert_not_protected(product_or_id: Any, action_desc: str = "Channel Automation operation"):
    """Raises PermissionError if product is protected."""
    if is_product_protected(product_or_id):
        raise PermissionError(
            f"PROTECTED PRODUCT BLOCKED: {product_or_id} is permanently excluded from {action_desc}."
        )
