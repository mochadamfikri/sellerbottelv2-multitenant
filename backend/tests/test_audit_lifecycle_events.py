"""Platform tenant lifecycle audit events are persisted safely."""

import asyncio
from datetime import datetime, timezone

from audit_events import PLATFORM_AUDIT_ACTIONS, write_platform_audit_event
from db import db


def run(coro):
    return asyncio.run(coro)


def setup_function():
    run(db.audit_events.drop())


def test_platform_audit_actions_cover_tenant_control_plane_lifecycle():
    assert PLATFORM_AUDIT_ACTIONS == frozenset({
        "tenant.created",
        "tenant.provisioned",
        "tenant.status_updated",
        "tenant.plan_updated",
        "tenant.member_added",
        "tenant.member_removed",
    })


def test_platform_lifecycle_events_persist_actor_target_timestamp_and_redacted_metadata():
    for action in PLATFORM_AUDIT_ACTIONS:
        result = run(write_platform_audit_event(
            actor=" platform-admin:42 ",
            action=action,
            tenant_id="tenant-7",
            target={"type": "tenant", "id": "tenant-7"},
            metadata={
                "authorization": "Bearer must-not-be-stored",
                "change": action,
            },
        ))

        stored = run(db.audit_events.find_one({"_id": result["_id"]}))
        assert stored is not None
        assert stored["actor"] == "platform-admin:42"
        assert stored["action"] == action
        assert stored["target"] == {"type": "tenant", "id": "tenant-7"}
        assert stored["metadata"] == {"authorization": "***", "change": action}
        assert isinstance(stored["occurred_at"], datetime)
        # BSON / mongomock stores naive UTC datetimes, so verify recency
        assert (datetime.now(timezone.utc).replace(tzinfo=None) - stored["occurred_at"]).total_seconds() < 10
