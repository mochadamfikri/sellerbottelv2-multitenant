"""Tests for invoice sequencing module - pure functions for composing and validating invoice references."""

import pytest

from invoice_sequencing import (
    compose_invoice_reference,
    counter_initial_value,
    invoice_counter_key,
    parse_invoice_reference,
    is_valid_invoice_reference,
)


def test_compose_invoice_reference_for_idse_legacy_format():
    """IDSE tenant uses legacy format: INV-YYYYMMDD-NNNN"""
    result = compose_invoice_reference("idse", "20260921", 1)

    assert result == "INV-20260921-0001"


def test_compose_invoice_reference_for_v2_tenant_includes_tenant_prefix():
    result = compose_invoice_reference("acme-shop", "20260921", 1)

    assert result == "INV-ACME-SHOP-20260921-0001"


def test_counter_initial_value_starts_at_zero_for_first_issued_sequence_one():
    assert counter_initial_value() == 0


def test_invoice_counter_key_scopes_counter_to_tenant_and_issue_date():
    assert invoice_counter_key("acme-shop", "20260921") == "invoice:acme-shop:20260921"


def test_invoice_counter_key_preserves_idse_legacy_format():
    """IDSE legacy counter key must remain unchanged for backward compatibility."""
    assert invoice_counter_key("idse", "20260921") == "invoice:20260921"


def test_invoice_counter_key_recognizes_idse_case_insensitively():
    assert invoice_counter_key("IDSE", "20260921") == "invoice:20260921"


def test_parse_invoice_reference_legacy_idse():
    parsed = parse_invoice_reference("INV-20260921-0001")

    assert parsed == {
        "tenant_id": "idse",
        "date_str": "20260921",
        "seq": 1,
        "is_legacy": True,
    }


def test_parse_invoice_reference_for_v2_tenant():
    parsed = parse_invoice_reference("INV-ACME-SHOP-20260921-0001")

    assert parsed == {
        "tenant_id": "acme-shop",
        "date_str": "20260921",
        "seq": 1,
        "is_legacy": False,
    }


@pytest.mark.parametrize(
    "invalid_ref",
    [
        "",
        "INVALID",
        "INV",
        "INV-20260921",
        "INV-20260921-ABC",
        "INV-2026092-0001",  # 7 digits date
        "ORDER-20260921-0001",
        "INV--20260921-0001",
        None,
        123,
    ],
)
def test_parse_invoice_reference_invalid_inputs_return_none(invalid_ref):
    assert parse_invoice_reference(invalid_ref) is None


def test_compose_invoice_reference_validates_inputs():
    with pytest.raises(ValueError, match="tenant_id"):
        compose_invoice_reference("", "20260921", 1)

    with pytest.raises(ValueError, match="sequence"):
        compose_invoice_reference("tenant", "20260921", 0)

    with pytest.raises(ValueError, match="sequence"):
        compose_invoice_reference("tenant", "20260921", -1)

    with pytest.raises(ValueError, match="date"):
        compose_invoice_reference("tenant", "invalid-date", 1)


def test_is_valid_invoice_reference():
    # Valid idse legacy format
    assert is_valid_invoice_reference("INV-20260921-0001") is True
    assert is_valid_invoice_reference("INV-20260921-0001", tenant_id="idse") is True
    assert is_valid_invoice_reference("INV-20260921-0001", tenant_id="acme") is False

    # Valid V2 tenant format
    assert is_valid_invoice_reference("INV-ACME-SHOP-20260921-0001") is True
    assert is_valid_invoice_reference("INV-ACME-SHOP-20260921-0001", tenant_id="acme-shop") is True
    assert is_valid_invoice_reference("INV-ACME-SHOP-20260921-0001", tenant_id="other") is False
    assert is_valid_invoice_reference("INV-ACME-SHOP-20260921-0001", tenant_id="idse") is False

    # Invalid references
    assert is_valid_invoice_reference("bad-ref") is False
    assert is_valid_invoice_reference("") is False
    assert is_valid_invoice_reference(None) is False
