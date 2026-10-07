"""Unit tests for pure audit-event payload construction."""

import pytest
from audit_events import build_audit_event, sanitize_metadata


# ── basic payload construction ──────────────────────────────────────


def test_build_audit_event_returns_normalized_payload():
    payload = build_audit_event(
        actor="admin:42",
        action="catalog.product.updated",
        tenant_id="tenant-1",
        platform="telegram",
    )

    assert payload == {
        "actor": "admin:42",
        "action": "catalog.product.updated",
        "scope": {"tenant_id": "tenant-1", "platform": "telegram"},
        "metadata": {},
    }


def test_scope_omits_unset_fields():
    payload = build_audit_event(actor="u", action="a")
    assert payload["scope"] == {}


def test_scope_with_only_tenant():
    payload = build_audit_event(actor="u", action="a", tenant_id="t1")
    assert payload["scope"] == {"tenant_id": "t1"}


def test_scope_with_only_platform():
    payload = build_audit_event(actor="u", action="a", platform="whatsapp")
    assert payload["scope"] == {"platform": "whatsapp"}


def test_tenant_id_must_be_nonempty_string_when_present():
    with pytest.raises(ValueError, match="tenant_id"):
        build_audit_event(actor="u", action="a", tenant_id=" ")


def test_platform_must_be_nonempty_string_when_present():
    with pytest.raises(ValueError, match="platform"):
        build_audit_event(actor="u", action="a", platform=42)


# ── validation ──────────────────────────────────────────────────────


def test_actor_must_be_nonempty_string():
    with pytest.raises(ValueError, match="actor"):
        build_audit_event(actor="", action="x")


def test_actor_rejects_none():
    with pytest.raises((ValueError, TypeError)):
        build_audit_event(actor=None, action="x")


def test_action_must_be_nonempty_string():
    with pytest.raises(ValueError, match="action"):
        build_audit_event(actor="a", action="   ")


def test_actor_is_stripped():
    payload = build_audit_event(actor="  admin  ", action="a")
    assert payload["actor"] == "admin"


# ── metadata sanitization ──────────────────────────────────────────


def test_sanitize_flat_keys():
    raw = {"user": "bob", "token": "abc123", "password": "hunter2"}
    clean = sanitize_metadata(raw)
    assert clean == {"user": "bob", "token": "***", "password": "***"}


def test_sanitize_is_case_insensitive():
    raw = {"Authorization": "Bearer xyz", "name": "ok"}
    clean = sanitize_metadata(raw)
    assert clean == {"Authorization": "***", "name": "ok"}


def test_sanitize_nested_dict():
    raw = {"outer": {"secret": "s3cr3t", "value": 1}}
    clean = sanitize_metadata(raw)
    assert clean == {"outer": {"secret": "***", "value": 1}}


def test_sanitize_list_of_dicts():
    raw = {"items": [{"token": "t1"}, {"safe": True}]}
    clean = sanitize_metadata(raw)
    assert clean == {"items": [{"token": "***"}, {"safe": True}]}


def test_sanitize_deeply_nested():
    raw = {"a": {"b": {"c": {"password": "deep"}}}}
    clean = sanitize_metadata(raw)
    assert clean == {"a": {"b": {"c": {"password": "***"}}}}


def test_sanitize_preserves_non_dict_non_list():
    assert sanitize_metadata({"x": 42}) == {"x": 42}
    assert sanitize_metadata({"x": None}) == {"x": None}


def test_sanitize_empty_dict():
    assert sanitize_metadata({}) == {}


def test_build_event_auto_sanitizes_metadata():
    payload = build_audit_event(
        actor="u",
        action="a",
        metadata={"token": "leaked", "info": "ok"},
    )
    assert payload["metadata"] == {"token": "***", "info": "ok"}
