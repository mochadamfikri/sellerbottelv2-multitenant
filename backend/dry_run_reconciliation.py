"""Dry-run reconciliation utilities for document counts and financial totals.

Pure module with no database calls, no network access, and deterministic
comparisons across collection counts and named financial totals.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


def _normalize_count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid collection count for {name!r}: expected non-negative integer, got {value!r}")
    if value < 0:
        raise ValueError(f"Invalid collection count for {name!r}: count must be non-negative, got {value}")
    return value


def _normalize_financial_total(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"Invalid financial total for {name!r}: boolean is not allowed")
    if isinstance(value, (int, str)):
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"Invalid financial total for {name!r}: {value!r}") from exc
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    raise ValueError(f"Invalid financial total for {name!r}: unexpected type {type(value).__name__}")


def reconcile_collections(
    source_counts: Mapping[str, Any],
    target_counts: Mapping[str, Any],
) -> dict[str, Any]:
    norm_source = {k: _normalize_count(v, k) for k, v in source_counts.items()}
    norm_target = {k: _normalize_count(v, k) for k, v in target_counts.items()}

    matched: dict[str, int] = {}
    mismatches: dict[str, dict[str, int]] = {}
    missing: dict[str, int] = {}
    extra: dict[str, int] = {}

    all_keys = sorted(set(norm_source.keys()) | set(norm_target.keys()))
    for key in all_keys:
        in_src = key in norm_source
        in_tgt = key in norm_target
        if in_src and in_tgt:
            s_val = norm_source[key]
            t_val = norm_target[key]
            if s_val == t_val:
                matched[key] = s_val
            else:
                mismatches[key] = {"source": s_val, "target": t_val}
        elif in_src:
            missing[key] = norm_source[key]
        else:
            extra[key] = norm_target[key]

    return {
        "matched": matched,
        "mismatches": mismatches,
        "missing": missing,
        "extra": extra,
    }


def reconcile_financial_totals(
    source_totals: Mapping[str, Any],
    target_totals: Mapping[str, Any],
) -> dict[str, Any]:
    norm_source = {k: _normalize_financial_total(v, k) for k, v in source_totals.items()}
    norm_target = {k: _normalize_financial_total(v, k) for k, v in target_totals.items()}

    matched: dict[str, Decimal] = {}
    mismatches: dict[str, dict[str, Decimal]] = {}
    missing: dict[str, Decimal] = {}
    extra: dict[str, Decimal] = {}

    all_keys = sorted(set(norm_source.keys()) | set(norm_target.keys()))
    for key in all_keys:
        in_src = key in norm_source
        in_tgt = key in norm_target
        if in_src and in_tgt:
            s_val = norm_source[key]
            t_val = norm_target[key]
            if s_val == t_val:
                matched[key] = s_val
            else:
                mismatches[key] = {"source": s_val, "target": t_val}
        elif in_src:
            missing[key] = norm_source[key]
        else:
            extra[key] = norm_target[key]

    return {
        "matched": matched,
        "mismatches": mismatches,
        "missing": missing,
        "extra": extra,
    }


def reconcile_snapshots(
    source_snapshot: Mapping[str, Any],
    target_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    source_collections = source_snapshot.get("collections", {})
    target_collections = target_snapshot.get("collections", {})
    source_financials = source_snapshot.get("financial_totals", {})
    target_financials = target_snapshot.get("financial_totals", {})

    collection_diff = reconcile_collections(source_collections, target_collections)
    financial_diff = reconcile_financial_totals(source_financials, target_financials)

    has_mismatches = bool(
        collection_diff["mismatches"]
        or collection_diff["missing"]
        or collection_diff["extra"]
        or financial_diff["mismatches"]
        or financial_diff["missing"]
        or financial_diff["extra"]
    )

    return {
        "passed": not has_mismatches,
        "collections": collection_diff,
        "financial_totals": financial_diff,
    }
