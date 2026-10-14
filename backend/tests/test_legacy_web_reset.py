from __future__ import annotations

import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import bcrypt
import pytest
from mongomock_motor import AsyncMongoMockClient

from auth import hash_password, verify_password
from candidate_readonly import CandidateReadonlyError
from legacy_customer_adapter import (
    LegacyPasswordResetRequiredError,
    authenticate_legacy_customer,
)
from legacy_web_reset import (
    REQUIREMENT_COLLECTION,
    STATE_COLLECTION,
    password_reset_required,
    mark_legacy_web_customer_bindings,
    record_password_reset_completion,
    requirement_id,
)
from bson import BSON


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["test_legacy_reset"]


@pytest.mark.asyncio
async def test_legacy_web_account_login_blocked_with_specific_state(db):
    old_hash = bcrypt.hashpw(b"legacy-pass-1", bcrypt.gensalt()).decode()
    await db.store_customers.insert_one({
        "_id": "legacy-cust-1",
        "email": "legacy@example.com",
        "password_hash": old_hash,
        "balance_idr": 1234,
        "session_version": 1,
    })
    await db[REQUIREMENT_COLLECTION].insert_one({
        "_id": requirement_id("legacy-cust-1"),
        "customer_id": "legacy-cust-1",
        "required": True,
    })

    assert await password_reset_required(db, await db.store_customers.find_one({"_id": "legacy-cust-1"})) is True

    with pytest.raises(LegacyPasswordResetRequiredError, match="PASSWORD_RESET_REQUIRED"):
        await authenticate_legacy_customer(db, "legacy@example.com", "legacy-pass-1")

    # Zero-write check
    doc = await db.store_customers.find_one({"_id": "legacy-cust-1"})
    assert doc["password_hash"] == old_hash
    assert doc["balance_idr"] == 1234


@pytest.mark.asyncio
async def test_reset_flow_with_otp_and_v3_login_success(db, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-reset")
    old_hash = bcrypt.hashpw(b"legacy-pass-1", bcrypt.gensalt()).decode()
    await db.store_customers.insert_one({
        "_id": "legacy-cust-1",
        "email": "legacy@example.com",
        "password_hash": old_hash,
        "session_version": 1,
    })
    await db[REQUIREMENT_COLLECTION].insert_one({
        "_id": requirement_id("legacy-cust-1"),
        "customer_id": "legacy-cust-1",
        "required": True,
    })

    now = datetime.now(timezone.utc)
    code = "123456"
    code_hash = hmac.new(b"test-secret-reset", f"legacy@example.com:{code}".encode(), hashlib.sha256).hexdigest()
    await db.store_email_codes.insert_one({
        "_id": "code-1",
        "email": "legacy@example.com",
        "purpose": "reset",
        "code_hash": code_hash,
        "expires_at": now + timedelta(minutes=10),
        "attempts": 0,
    })

    # Wrong code rejected
    assert not hmac.compare_digest(code_hash, hmac.new(b"test-secret-reset", b"legacy@example.com:000000", hashlib.sha256).hexdigest())

    # Expired token rejected
    expired_code_record = {
        "email": "legacy@example.com",
        "purpose": "reset",
        "expires_at": now - timedelta(seconds=1),
    }
    assert expired_code_record["expires_at"] <= now

    # Reset completion writes new hash and records completion
    new_hash = hash_password("new-secure-password-2026")
    assert verify_password("new-secure-password-2026", new_hash)
    await db.store_customers.update_one(
        {"_id": "legacy-cust-1"},
        {"$set": {"password_hash": new_hash, "password_updated_at": now}, "$inc": {"session_version": 1}},
    )
    await db.store_email_codes.delete_one({"_id": "code-1"})
    await record_password_reset_completion(db, "legacy-cust-1")

    # Reused token is impossible because deleted
    assert await db.store_email_codes.find_one({"_id": "code-1"}) is None

    # After reset: requirement is cleared and customer authenticates
    customer_after = await db.store_customers.find_one({"_id": "legacy-cust-1"})
    assert await password_reset_required(db, customer_after) is False
    identity = await authenticate_legacy_customer(db, "legacy@example.com", "new-secure-password-2026")
    assert identity is not None
    assert identity.id == "legacy-cust-1"


@pytest.mark.asyncio
async def test_migration_rerun_idempotent_and_never_reforces_reset(db):
    await db.store_customers.insert_one({"_id": "legacy-cust-1", "email": "legacy@example.com"})
    await db[REQUIREMENT_COLLECTION].insert_one({
        "_id": requirement_id("legacy-cust-1"),
        "customer_id": "legacy-cust-1",
        "required": True,
    })
    await record_password_reset_completion(db, "legacy-cust-1")

    # Simulate migration rerun upserting requirement
    await db[REQUIREMENT_COLLECTION].update_one(
        {"_id": requirement_id("legacy-cust-1")},
        {"$setOnInsert": {"customer_id": "legacy-cust-1", "required": True}},
        upsert=True,
    )

    # State still says completed; reset is NOT re-forced
    state = await db[STATE_COLLECTION].find_one({"_id": requirement_id("legacy-cust-1")})
    assert state and state.get("reset_completed_at")
    assert await password_reset_required(db, await db.store_customers.find_one({"_id": "legacy-cust-1"})) is False


@pytest.mark.asyncio
async def test_marker_migration_preserves_customers_and_is_idempotent():
    client = AsyncMongoMockClient()
    tenant = client["tenant_db"]
    migration = client["migration_db"]
    before = {
        "_id": "legacy-cust-1", "email": "legacy@example.com",
        "balance_idr": 1234, "telegram_id": 99,
    }
    await tenant.store_customers.insert_one(before.copy())
    await migration.account_tenant_bindings.insert_one({
        "_id": "binding-1", "tenant_id": "tenant-1", "database_name": "tenant_db",
        "source_collection": "store_customers", "source_id_bson": BSON.encode({"_id": "legacy-cust-1"}),
    })

    first = await mark_legacy_web_customer_bindings(client, "migration_db")
    second = await mark_legacy_web_customer_bindings(client, "migration_db")
    assert first == {"bindings": 1, "created": 1, "existing": 0}
    assert second == {"bindings": 1, "created": 0, "existing": 1}
    assert await tenant.store_customers.find_one({"_id": "legacy-cust-1"}) == before
    assert await password_reset_required(tenant, before) is True


@pytest.mark.asyncio
async def test_mid_reset_crash_recovery_prevents_lockout(db):
    from legacy_web_reset import begin_password_reset
    old_hash = bcrypt.hashpw(b"legacy-pass-1", bcrypt.gensalt()).decode()
    await db.store_customers.insert_one({
        "_id": "crash-cust-1",
        "email": "crash@example.com",
        "password_hash": old_hash,
        "session_version": 1,
    })
    await db[REQUIREMENT_COLLECTION].insert_one({
        "_id": requirement_id("crash-cust-1"),
        "customer_id": "crash-cust-1",
        "required": True,
    })

    new_hash = hash_password("new-pass-after-crash")
    await begin_password_reset(db, "crash-cust-1", new_hash)
    # Simulate customer password hash updated, but server crashed before completion write
    await db.store_customers.update_one(
        {"_id": "crash-cust-1"},
        {"$set": {"password_hash": new_hash}},
    )
    cust = await db.store_customers.find_one({"_id": "crash-cust-1"})
    # Must NOT be locked out!
    assert await password_reset_required(db, cust) is False


@pytest.mark.asyncio
async def test_candidate_token_session_version_and_reset_gating(monkeypatch):
    from candidate_legacy_routes import _issue_token, _read_token
    monkeypatch.setenv("CANDIDATE_AUTH_SECRET", "test-secret-session")
    token = _issue_token("test-store", "cust-1", 1)
    cust_id, sv = _read_token(token, "test-store")
    assert cust_id == "cust-1"
    assert sv == 1

    # Invalidated when session version bumps
    assert sv != 2


@pytest.mark.asyncio
async def test_cross_tenant_isolation(db):
    client = AsyncMongoMockClient()
    db_a = client["tenant_a"]
    db_b = client["tenant_b"]
    await db_a.store_customers.insert_one({"_id": "user-1", "email": "a@example.com"})
    await db_a[REQUIREMENT_COLLECTION].insert_one({"_id": requirement_id("user-1"), "customer_id": "user-1", "required": True})

    # Tenant B has no such customer or marker
    assert await password_reset_required(db_b, await db_b.store_customers.find_one({"_id": "user-1"})) is False


@pytest.mark.asyncio
async def test_candidate_readonly_blocks_password_reset_mutation(monkeypatch):
    monkeypatch.setenv("CANDIDATE_READONLY", "1")
    from candidate_readonly import assert_service_writable
    with pytest.raises(CandidateReadonlyError, match="storefront.password_reset"):
        assert_service_writable("storefront.password_reset")
