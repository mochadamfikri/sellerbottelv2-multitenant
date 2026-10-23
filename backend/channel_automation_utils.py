"""Nominal Calculation, Masking, and Dummy Generator for Channel Automation V2.

Section 2: GENERATOR DATA SIMULASI
- NAME: "@" + two random alphabet characters + 5-10 asterisks (e.g. @Ra*******, @Ms******, @Al********, @Di*****)
- USER: Exactly 10 digits. First digit strictly in [1, 2, 4, 5, 6, 7, 8].
  Display masking: 3 digit awal + 5 asterisk + 2 digit akhir (e.g. 129*****38, 562*****73, 481*****29)

Section 5: NOMINAL CALCULATION
- FINAL = PRODUCT_PRICE + (PRODUCT_PRICE * 0.007) + ADMIN_FEE + UNIQUE_SEQUENCE
"""
import random
import re
import string
from typing import Optional, Tuple, Any, Dict


def generate_dummy_username() -> str:
    """Generates dummy Telegram username according to Section 2:
    
    '@' + two letters + 5 to 10 asterisks.
    Examples: @Ra*******, @Ms******, @Al********, @Di*****
    """
    first_letter = random.choice(string.ascii_uppercase)
    second_letter = random.choice(string.ascii_lowercase)
    asterisk_count = random.randint(5, 10)
    return f"@{first_letter}{second_letter}{'*' * asterisk_count}"


def generate_dummy_user_id() -> Tuple[str, str]:
    """Generates dummy 10-digit Telegram User ID according to Section 2:
    
    - First digit MUST be one of: 1, 2, 4, 5, 6, 7, 8
    - Exactly 10 digits
    - Returns (raw_id, masked_id)
    - Masking: 3 digit awal + 5 asterisk + 2 digit akhir (e.g. 129*****38)
    """
    first_digit = str(random.choice([1, 2, 4, 5, 6, 7, 8]))
    remaining_digits = "".join(random.choices(string.digits, k=9))
    raw_id = first_digit + remaining_digits
    masked = mask_user_id(raw_id)
    return raw_id, masked


def mask_username(username: Optional[str], min_asterisks: int = 5, max_asterisks: int = 10) -> str:
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
    count = random.randint(min_asterisks, max(min_asterisks, max_asterisks))
    return f"@{prefix}{'*' * count}"


def mask_user_id(telegram_id: Optional[Any]) -> str:
    """Mask Telegram User ID preserving first 3 digits and last 2 digits for 10-digit IDs.
    
    Format: 3 digit awal + 5 asterisk + 2 digit akhir (e.g. 129*****38).
    For IDs of other lengths, preserves first 3 and last 2 digits, masking the middle.
    """
    if not telegram_id:
        return "-"
    text = str(telegram_id).strip()
    if not text.isdigit():
        return "-"
    length = len(text)
    if length == 10:
        return f"{text[:3]}*****{text[-2:]}"
    if length <= 4:
        return text[0] + "*" * (length - 1)
    if length <= 6:
        return text[:2] + "*" * (length - 3) + text[-1:]
    # Middle asterisks for other lengths
    middle_count = length - 5
    return text[:3] + ("*" * middle_count) + text[-2:]



def calculate_nominal(base_price: int, admin_fee: int = 0, sequence: int = 1) -> Dict[str, Any]:
    """Calculate nominal breakdown according to Section 5:
    
    FINAL = PRODUCT_PRICE + (PRODUCT_PRICE * 0.007) + ADMIN_FEE + UNIQUE_SEQUENCE
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
