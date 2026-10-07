"""Tests for pure IDSE migration planning and dry-run validation."""

from copy import deepcopy

from migration_planning import build_dry_run_report, validate_source_record


def test_inventory_record_requires_product_id_and_is_tagged_as_idse_owned():
    source = {"_id": "stock-1", "product_id": "product-1", "status": "available"}

    result = validate_source_record("inventory_items", source)

    assert result == {
        "valid": True,
        "collection": "inventory_items",
        "target_collection": "inventory_items",
        "operation": "copy_to_tenant",
        "identity_scope": "tenant",
        "tenant_id": "idse",
        "set_fields": {"tenant_id": "idse"},
        "errors": [],
        "warnings": [],
    }


def test_inventory_record_without_product_id_is_not_mappable():
    result = validate_source_record("inventory_items", {"_id": "stock-1"})

    assert result["valid"] is False
    assert result["errors"] == ["inventory_items requires a non-empty product_id"]


def test_purchase_preserves_legacy_invoice_and_uses_idse_counter_scope():
    source = {"_id": "purchase-1", "invoice_id": "INV-20240101-0001"}

    result = validate_source_record("purchases", source)

    assert result == {
        "valid": True,
        "collection": "purchases",
        "target_collection": "purchases",
        "operation": "copy_to_tenant",
        "identity_scope": "tenant",
        "tenant_id": "idse",
        "set_fields": {"tenant_id": "idse", "invoice_counter_scope": "idse"},
        "preserve_fields": ["invoice_id"],
        "errors": [],
        "warnings": [],
    }


def test_dry_run_report_is_pure_and_counts_planned_operations():
    records = {
        "store_customers": [{"_id": "customer-1", "email": "buyer@example.com"}],
        "inventory_items": [{"_id": "stock-1", "product_id": "product-1"}, {"_id": "stock-2"}],
    }
    original = deepcopy(records)

    report = build_dry_run_report(records)

    assert report["dry_run"] is True
    assert report["tenant_id"] == "idse"
    assert report["summary"] == {"total": 3, "valid": 2, "invalid": 1}
    assert report["operations"] == {"reference_global_identity": 1, "copy_to_tenant": 1}
    assert report["invalid_records"] == [
        {
            "collection": "inventory_items",
            "record_id": "stock-2",
            "errors": ["inventory_items requires a non-empty product_id"],
        }
    ]
    assert records == original




def test_global_customer_identity_is_referenced_not_copied_to_idse():
    source = {"_id": "customer-1", "email": "buyer@example.com", "telegram_id": 42}

    result = validate_source_record("store_customers", source)

    assert result == {
        "valid": True,
        "collection": "store_customers",
        "target_collection": "store_customers",
        "operation": "reference_global_identity",
        "identity_scope": "global",
        "tenant_id": None,
        "preserve_fields": ["_id", "email", "telegram_id"],
        "errors": [],
        "warnings": [],
    }
    assert source == {"_id": "customer-1", "email": "buyer@example.com", "telegram_id": 42}


def test_global_bot_users_identity_referenced_not_duplicated():
    source = {"_id": "user-1", "telegram_id": 12345, "first_name": "Bob"}

    result = validate_source_record("bot_users", source)

    assert result == {
        "valid": True,
        "collection": "bot_users",
        "target_collection": "bot_users",
        "operation": "reference_global_identity",
        "identity_scope": "global",
        "tenant_id": None,
        "preserve_fields": ["_id", "telegram_id"],
        "errors": [],
        "warnings": [],
    }

