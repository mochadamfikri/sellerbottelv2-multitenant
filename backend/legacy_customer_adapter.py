"""Legacy customer auth & identity adapter for V3 first cutover.

Provides:
- Read-only password verification against migrated password_hash fields
  (never rehashes or mutates on login).
- Resolution of the 1 Telegram<->web linked account to a single logical wallet.
- Addressability for 53 bot users and 5 web customers.
- Direct balance authority (no wallet_ledger dependency).
- Zero-write reads.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping
import bcrypt

logger = logging.getLogger(__name__)

def verify_legacy_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against legacy hash without mutating the stored hash.

    In candidate_readonly mode, rehash-on-verify is strictly forbidden.
    """
    if not hashed_password or not plain_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception as exc:
        logger.warning("legacy_customer_adapter: password verify error: %s", exc)
        return False


class LegacyCustomerIdentity:
    """Read-only view of a customer account from migrated compatibility data."""

    def __init__(self, doc: Mapping[str, Any], account_type: str = "web"):
        self.doc = dict(doc)
        self.account_type = account_type  # "web" | "bot"

    @property
    def id(self) -> str:
        return str(self.doc.get("_id", ""))

    @property
    def email(self) -> str | None:
        return self.doc.get("email")

    @property
    def telegram_id(self) -> int | None:
        tid = self.doc.get("telegram_id")
        return int(tid) if tid is not None else None

    @property
    def username(self) -> str | None:
        return self.doc.get("username")

    @property
    def is_blocked(self) -> bool:
        return bool(self.doc.get("blocked", False) or self.doc.get("status") == "blocked")

    @property
    def balance_idr(self) -> int:
        return int(self.doc.get("balance_idr") or 0)

    @property
    def balance_usd(self) -> int:
        return int(self.doc.get("balance_usd") or 0)

    @property
    def session_version(self) -> int:
        return int(self.doc.get("session_version", 1))

    def to_profile_dict(self) -> dict[str, Any]:
        """Safe public representation without credentials."""
        return {
            "id": self.id,
            "account_type": self.account_type,
            "email": self.email,
            "telegram_id": self.telegram_id,
            "username": self.username,
            "balance_idr": self.balance_idr,
            "balance_usd": self.balance_usd,
            "is_blocked": self.is_blocked,
        }


async def authenticate_legacy_customer(
    database: Any,
    identifier: str,
    password: str,
) -> LegacyCustomerIdentity | None:
    """Authenticate a customer against store_customers using legacy hash.

    Zero-write: never updates the document or rehashes the password.
    Tolerates missing/null fields safely.
    """
    clean_id = identifier.strip().lower()

    # Search in store_customers by email
    cust = await database.store_customers.find_one({"email": clean_id})
    if not cust:
        return None

    stored_hash = cust.get("password_hash")
    if not stored_hash or not verify_legacy_password(password, stored_hash):
        return None

    return LegacyCustomerIdentity(cust, account_type="web")


async def get_customer_by_telegram_id(
    database: Any,
    telegram_id: int,
) -> LegacyCustomerIdentity | None:
    """Look up a bot user or linked customer by telegram_id.

    Zero-write read.
    """
    # Check bot_users first
    bot = await database.bot_users.find_one({"telegram_id": telegram_id})
    if bot:
        return LegacyCustomerIdentity(bot, account_type="bot")

    # Fallback to linked store_customer
    cust = await database.store_customers.find_one({"telegram_id": telegram_id})
    if cust:
        return LegacyCustomerIdentity(cust, account_type="web")

    return None


async def resolve_logical_wallet(
    database: Any,
    identity: LegacyCustomerIdentity,
) -> dict[str, Any]:
    """Resolve the single authoritative wallet for an identity.

    For Telegram<->web linked accounts, the Telegram bot wallet is
    authoritative if both exist, matching legacy storefront_routes behavior.
    Zero-write.
    """
    tid = identity.telegram_id
    if tid is not None:
        # Check if matching bot user exists
        bot = await database.bot_users.find_one({"telegram_id": tid})
        if bot:
            return {
                "wallet_id": f"bot:{tid}",
                "currency_idr": int(bot.get("balance_idr", 0)),
                "currency_usd": int(bot.get("balance_usd", 0)),
                "authority": "bot_users",
                "linked_web_customer_id": identity.id if identity.account_type == "web" else None,
            }

    # Standard direct wallet
    return {
        "wallet_id": f"{identity.account_type}:{identity.id}",
        "currency_idr": identity.balance_idr,
        "currency_usd": identity.balance_usd,
        "authority": f"store_customers" if identity.account_type == "web" else "bot_users",
        "linked_web_customer_id": None,
    }
