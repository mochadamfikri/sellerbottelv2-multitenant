"""Tests for backend/config.py environment-validation helpers."""
import os
import re
import sys
from pathlib import Path
from io import StringIO

import pytest

# Ensure backend/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# 1. ENVIRONMENT distinguishes development / test / production
# ---------------------------------------------------------------------------

class TestEnvironmentDetection:
    def test_defaults_to_development(self, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        from config import get_environment
        assert get_environment() == "development"

    def test_accepts_production(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        from config import get_environment
        assert get_environment() == "production"

    def test_accepts_test(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "test")
        from config import get_environment
        assert get_environment() == "test"

    def test_accepts_development(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        from config import get_environment
        assert get_environment() == "development"

    def test_rejects_unknown_value(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "staging")
        from config import get_environment
        with pytest.raises(ValueError, match="ENVIRONMENT"):
            get_environment()

    def test_normalises_case(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "Production")
        from config import get_environment
        assert get_environment() == "production"


# ---------------------------------------------------------------------------
# 2. MONGO_URL on default port 27017 rejected outside production
# ---------------------------------------------------------------------------

class TestMongoUrlSafety:
    def test_rejects_27017_in_development(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
        from config import validate_mongo_url
        with pytest.raises(ValueError, match="27017"):
            validate_mongo_url()

    def test_rejects_27017_in_test(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017/mydb")
        from config import validate_mongo_url
        with pytest.raises(ValueError, match="27017"):
            validate_mongo_url()

    def test_allows_27017_in_production(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
        from config import validate_mongo_url
        # Should not raise
        validate_mongo_url()

    def test_allows_non_default_port_in_dev(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:1")
        from config import validate_mongo_url
        validate_mongo_url()  # no error


# ---------------------------------------------------------------------------
# 3. DEV database must not use production-named DB
# ---------------------------------------------------------------------------

class TestDevDbName:
    def test_rejects_production_db_name_in_dev(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("DB_NAME", "sellerbottel")
        from config import validate_db_name
        with pytest.raises(ValueError, match="production"):
            validate_db_name()

    def test_allows_test_suffix_in_dev(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("DB_NAME", "sellerbottel_dev")
        from config import validate_db_name
        validate_db_name()  # no error

    def test_allows_production_name_in_production(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("DB_NAME", "sellerbottel")
        from config import validate_db_name
        validate_db_name()  # no error

    def test_rejects_production_name_in_test_env(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("DB_NAME", "sellerbottel")
        from config import validate_db_name
        with pytest.raises(ValueError, match="production"):
            validate_db_name()

    @pytest.mark.parametrize("environment", ["development", "test"])
    def test_rejects_v2_platform_database_outside_production(self, monkeypatch, environment):
        monkeypatch.setenv("ENVIRONMENT", environment)
        monkeypatch.setenv("DB_NAME", "sellerbottel_platform")
        from config import validate_db_name
        with pytest.raises(ValueError, match="production"):
            validate_db_name()

    def test_allows_v2_platform_database_in_production(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("DB_NAME", "sellerbottel_platform")
        from config import validate_db_name
        validate_db_name()


# ---------------------------------------------------------------------------
# 4. External integration flags default to disabled
# ---------------------------------------------------------------------------

class TestExternalIntegrationDefaults:
    @pytest.mark.parametrize("flag", [
        "GOPAY_ENABLED",
        "PROMOTION_ENABLED",
        "STORE_QRIS_ENABLED",
    ])
    def test_flag_defaults_disabled(self, monkeypatch, flag):
        monkeypatch.delenv(flag, raising=False)
        from config import is_external_enabled
        assert is_external_enabled(flag) is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "True", "YES"])
    def test_flag_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv("GOPAY_ENABLED", value)
        from config import is_external_enabled
        assert is_external_enabled("GOPAY_ENABLED") is True

    def test_flag_falsy_values(self, monkeypatch):
        monkeypatch.setenv("GOPAY_ENABLED", "0")
        from config import is_external_enabled
        assert is_external_enabled("GOPAY_ENABLED") is False


# ---------------------------------------------------------------------------
# 5. Never print secrets
# ---------------------------------------------------------------------------

class TestSecretMasking:
    def test_repr_masks_secrets(self):
        from config import SafeConfig
        cfg = SafeConfig(
            environment="development",
            mongo_url="mongodb://user:password@host:27017",
            db_name="testdb",
            jwt_secret="super-secret",
        )
        text = repr(cfg)
        assert "password" not in text
        assert "super-secret" not in text
        assert "***" in text

    def test_str_masks_secrets(self):
        from config import SafeConfig
        cfg = SafeConfig(
            environment="development",
            mongo_url="mongodb://user:password@host:27017",
            db_name="testdb",
            jwt_secret="super-secret",
        )
        text = str(cfg)
        assert "password" not in text
        assert "super-secret" not in text

    def test_safe_summary_excludes_raw_values(self):
        from config import SafeConfig
        cfg = SafeConfig(
            environment="production",
            mongo_url="mongodb://admin:s3cret@prod:27017",
            db_name="sellerbottel",
            jwt_secret="jwt-tok-xyz",
        )
        summary = cfg.safe_summary()
        assert isinstance(summary, dict)
        assert "s3cret" not in str(summary)
        assert "jwt-tok-xyz" not in str(summary)
        assert summary["environment"] == "production"
        assert summary["db_name"] == "sellerbottel"
