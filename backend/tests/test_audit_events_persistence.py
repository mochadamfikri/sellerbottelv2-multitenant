"""Tests for audit event database persistence."""

import asyncio
from datetime import datetime

# Mock motor before importing modules that use it.
import motor.motor_asyncio as motor
from mongomock_motor import AsyncMongoMockClient

motor.AsyncIOMotorClient = AsyncMongoMockClient

from audit_events import build_audit_event, write_audit_event
from db import db


def run(coro):
    return asyncio.run(coro)


def setup_function():
    async def reset():
        await db.audit_events.drop()
        await db.audit_events.create_index(
            "idempotency_key",
            unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string"}},
        )

    run(reset())


def test_write_audit_event_persists_to_database():
    """write_audit_event should store event with timestamp and target."""
    event = build_audit_event(
        actor="user:123",
        action="product.created",
        tenant_id="tenant-a",
        metadata={"product_id": "prod-1"},
    )

    result = run(write_audit_event(event, target={"type": "product", "id": "prod-1"}))

    assert result["ok"] is True
    assert "_id" in result

    stored = run(db.audit_events.find_one({"_id": result["_id"]}))
    assert stored is not None
    assert stored["actor"] == "user:123"
    assert stored["action"] == "product.created"
    assert stored["scope"]["tenant_id"] == "tenant-a"
    assert stored["metadata"]["product_id"] == "prod-1"
    assert stored["target"] == {"type": "product", "id": "prod-1"}
    assert isinstance(stored["occurred_at"], datetime)


def test_write_audit_event_sanitizes_metadata_before_persist():
    """Sanitized metadata should be persisted, not raw values."""
    # Persistence accepts a payload from an untrusted caller and re-sanitizes
    # it instead of trusting the caller to have used build_audit_event.
    event = {
        "actor": "admin:1",
        "action": "config.updated",
        "scope": {},
        "metadata": {"api_token": "secret123", "setting": "value"},
    }

    result = run(write_audit_event(event))

    stored = run(db.audit_events.find_one({"_id": result["_id"]}))
    assert stored is not None
    assert stored["metadata"]["api_token"] == "***"
    assert stored["metadata"]["setting"] == "value"


def test_write_audit_event_handles_duplicate_idempotently():
    """Writing the same event twice should not raise, returns existing ID."""
    event = build_audit_event(
        actor="system",
        action="tenant.created",
        tenant_id="new-tenant",
    )

    result1 = run(write_audit_event(
        event,
        target={"type": "tenant", "id": "new-tenant"},
        idempotency_key="tenant-create-new-tenant",
    ))
    result2 = run(write_audit_event(
        event,
        target={"type": "tenant", "id": "new-tenant"},
        idempotency_key="tenant-create-new-tenant",
    ))

    assert result1["_id"] == result2["_id"]
    assert result2["duplicate"] is True
    assert run(db.audit_events.count_documents(
        {"idempotency_key": "tenant-create-new-tenant"}
    )) == 1


def test_write_audit_event_without_target():
    """Target field is optional."""
    result = run(write_audit_event(build_audit_event(actor="u", action="a")))

    stored = run(db.audit_events.find_one({"_id": result["_id"]}))
    assert stored is not None
    assert "target" not in stored


def test_write_audit_event_without_idempotency_key():
    """Idempotency key is optional, allowing multiple similar events."""
    event = build_audit_event(actor="u", action="login.success")

    result1 = run(write_audit_event(event))
    result2 = run(write_audit_event(event))

    assert result1["_id"] != result2["_id"]
