import asyncio
import os
import pytest
from db import client
import runtime_env

@pytest.fixture(autouse=True)
def reset_db(monkeypatch):
    async def reset():
        for name in await client.list_database_names():
            database = client[name]
            for collection in await database.list_collection_names():
                await database.drop_collection(collection)
    asyncio.run(reset())
    monkeypatch.setenv("INVENTORY_ENCRYPTION_KEY", "iInZjmnNDsHfMBTcPybUSNkfIIBns17Arb9jCTqzYnM=")
    for key in runtime_env.SECRET_FIELDS | runtime_env.VALUE_FIELDS:
        monkeypatch.delenv(key, raising=False)

async def test_runtime_env_go_pay_saved_encrypted_and_never_returned():
    result = await runtime_env.save(client, {
        "GOPAY_ENABLED": "true", "GOPAY_LOGIN_METHOD": "password",
        "GOPAY_EMAIL": "merchant@example.test", "GOPAY_PASSWORD": "not-returned",
        "GOPAY_PHONE": "08123456789", "GOPAY_QRIS_STRING": "000201010211...",
        "GOPAY_QR_TIMEOUT_MINUTES": "5", "GOPAY_POLL_INTERVAL": "15",
    })
    assert result["values"]["GOPAY_ENABLED"] == "true"
    assert result["values"]["GOPAY_LOGIN_METHOD"] == "password"
    assert result["configured"]["GOPAY_EMAIL"] is True
    assert "not-returned" not in str(result)
    assert os.environ["GOPAY_PASSWORD"] == "not-returned"
    status = await runtime_env.status(client)
    assert "not-returned" not in str(status)
    assert status["configured"]["GOPAY_QRIS_STRING"] is True

async def test_empty_secret_does_not_overwrite_existing_go_pay_secret():
    await runtime_env.save(client, {"GOPAY_PASSWORD": "first-value"})
    await runtime_env.save(client, {"GOPAY_PASSWORD": ""})
    values = await runtime_env.load(client)
    assert values["GOPAY_PASSWORD"] == "first-value"

async def test_invalid_login_method_rejected():
    with pytest.raises(ValueError):
        await runtime_env.save(client, {"GOPAY_LOGIN_METHOD": "invalid"})
