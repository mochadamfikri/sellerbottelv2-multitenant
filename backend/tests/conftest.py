"""All tests in this directory are offline, even when run without the runner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Install MongoDB mocks BEFORE test collection imports any application module.
# This also blocks outbound sockets, including legacy HTTP integration tests.
import run_offline_tests  # noqa: F401,E402
