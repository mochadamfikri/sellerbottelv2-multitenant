"""Backend tests for Toko Digital Bot admin API + Telegram webhook.

Covers: auth, products CRUD, deposits (webhook DB side effects, admin approve/reject/cancel),
users (adjust/freeze/unfreeze), settings persistence, and error paths.
"""
import os
import uuid
import time
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else \
    "http://127.0.0.1:8000"
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

TEST_TID = 111222333
TEST_TID_DEPOSITS = 111222334

mongo = MongoClient(MONGO_URL)
mdb = mongo[DB_NAME]


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data
    return data["token"]


@pytest.fixture
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _ensure_test_bot_user(tid=TEST_TID):
    """Idempotently ensure the test bot_user exists (avoid cross-worker races)."""
    mdb.bot_users.update_one(
        {"telegram_id": tid},
        {"$setOnInsert": {
            "_id": str(uuid.uuid4()),
            "telegram_id": tid,
            "username": "tester1",
            "first_name": "Tester",
            "currency": "IDR",
            "balance_usd": 0.0,
            "balance_idr": 0.0,
            "frozen": False,
            "frozen_reason": "",
            "cart": [],
            "state": None,
            "state_data": {},
            "created_at": "2026-01-01T00:00:00+00:00",
        }},
        upsert=True,
    )


# ============ AUTH ============

class TestAuth:
    def test_login_wrong_password(self):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": ADMIN_EMAIL, "password": "wrongpass"}, timeout=15)
        assert r.status_code == 401

    def test_admin_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/stats", timeout=15)
        assert r.status_code == 401

    def test_admin_with_bearer(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/stats", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        for k in ("total_deposit_usd", "total_deposit_idr", "circulating_idr",
                  "pending_deposits", "rate", "rate_mode"):
            assert k in data


# ============ WEBHOOK ============

class TestWebhook:
    @pytest.fixture(autouse=True)
    def _pre(self):
        # clear test bot user so /start creates fresh
        mdb.bot_users.delete_many({"telegram_id": TEST_TID})
        yield

    def test_wrong_secret_403(self):
        r = requests.post(
            f"{BASE_URL}/api/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            json={"update_id": 1},
            timeout=15,
        )
        assert r.status_code == 403

    def test_start_message_creates_user(self):
        update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "from": {"id": TEST_TID, "is_bot": False, "first_name": "Tester", "username": "tester1"},
                "chat": {"id": TEST_TID, "type": "private"},
                "text": "/start",
            },
        }
        r = requests.post(
            f"{BASE_URL}/api/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": TELEGRAM_WEBHOOK_SECRET or ""},
            json=update,
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True
        # webhook processes update as background task; wait for DB write
        found = None
        for _ in range(15):
            time.sleep(0.5)
            found = mdb.bot_users.find_one({"telegram_id": TEST_TID})
            if found:
                break
        assert found is not None, "bot_users doc not created after /start"
        assert found["first_name"] == "Tester"

    def test_callback_sets_currency_idr(self):
        cb = {
            "update_id": 2,
            "callback_query": {
                "id": "cb1",
                "from": {"id": TEST_TID, "is_bot": False, "first_name": "Tester", "username": "tester1"},
                "message": {"message_id": 2, "chat": {"id": TEST_TID, "type": "private"}},
                "data": "cur:IDR",
            },
        }
        r = requests.post(
            f"{BASE_URL}/api/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": TELEGRAM_WEBHOOK_SECRET or ""},
            json=cb,
            timeout=15,
        )
        assert r.status_code == 200
        cur = None
        for _ in range(15):
            time.sleep(0.5)
            u = mdb.bot_users.find_one({"telegram_id": TEST_TID})
            if u and u.get("currency") == "IDR":
                cur = u.get("currency")
                break
        assert cur == "IDR", f"currency not updated to IDR, got {cur}"


# ============ USERS ============

class TestUsers:
    @pytest.fixture(autouse=True)
    def _pre(self):
        _ensure_test_bot_user()
        # reset balance for deterministic assertion
        mdb.bot_users.update_one({"telegram_id": TEST_TID},
                                 {"$set": {"balance_idr": 0.0, "balance_usd": 0.0,
                                           "frozen": False, "frozen_reason": ""}})
        yield

    def test_adjust_balance_idr(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/users/{TEST_TID}/adjust",
                          json={"currency": "IDR", "amount": 100000, "reason": "test"},
                          headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        u = mdb.bot_users.find_one({"telegram_id": TEST_TID})
        assert u["balance_idr"] == 100000

    def test_list_users_includes_test(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        users = r.json()
        assert any(u.get("telegram_id") == TEST_TID for u in users)

    def test_stats_reflects_circulating(self, auth_headers):
        # give this user some balance first
        requests.post(f"{BASE_URL}/api/admin/users/{TEST_TID}/adjust",
                      json={"currency": "IDR", "amount": 100000, "reason": "seed"},
                      headers=auth_headers, timeout=15)
        r = requests.get(f"{BASE_URL}/api/admin/stats", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["circulating_idr"] >= 100000

    def test_freeze_unfreeze(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/users/{TEST_TID}/freeze",
                          json={"reason": "abuse"}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert mdb.bot_users.find_one({"telegram_id": TEST_TID})["frozen"] is True
        r = requests.post(f"{BASE_URL}/api/admin/users/{TEST_TID}/unfreeze",
                          json={}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert mdb.bot_users.find_one({"telegram_id": TEST_TID})["frozen"] is False


# ============ DEPOSITS ============

def _insert_pending_deposit(amount=75000, tid=None):
    dep = {
        "_id": str(uuid.uuid4()),
        "user_tid": tid if tid is not None else TEST_TID,
        "username": "tester1",
        "first_name": "Tester",
        "method": "bank",
        "coin": None,
        "network": None,
        "currency": "IDR",
        "amount": amount,
        "credited_amount": None,
        "tx_hash": None,
        "proof_file_id": None,
        "status": "pending",
        "auto_verified": False,
        "note": "",
        "created_at": "2026-01-01T00:00:00+00:00",
        "decided_at": None,
    }
    mdb.deposits.insert_one(dep)
    return dep["_id"]


class TestDeposits:
    TID = TEST_TID_DEPOSITS

    @pytest.fixture(autouse=True)
    def _pre(self):
        _ensure_test_bot_user(self.TID)
        mdb.bot_users.update_one({"telegram_id": self.TID},
                                 {"$set": {"balance_idr": 0.0, "balance_usd": 0.0}})
        mdb.deposits.delete_many({"user_tid": self.TID})
        yield

    def test_list_deposits_filter(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/deposits?status=all", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_approve_deposit_credits_balance(self, auth_headers):
        dep_id = _insert_pending_deposit(75000, tid=self.TID)
        before = mdb.bot_users.find_one({"telegram_id": self.TID})["balance_idr"]
        r = requests.post(f"{BASE_URL}/api/admin/deposits/{dep_id}/approve",
                          json={"note": "ok"}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = mdb.deposits.find_one({"_id": dep_id})
        assert d["status"] == "approved"
        assert d["credited_amount"] == 75000
        after = mdb.bot_users.find_one({"telegram_id": self.TID})["balance_idr"]
        assert after == before + 75000

    def test_reject_deposit(self, auth_headers):
        dep_id = _insert_pending_deposit(50000, tid=self.TID)
        r = requests.post(f"{BASE_URL}/api/admin/deposits/{dep_id}/reject",
                          json={"note": "invalid"}, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        d = mdb.deposits.find_one({"_id": dep_id})
        assert d["status"] == "rejected"

    def test_cancel_approved_reduces_balance(self, auth_headers):
        dep_id = _insert_pending_deposit(30000, tid=self.TID)
        requests.post(f"{BASE_URL}/api/admin/deposits/{dep_id}/approve",
                      json={"note": ""}, headers=auth_headers, timeout=15)
        before = mdb.bot_users.find_one({"telegram_id": self.TID})["balance_idr"]
        r = requests.post(f"{BASE_URL}/api/admin/deposits/{dep_id}/cancel",
                          headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        after = mdb.bot_users.find_one({"telegram_id": self.TID})["balance_idr"]
        assert after == before - 30000
        assert mdb.deposits.find_one({"_id": dep_id})["status"] == "cancelled"

    def test_approve_nonexistent_returns_404(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/deposits/nonexistent-id/approve",
                          json={"note": ""}, headers=auth_headers, timeout=15)
        assert r.status_code == 404


# ============ PRODUCTS ============

class TestProducts:
    def test_create_license_product(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/products",
                          data={"name": "TEST_License", "description": "test",
                                "price_usd": "5", "delivery_type": "license",
                                "content": "ABC-123", "active": "true"},
                          headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["name"] == "TEST_License"
        assert data["content"] == "ABC-123"
        assert data["delivery_type"] == "license"
        pid = data["_id"]

        # verify in list
        r2 = requests.get(f"{BASE_URL}/api/admin/products", headers=auth_headers, timeout=15)
        assert any(p["_id"] == pid for p in r2.json())

        # toggle
        r3 = requests.patch(f"{BASE_URL}/api/admin/products/{pid}/toggle",
                            headers=auth_headers, timeout=15)
        assert r3.status_code == 200

        # delete
        r4 = requests.delete(f"{BASE_URL}/api/admin/products/{pid}", headers=auth_headers, timeout=15)
        assert r4.status_code == 200

    def test_create_file_product_without_file_returns_400(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/products",
                          data={"name": "TEST_File", "description": "",
                                "price_usd": "5", "delivery_type": "file",
                                "content": "", "active": "true"},
                          headers=auth_headers, timeout=20)
        assert r.status_code == 400, r.text


# ============ SETTINGS ============

class TestSettings:
    def test_get_settings(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/settings", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "crypto_addresses" in d
        assert "current_rate" in d

    def test_update_settings_persists(self, auth_headers):
        cur = requests.get(f"{BASE_URL}/api/admin/settings", headers=auth_headers, timeout=15).json()
        addrs = cur.get("crypto_addresses") or {}
        addrs["USDT_POL"] = "0xTESTADDR1234567890"
        body = {
            "crypto_addresses": addrs,
            "bank_name": "TestBank",
            "bank_account_number": "1234567890",
            "bank_account_holder": "Test Holder",
            "min_deposit_usd": 15.0,
            "min_deposit_idr": 50000.0,
            "admin_telegram_id": cur.get("admin_telegram_id", ""),
            "rate_mode": "manual",
            "manual_rate": 17500.0,
        }
        r = requests.put(f"{BASE_URL}/api/admin/settings", json=body,
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["rate_mode"] == "manual"
        assert d["crypto_addresses"]["USDT_POL"] == "0xTESTADDR1234567890"
        assert d["manual_rate"] == 17500.0
        assert d["current_rate"] == 17500.0
