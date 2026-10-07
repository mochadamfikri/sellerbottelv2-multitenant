"""Strict offline tests for dry-run document and financial reconciliation."""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dry_run_reconciliation import reconcile_snapshots


def test_reconcile_snapshots_passes_when_all_named_values_match():
    source = {
        "collections": {"orders": 12, "users": 4},
        "financial_totals": {"sales_idr": Decimal("150000.50"), "sales_usd": "12.30"},
    }
    target = {
        "collections": {"orders": 12, "users": 4},
        "financial_totals": {"sales_idr": "150000.50", "sales_usd": Decimal("12.30")},
    }

    result = reconcile_snapshots(source, target)

    assert result == {
        "passed": True,
        "collections": {"matched": {"orders": 12, "users": 4}, "mismatches": {}, "missing": {}, "extra": {}},
        "financial_totals": {
            "matched": {"sales_idr": Decimal("150000.50"), "sales_usd": Decimal("12.30")},
            "mismatches": {},
            "missing": {},
            "extra": {},
        },
    }


def test_reconcile_snapshots_reports_collection_count_mismatches():
    result = reconcile_snapshots(
        {"collections": {"orders": 12}, "financial_totals": {}},
        {"collections": {"orders": 10}, "financial_totals": {}},
    )

    assert result["passed"] is False
    assert result["collections"]["mismatches"] == {"orders": {"source": 12, "target": 10}}
    assert result["financial_totals"] == {"matched": {}, "mismatches": {}, "missing": {}, "extra": {}}


def test_reconcile_snapshots_reports_missing_and_extra_names_per_section():
    result = reconcile_snapshots(
        {
            "collections": {"orders": 12, "users": 4},
            "financial_totals": {"sales_idr": "100.00", "refunds_idr": "5.00"},
        },
        {
            "collections": {"orders": 12, "sessions": 3},
            "financial_totals": {"sales_idr": "100.00", "fees_idr": "2.00"},
        },
    )

    assert result["passed"] is False
    assert result["collections"] == {
        "matched": {"orders": 12},
        "mismatches": {},
        "missing": {"users": 4},
        "extra": {"sessions": 3},
    }
    assert result["financial_totals"] == {
        "matched": {"sales_idr": Decimal("100.00")},
        "mismatches": {},
        "missing": {"refunds_idr": Decimal("5.00")},
        "extra": {"fees_idr": Decimal("2.00")},
    }


def test_reconcile_snapshots_reports_financial_total_mismatch_without_float_rounding():
    result = reconcile_snapshots(
        {"collections": {}, "financial_totals": {"sales_usd": "0.30"}},
        {"collections": {}, "financial_totals": {"sales_usd": "0.31"}},
    )

    assert result["passed"] is False
    assert result["financial_totals"]["mismatches"] == {
        "sales_usd": {"source": Decimal("0.30"), "target": Decimal("0.31")}
    }


def test_reconcile_snapshots_rejects_invalid_counts_and_financial_totals():
    invalid_count_source = {"collections": {"orders": -1}, "financial_totals": {}}
    invalid_total_source = {"collections": {}, "financial_totals": {"sales_usd": "not-money"}}

    import pytest

    with pytest.raises(ValueError, match="collection count"):
        reconcile_snapshots(invalid_count_source, {"collections": {}, "financial_totals": {}})
    with pytest.raises(ValueError, match="financial total"):
        reconcile_snapshots(invalid_total_source, {"collections": {}, "financial_totals": {}})


def test_reconcile_snapshots_handles_empty_snapshots():
    result = reconcile_snapshots(
        {"collections": {}, "financial_totals": {}},
        {"collections": {}, "financial_totals": {}},
    )

    assert result["passed"] is True
    assert result["collections"] == {"matched": {}, "mismatches": {}, "missing": {}, "extra": {}}
    assert result["financial_totals"] == {"matched": {}, "mismatches": {}, "missing": {}, "extra": {}}


def test_reconcile_snapshots_accepts_zero_counts_and_totals():
    result = reconcile_snapshots(
        {"collections": {"orders": 0}, "financial_totals": {"sales_usd": "0.00"}},
        {"collections": {"orders": 0}, "financial_totals": {"sales_usd": "0"}},
    )

    assert result["passed"] is True
    assert result["collections"]["matched"] == {"orders": 0}
    assert result["financial_totals"]["matched"] == {"sales_usd": Decimal("0.00")}


def test_reconcile_snapshots_accepts_negative_financial_totals_for_refunds():
    result = reconcile_snapshots(
        {"collections": {}, "financial_totals": {"refunds_usd": "-12.50"}},
        {"collections": {}, "financial_totals": {"refunds_usd": Decimal("-12.50")}},
    )

    assert result["passed"] is True
    assert result["financial_totals"]["matched"] == {"refunds_usd": Decimal("-12.50")}
