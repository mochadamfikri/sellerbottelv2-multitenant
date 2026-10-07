"""Tests for backend/platform_rbac.py platform and tenant role dependencies."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

# Ensure backend/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(coro):
    return asyncio.run(coro)


class TestRequirePlatformAdmin:
    def test_allows_explicit_platform_admin(self):
        """An explicit platform_admin role grants platform access."""
        from platform_rbac import require_platform_admin

        admin = {
            "_id": "admin-1",
            "email": "admin@example.com",
            "role": "admin",
            "platform_role": "platform_admin",
        }

        assert run(require_platform_admin(admin)) == admin

    def test_rejects_non_platform_admin(self):
        """Tenant-scoped users cannot access platform-only endpoints."""
        from platform_rbac import require_platform_admin

        admin = {
            "_id": "admin-2",
            "email": "admin@example.com",
            "role": "admin",
            "platform_role": "tenant_admin",
        }

        with pytest.raises(HTTPException) as exc_info:
            run(require_platform_admin(admin))

        assert exc_info.value.status_code == 403
        assert "platform admin" in exc_info.value.detail.lower()

    def test_legacy_admin_role_still_grants_platform_access(self):
        """Legacy admins without platform_role remain authorized during migration."""
        from platform_rbac import require_platform_admin

        admin = {"_id": "admin-1", "email": "admin@example.com", "role": "admin"}

        assert run(require_platform_admin(admin)) == admin

    def test_non_admin_without_platform_role_is_rejected(self):
        """A missing platform role does not grant access to ordinary users."""
        from platform_rbac import require_platform_admin

        with pytest.raises(HTTPException) as exc_info:
            run(require_platform_admin({"_id": "user-1", "role": "user"}))

        assert exc_info.value.status_code == 403


