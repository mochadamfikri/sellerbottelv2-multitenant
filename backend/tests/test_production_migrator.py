from __future__ import annotations

import os
import sys
from pathlib import Path
from copy import deepcopy

import pytest
from mongomock_motor import AsyncMongoMockClient

# Add tools to sys.path
TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from production_v1_v3_migrate import (
    ProductionMigrator,
    validate_safety_guards,
    load_owner_mapping,
    RESET_COLLECTION,
    MigrationSafetyError,
    TargetConflictError,
)

try:
    from cryptography.fernet import Fernet
    TEST_FERNET_KEY = Fernet.generate_key().decode()
except ImportError:
    Fernet = None
    TEST_FERNET_KEY = None


@pytest.fixture
def sample_mapping():
    return {
        "mapping_version": 1,
        "source": {
            "database": "sellerbottel",
            "business": "IDSE SellerBottel",
        },
        "tenant": {
            "slug": "idse",
            "name": "IDSE SellerBottel",
            "database_name": "sellerbottel_tenant_idse",
        },
    }


async def make_mock_client():
    client = AsyncMongoMockClient()
    src = client["sellerbottel"]

    # Seed source: 1 admin, 1 settings, 55 bot users, 5 store customers, 1 linked alias, 1116 inventory
    await src.admins.insert_one({"_id": "admin-1", "email": "admin@idse.com", "role": "owner"})
    await src.settings.insert_one({"_id": "main", "store_name": "IDSE Digital"})

    # 55 bots
    bots = []
    for i in range(55):
        bots.append({
            "_id": f"bot-{i}",
            "telegram_id": 1000 + i,
            "username": f"botuser_{i}",
            "balance_idr": 66287650 if i == 0 else 0,
            "balance_usd": 0,
        })
    await src.bot_users.insert_many(bots)

    # 5 store customers, 1 linked alias (telegram_id: 1000)
    custs = []
    for i in range(5):
        doc = {
            "_id": f"cust-{i}",
            "email": f"cust{i}@example.com",
            "password_hash": f"hash-{i}",
            "balance_idr": 2410800 if i == 0 else 0,
            "balance_usd": 0,
            "session_version": 1,
        }
        if i == 0:
            doc["telegram_id"] = 1000  # linked alias
        custs.append(doc)
    await src.store_customers.insert_many(custs)

    # 1116 inventory (759 available, 357 sold) with encrypted secret if Fernet available
    inv = []
    cipher = Fernet(TEST_FERNET_KEY.encode()) if Fernet and TEST_FERNET_KEY else None
    for i in range(759):
        secret = cipher.encrypt(f"item-avail-{i}".encode()).decode() if cipher else f"item-avail-{i}"
        inv.append({"_id": f"inv-avail-{i}", "status": "available", "secret": secret})
    for i in range(357):
        secret = cipher.encrypt(f"item-sold-{i}".encode()).decode() if cipher else f"item-sold-{i}"
        inv.append({"_id": f"inv-sold-{i}", "status": "sold", "secret": secret})
    await src.inventory_items.insert_many(inv)

    # products, counters, purchases, and custom generic historical collections
    await src.products.insert_one({"_id": "prod-1", "name": "Digital Item"})
    await src.counters.insert_one({"_id": "invoice:2026-10", "seq": 100})
    await src.purchases.insert_one({"_id": "pur-1", "invoice_id": "INV-2026-10-0100"})
    await src.custom_history_logs.insert_one({"_id": "hist-1", "action": "test_action"})

    return client


def test_safety_guards_refuse_invalid_targets():
    with pytest.raises(ValueError, match="reserved name"):
        validate_safety_guards("sellerbottel", "admin", "sellerbottel_tenant_idse")
    with pytest.raises(ValueError, match="matches source"):
        validate_safety_guards("custom_v1", "custom_v1", "sellerbottel_tenant_idse")
    with pytest.raises(ValueError, match="distinct"):
        validate_safety_guards("sellerbottel", "target_db", "target_db")


@pytest.mark.asyncio
async def test_inspect_and_dry_run_zero_writes(sample_mapping):
    mock_client = await make_mock_client()
    migrator = ProductionMigrator(
        client=mock_client,
        source_db_name="sellerbottel",
        target_platform_db="sellerbottel_v3_platform_test",
        mapping=sample_mapping,
        encryption_key=TEST_FERNET_KEY,
    )

    insp = await migrator.inspect()
    assert insp["status"] == "INSPECT_READY"
    assert insp["source"]["bot_users"] == 55
    assert insp["source"]["store_customers"] == 5
    assert insp["source"]["combined_idr"] == 68698450
    assert insp["source"]["inventory_total"] == 1116

    dry = await migrator.dry_run()
    assert dry["status"] == "DRY_RUN_PASS"
    assert dry["zero_source_writes"] is True
    if TEST_FERNET_KEY:
        assert dry["inventory_decrypt"]["status"] == "PASS"
        assert dry["inventory_decrypt"]["decrypted_count"] == 1116

    # Target must have zero collections
    assert await mock_client["sellerbottel_v3_platform_test"].list_collection_names() == []
    assert await mock_client["sellerbottel_tenant_idse"].list_collection_names() == []


@pytest.mark.asyncio
async def test_apply_refuses_without_confirmation(sample_mapping):
    mock_client = await make_mock_client()
    migrator = ProductionMigrator(
        client=mock_client,
        source_db_name="sellerbottel",
        target_platform_db="sellerbottel_v3_platform_test",
        mapping=sample_mapping,
        encryption_key=TEST_FERNET_KEY,
    )
    with pytest.raises(MigrationSafetyError, match="does not match"):
        await migrator.apply("wrong_target_name")


@pytest.mark.asyncio
async def test_apply_and_verify_invariants_and_generic_archive(sample_mapping):
    mock_client = await make_mock_client()
    migrator = ProductionMigrator(
        client=mock_client,
        source_db_name="sellerbottel",
        target_platform_db="sellerbottel_v3_platform_test",
        mapping=sample_mapping,
        encryption_key=TEST_FERNET_KEY,
    )

    # 1. Apply with confirmation
    res = await migrator.apply("sellerbottel_v3_platform_test")
    assert res["status"] == "APPLY_PASS"
    assert res["zero_source_writes"] is True

    # 2. Verify
    ver = await migrator.verify()
    assert ver["status"] == "VERIFY_PASS"
    assert ver["bot_users"] == 55
    assert ver["store_customers"] == 5
    assert ver["combined_idr"] == 68698450
    assert ver["inventory_total"] == 1116
    assert ver["inventory_available"] == 759
    assert ver["inventory_sold"] == 357
    if TEST_FERNET_KEY:
        assert ver["inventory_decrypt"]["status"] == "PASS"
        assert ver["inventory_decrypt"]["decrypted_count"] == 1116

    # 3. Check legacy reset sidecar
    tenant_db = mock_client["sellerbottel_tenant_idse"]
    sidecars = await tenant_db[RESET_COLLECTION].find().to_list(None)
    assert len(sidecars) == 5
    for s in sidecars:
        assert s["required"] is True

    # 4. Check account tenant bindings in platform DB
    platform_db = mock_client["sellerbottel_v3_platform_test"]
    bindings = await platform_db.account_tenant_bindings.find().to_list(None)
    assert len(bindings) == 60  # 55 bots + 5 store_customers

    # 5. Check generic archive collection
    arch_db = mock_client["sellerbottel_v3_platform_test_archive"]
    custom_doc = await arch_db.custom_history_logs.find_one({"_id": "hist-1"})
    assert custom_doc is not None
    assert custom_doc["action"] == "test_action"

    # 6. Check Idempotency: re-running apply changes nothing and does not duplicate
    res2 = await migrator.apply("sellerbottel_v3_platform_test")
    assert res2["status"] == "APPLY_PASS"
    ver2 = await migrator.verify()
    assert ver2["status"] == "VERIFY_PASS"
    assert ver2["bot_users"] == 55


@pytest.mark.asyncio
async def test_target_conflict_detection(sample_mapping):
    mock_client = await make_mock_client()
    # Pre-seed conflicting bot in target
    target_tenant_db = mock_client["sellerbottel_tenant_idse"]
    await target_tenant_db.bot_users.insert_one({
        "_id": "bot-0",
        "telegram_id": 1000,
        "balance_idr": 999999999,  # CONFLICT!
    })

    migrator = ProductionMigrator(
        client=mock_client,
        source_db_name="sellerbottel",
        target_platform_db="sellerbottel_v3_platform_test",
        mapping=sample_mapping,
        encryption_key=TEST_FERNET_KEY,
    )

    with pytest.raises(TargetConflictError, match="Target bot user balance conflict"):
        await migrator.apply("sellerbottel_v3_platform_test")
