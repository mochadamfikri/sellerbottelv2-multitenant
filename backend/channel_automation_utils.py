"""Nominal Calculation and Masking utilities for Channel Automation.

Section 3: Privacy & User Masking
Section 7: Sistem Nominal
FINAL = BASE_PRICE + FEE_0_7_PERCENT + ADMIN_FEE + UNIQUE_SEQUENCE
"""
import random
import re
from typing import Optional, Tuple, Any


def mask_username(username: Optional[str], min_asterisks: int = 5, max_asterisks: int = 7) -> str:
    """Mask Telegram username preserving @ and first 2 characters, followed by 5-10 asterisks.
    
    Example:
    @RapliArdn -> @Ra*******
    """
    if not username:
        return "-"
    raw = str(username).strip()
    if not raw or raw == "-":
        return "-"
    cleaned = raw.lstrip("@")
    if not cleaned:
        return "-"
    
    prefix = cleaned[:2]
    # variable asterisks between 5-10 so true username length cannot be guessed easily
    count = random.randint(min_asterisks, max(min_asterisks, max_asterisks))
    return f"@{prefix}{'*' * count}"


def mask_user_id(telegram_id: Optional[Any]) -> str:
    """Mask Telegram User ID preserving first 3 digits and last 2 digits for 10-digit IDs.
    
    For IDs of other lengths, preserves first 3 (or 2) and last 2 digits, masking the middle.
    Example:
    1297810938 -> 129*****38
    """
    if not telegram_id:
        return "-"
    text = str(telegram_id).strip()
    if not text.isdigit():
        return "-"
    length = len(text)
    if length <= 4:
        return text[0] + "*" * (length - 1)
    if length <= 6:
        return text[:2] + "*" * (length - 3) + text[-1:]
    # Default: first 3, last 2, middle asterisks
    middle_count = length - 5
    return text[:3] + ("*" * middle_count) + text[-2:]


def calculate_nominal(base_price: int, admin_fee: int = 0, sequence: int = 1) -> dict:
    """Calculate nominal breakdown according to Section 7:
    
    FINAL = BASE_PRICE + FEE_0_7_PERCENT + ADMIN_FEE + UNIQUE_SEQUENCE
    Fee 0.7% = round(base_price * 0.007)
    """
    base = max(0, int(base_price))
    fee_07 = round(base * 0.007)
    admin = max(0, int(admin_fee))
    seq = max(1, int(sequence))
    final = base + fee_07 + admin + seq
    return {
        "base_price": base,
        "fee_0_7_percent": fee_07,
        "admin_fee": admin,
        "unique_sequence": seq,
        "final_amount": final,
        "formatted_final": format_idr(final),
    }


def format_idr(amount: int) -> str:
    return "Rp" + format(int(amount), ",").replace(",", ".")
