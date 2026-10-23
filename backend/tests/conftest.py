"""All tests in this directory are offline, even when run without the runner."""
import os
import sys
from pathlib import Path

# In offline tests, default rich tables to false so legacy mock assertions pass,
# while explicit rich table tests enable it via monkeypatch.
os.environ["TELEGRAM_RICH_TABLES_ENABLED"] = "false"
# Offline test runner isolation
os.environ.setdefault("ENVIRONMENT", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Install MongoDB mocks BEFORE test collection imports any application module.
# This also blocks outbound sockets, including legacy HTTP integration tests.
import run_offline_tests  # noqa: F401,E402
