"""Contract tests for the V2 tenant context verification endpoint."""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tenant_context import configure_development_tenant_resolver
from v2_tenant_routes import router


class DatabaseClient:
    def __getitem__(self, database_name):
        return {"database_name": database_name}


@pytest.fixture
def client():
    configure_development_tenant_resolver(
        {
            "acme-shop": {
                "slug": "acme-shop",
                "status": "active",
                "database_name": "sellerbottel_tenant_acme_shop",
            }
        },
        DatabaseClient(),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v2/tenant")
    return TestClient(app)


def test_info_requires_tenant_id_header(client):
    response = client.get("/api/v2/tenant/info")

    assert response.status_code == 400
    assert response.json() == {"detail": "X-Tenant-ID header is required"}


def test_info_returns_404_for_unknown_tenant(client):
    response = client.get(
        "/api/v2/tenant/info", headers={"X-Tenant-ID": "unknown-shop"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown tenant"}


def test_info_returns_the_resolved_tenant_context(client):
    response = client.get(
        "/api/v2/tenant/info", headers={"X-Tenant-ID": "acme-shop"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": "acme-shop",
        "status": "active",
        "database_name": "sellerbottel_tenant_acme_shop",
    }
