"""Safe audit-event construction and persistence helpers."""

from collections.abc import Mapping
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError


_SENSITIVE_METADATA_KEY_PARTS = ("token", "password", "secret", "authorization")
_REDACTED = "***"

# Canonical action names for privileged tenant control-plane changes.  Keep this
# allowlist here so callers cannot introduce near-duplicate lifecycle actions.
TENANT_CREATED = "tenant.created"
TENANT_PROVISIONED = "tenant.provisioned"
TENANT_STATUS_UPDATED = "tenant.status_updated"
TENANT_PLAN_UPDATED = "tenant.plan_updated"
TENANT_MEMBER_ADDED = "tenant.member_added"
TENANT_MEMBER_REMOVED = "tenant.member_removed"

PLATFORM_AUDIT_ACTIONS = frozenset({
    TENANT_CREATED,
    TENANT_PROVISIONED,
    TENANT_STATUS_UPDATED,
    TENANT_PLAN_UPDATED,
    TENANT_MEMBER_ADDED,
    TENANT_MEMBER_REMOVED,
})


def sanitize_metadata(value):
    """Return a copy of *value* with sensitive mapping values redacted."""
    if isinstance(value, Mapping):
        return {
            key: (
                _REDACTED
                if isinstance(key, str)
                and any(part in key.lower() for part in _SENSITIVE_METADATA_KEY_PARTS)
                else sanitize_metadata(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_metadata(item) for item in value)
    return value


def build_audit_event(*, actor, action, tenant_id=None, platform=None, metadata=None):
    """Build a validated, sanitized audit-event payload without storage I/O."""
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor must be a non-empty string")
    if not isinstance(action, str) or not action.strip():
        raise ValueError("action must be a non-empty string")
    if tenant_id is not None and (
        not isinstance(tenant_id, str) or not tenant_id.strip()
    ):
        raise ValueError("tenant_id must be a non-empty string when provided")
    if platform is not None and (
        not isinstance(platform, str) or not platform.strip()
    ):
        raise ValueError("platform must be a non-empty string when provided")

    scope = {}
    if tenant_id is not None:
        scope["tenant_id"] = tenant_id.strip()
    if platform is not None:
        scope["platform"] = platform.strip()

    return {
        "actor": actor.strip(),
        "action": action.strip(),
        "scope": scope,
        "metadata": sanitize_metadata({} if metadata is None else metadata),
    }


async def write_audit_event(
    event=None,
    *,
    actor=None,
    action=None,
    tenant_id=None,
    platform=None,
    metadata=None,
    target=None,
    idempotency_key=None,
):
    """Persist an audit event in the platform database.

    Callers may provide a payload returned by :func:`build_audit_event`, or the
    same keyword arguments accepted by that function.  An idempotency key makes
    a retry return the original event rather than creating a second record.
    """
    if event is not None:
        if not isinstance(event, Mapping):
            raise ValueError("event must be a mapping")
        if any(value is not None for value in (actor, action, tenant_id, platform, metadata)):
            raise ValueError("event cannot be combined with audit event fields")
        scope = event.get("scope", {})
        if not isinstance(scope, Mapping):
            raise ValueError("event scope must be a mapping")
        payload = build_audit_event(
            actor=event.get("actor"),
            action=event.get("action"),
            tenant_id=scope.get("tenant_id"),
            platform=scope.get("platform"),
            # Re-sanitize so only redacted metadata ever reaches storage.
            metadata=event.get("metadata"),
        )
        if target is None:
            target = event.get("target")
    else:
        payload = build_audit_event(
            actor=actor,
            action=action,
            tenant_id=tenant_id,
            platform=platform,
            metadata=metadata,
        )

    if target is not None and not isinstance(target, Mapping):
        raise ValueError("target must be a mapping when provided")
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str) or not idempotency_key.strip()
    ):
        raise ValueError("idempotency_key must be a non-empty string when provided")

    payload["occurred_at"] = datetime.now(timezone.utc)
    if target is not None:
        payload["target"] = dict(target)
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key.strip()

    # Import lazily to retain build_audit_event as a configuration-free helper.
    from db import db

    try:
        result = await db.audit_events.insert_one(payload)
    except DuplicateKeyError:
        existing = await db.audit_events.find_one(
            {"idempotency_key": payload["idempotency_key"]}
        )
        if existing is None:
            raise
        return {"ok": True, "_id": existing["_id"], "duplicate": True}

    return {"ok": True, "_id": result.inserted_id, "duplicate": False}


async def write_platform_audit_event(
    *,
    actor,
    action,
    tenant_id,
    target=None,
    metadata=None,
    idempotency_key=None,
):
    """Write a platform control-plane audit event for tenant lifecycle changes.

    This helper enforces canonical lifecycle actions and marks their scope as
    the platform control plane, distinguishing them from tenant-internal actions.
    """
    if action not in PLATFORM_AUDIT_ACTIONS:
        raise ValueError(
            f"action {action!r} is not a recognized platform audit action; "
            f"use one of {sorted(PLATFORM_AUDIT_ACTIONS)}"
        )

    return await write_audit_event(
        actor=actor,
        action=action,
        tenant_id=tenant_id,
        platform="control-plane",
        metadata=metadata,
        target=target,
        idempotency_key=idempotency_key,
    )
