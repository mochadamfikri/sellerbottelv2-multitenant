"""Tests for Stage 2 dry-run verification report generator.

The report utility must verify tenant database provisioning and produce
repeatable read-only analysis without migrating documents.
"""

import pytest


def test_report_generator_captures_source_collection_counts():
    """Report must show document counts for all legacy collections."""
    from stage2_report import generate_verification_report
    
    # Mock source database with known counts
    mock_source = {
        "products": 10,
        "inventory_items": 25,
        "purchases": 5,
        "deposits": 3,
        "store_customers": 8,
        "bot_users": 12,
        "admins": 1,
    }
    
    report = generate_verification_report(
        source_counts=mock_source,
        tenant_id="idse",
        tenant_db_name="sellerbottel_tenant_idse",
        tenant_collections=[],
        tenant_indexes={},
    )
    
    assert report["source_database"] == "sellerbottel_dev"
    assert report["source_counts"]["products"] == 10
    assert report["source_counts"]["inventory_items"] == 25
    assert report["tenant_id"] == "idse"
    assert report["read_only"] is True


def test_report_generator_captures_tenant_database_state():
    """Report must verify tenant database structure and initialization."""
    from stage2_report import generate_verification_report
    
    report = generate_verification_report(
        source_counts={},
        tenant_id="idse",
        tenant_db_name="sellerbottel_tenant_idse",
        tenant_collections=["products", "inventory_items", "settings", "_meta"],
        tenant_indexes={
            "products": ["_id_", "active_created_at"],
            "inventory_items": ["_id_", "product_status", "product_fingerprint_unique"],
        },
    )
    
    assert report["tenant_database"] == "sellerbottel_tenant_idse"
    assert "products" in report["tenant_collections"]
    assert "settings" in report["tenant_collections"]
    assert report["tenant_indexes"]["products"] == ["_id_", "active_created_at"]


def test_report_generator_verifies_essential_tenant_collections():
    """Report must confirm all essential collections are initialized."""
    from stage2_report import generate_verification_report
    
    tenant_collections = [
        "settings",
        "_meta",
        "products",
        "inventory_items",
        "purchases",
        "deposits",
        "store_customers",
        "bot_users",
    ]
    
    report = generate_verification_report(
        source_counts={},
        tenant_id="idse",
        tenant_db_name="sellerbottel_tenant_idse",
        tenant_collections=tenant_collections,
        tenant_indexes={},
    )
    
    assert report["tenant_collections_initialized"] == 8
    assert report["essential_collections_present"] is True


def test_report_generator_detects_missing_essential_collections():
    """Report must flag if essential tenant collections are missing."""
    from stage2_report import generate_verification_report
    
    report = generate_verification_report(
        source_counts={},
        tenant_id="idse",
        tenant_db_name="sellerbottel_tenant_idse",
        tenant_collections=["settings", "_meta"],  # Missing essential collections
        tenant_indexes={},
    )
    
    assert report["essential_collections_present"] is False
    assert len(report["missing_collections"]) > 0


def test_report_generator_includes_audit_metadata():
    """Report must include timestamp, MongoDB version, and verification status."""
    from stage2_report import generate_verification_report
    from datetime import datetime, timezone
    
    clock = datetime(2026, 10, 4, 4, 30, tzinfo=timezone.utc)
    
    report = generate_verification_report(
        source_counts={},
        tenant_id="idse",
        tenant_db_name="sellerbottel_tenant_idse",
        tenant_collections=[],
        tenant_indexes={},
        clock=clock,
        mongo_version="7.0.43",
    )
    
    assert report["generated_at"] == "2026-10-04T04:30:00+00:00"
    assert report["mongo_version"] == "7.0.43"
    assert report["verification_type"] == "read_only"


def test_report_generator_confirms_no_documents_migrated():
    """Report must explicitly state this is read-only verification."""
    from stage2_report import generate_verification_report
    
    report = generate_verification_report(
        source_counts={"products": 10},
        tenant_id="idse",
        tenant_db_name="sellerbottel_tenant_idse",
        tenant_collections=["products"],
        tenant_indexes={},
    )
    
    assert report["read_only"] is True
    assert report["documents_migrated"] == 0
    assert "verification_only" in report["status"]
