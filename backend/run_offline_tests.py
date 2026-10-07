"""Run selected tests with a mocked database and all outbound sockets disabled.

Usage: ./venv/bin/python run_offline_tests.py tests/test_product_catalog.py -q
Do not invoke production integration tests through a running HTTP service.
"""
import os
import socket
import sys
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1"
os.environ["DB_NAME"] = "sellerbottel_mock_only"
# Offline tests use a single mocked database: the platform control-plane DB
# resolves to the same mock DB the test helpers seed (db.admins, etc.).
os.environ["PLATFORM_DB_NAME"] = "sellerbottel_mock_only"
os.environ["JWT_SECRET"] = "offline-test-secret-at-least-32-characters"
import motor.motor_asyncio
from mongomock_motor import AsyncMongoMockClient

motor.motor_asyncio.AsyncIOMotorClient = AsyncMongoMockClient


def no_network(*args, **kwargs):
    raise RuntimeError("Network disabled in offline tests")


socket.socket.connect = no_network
socket.socket.connect_ex = no_network
sys.path.insert(0, str(Path(__file__).resolve().parent))
if __name__ == "__main__":
    if not any(arg.startswith("tests/") for arg in sys.argv[1:]):
        raise SystemExit("Specify the offline test files explicitly.")
    import pytest
    raise SystemExit(pytest.main([*sys.argv[1:], "-n", "0"]))
