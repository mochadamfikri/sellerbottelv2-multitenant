"""Offline behavioral tests for the async IDSE Stage 3 migration tool."""
import asyncio
from decimal import Decimal
from functools import wraps

import pytest
from mongomock_motor import AsyncMongoMockClient


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def tool(source, target, *, dry_run=True):
    from idse_stage3_migration import IDSEStage3Migration

    return IDSEStage3Migration(source, target, dry_run=dry_run, environment="development")


def database(name):
    return AsyncMongoMockClient()[name]


@async_test
async def test_async_mongo_handles_migrate_idempotently_and_reconcile():
    """Real async Mongo handles migrate safely, rerun idempotently, and reconcile."""
    source = database("idse_stage3_async_source")
    target = database("idse_stage3_async_target")
    await source["purchases"].insert_one({"_id": "p1", "invoice_id": "INV-20261004-0007", "total": "12.50"})
    await source["deposits"].insert_one({"_id": "d1", "amount": "2", "credited_amount": "2"})
    await source["products"].insert_one({"_id": "product-1", "name": "Plan", "secret": "never-copy"})

    first = await tool(source, target, dry_run=False).run()
    second = await tool(source, target, dry_run=False).run()
    reconciliation = await tool(source, target).financial_reconciliation()

    assert first["total_migrated"] == 3
    assert second["total_migrated"] == 0
    assert second["total_skipped"] == 3
    assert await target["products"].count_documents({"_id": "product-1", "tenant_id": "idse", "secret": {"$exists": False}}) == 1
    assert reconciliation["passed"] is True


@async_test
async def test_dry_run_returns_plan_without_target_writes():
    source = database("idse_stage3_dry_source")
    target = database("idse_stage3_dry_target")
    await source["products"].insert_one({"_id": "p1", "name": "Plan", "custom_business_field": "kept"})

    report = await tool(source, target).run()

    assert report["dry_run"] is True
    assert report["collections"]["products"]["planned"] == 1
    assert await target["products"].count_documents({}) == 0
    assert await target["migration_progress"].count_documents({}) == 0


@async_test
async def test_execute_is_idempotent_and_does_not_overwrite_existing_target_document():
    source = database("idse_stage3_existing_source")
    target = database("idse_stage3_existing_target")
    await source["products"].insert_one({"_id": "p1", "name": "Source"})
    await target["products"].insert_one({"_id": "p1", "name": "Existing", "tenant_id": "idse"})

    first = await tool(source, target, dry_run=False).run()
    second = await tool(source, target, dry_run=False).run()

    assert first["collections"]["products"] == {"migrated": 0, "skipped": 1, "planned": 1}
    assert second["collections"]["products"]["skipped"] == 1
    assert (await target["products"].find_one({"_id": "p1"}))["name"] == "Existing"


@async_test
async def test_secret_collection_is_refused_and_never_planned():
    source = database("idse_stage3_secret_source")
    target = database("idse_stage3_secret_target")
    await source["tg_accounts"].insert_one({"_id": "a1", "session_encrypted": "never-copy"})

    report = await tool(source, target).run()

    assert "tg_accounts" not in report["collections"]
    assert "tg_accounts" in report["refused_collections"]
    assert await target["tg_accounts"].count_documents({}) == 0


@async_test
async def test_migrated_business_document_is_tenant_tagged_and_secret_fields_are_stripped():
    source = database("idse_stage3_sanitize_source")
    target = database("idse_stage3_sanitize_target")
    await source["inventory_items"].insert_one({"_id": "i1", "product_id": "p1", "secret": "credential", "note": "business"})

    await tool(source, target, dry_run=False).run()

    result = await target["inventory_items"].find_one({"_id": "i1"})
    assert result["tenant_id"] == "idse"
    assert result["note"] == "business"
    assert "secret" not in result


@async_test
async def test_reconciliation_mismatch_fails_explicit_verification():
    from idse_stage3_migration import ReconciliationMismatch, verify_reconciliation

    source = database("idse_stage3_reconcile_source")
    target = database("idse_stage3_reconcile_target")
    await source["purchases"].insert_one({"_id": "p1", "total": "12.50"})
    await source["deposits"].insert_one({"_id": "d1", "amount": "2"})
    await target["purchases"].insert_one({"_id": "p1", "tenant_id": "idse", "total": "11.50"})
    await target["deposits"].insert_one({"_id": "d1", "tenant_id": "idse", "amount": "2"})

    report = await tool(source, target).financial_reconciliation()

    assert report["source"]["purchases"]["total"] == Decimal("12.50")
    assert report["target"]["purchases"]["total"] == Decimal("11.50")
    assert report["source"]["deposits"]["credited_amount"] == Decimal("0")
    with pytest.raises(ReconciliationMismatch):
        verify_reconciliation(report)


@async_test
async def test_counter_seed_uses_highest_invoice_sequence_or_source_counter_never_lower():
    source = database("idse_stage3_counter_source")
    target = database("idse_stage3_counter_target")
    await source["purchases"].insert_many([
        {"_id": "p1", "invoice_id": "INV-20261004-0007"},
        {"_id": "p2", "invoice_id": "idse-12"},
    ])
    await source["counters"].insert_one({"_id": "invoice:20261004", "seq": 19})

    result = await tool(source, target, dry_run=False).seed_invoice_counter()

    assert result["value"] == 19
    assert await target["counters"].find_one({"_id": "idse:invoice"}) == {
        "_id": "idse:invoice", "tenant_id": "idse", "counter_name": "invoice", "value": 19
    }


def test_rejects_production_and_port_27017():
    from idse_stage3_migration import IDSEStage3Migration, MigrationSafetyError

    with pytest.raises(MigrationSafetyError):
        IDSEStage3Migration(database("idse_stage3_prod_source"), database("idse_stage3_prod_target"), environment="production")
    with pytest.raises(MigrationSafetyError):
        IDSEStage3Migration(database("idse_stage3_port_source"), database("idse_stage3_port_target"), target_uri="mongodb://localhost:27017/forbidden")
