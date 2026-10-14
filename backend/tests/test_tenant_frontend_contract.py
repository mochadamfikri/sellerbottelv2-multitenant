"""Static tenant UI URL contract: owner routes must never leak into the panel."""
from pathlib import Path
import re
import pytest
from fastapi import FastAPI
from tenant_full_routes import router

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / "frontend/src/pages" / f"{name}.jsx" for name in (
    "TenantAdmin", "TenantProducts", "TenantCatalogs", "TenantInventory", "TenantOrders")]

CONTRACTS = [
    ("GET", "/stats"), ("GET", "/users"), ("GET", "/broadcasts"), ("POST", "/broadcasts"),
    ("GET", "/products"), ("POST", "/products"), ("PUT", "/products/{pid}"),
    ("DELETE", "/products/{pid}"), ("PATCH", "/products/{pid}/toggle"),
    ("GET", "/products/import-template"), ("POST", "/products/import"),
    ("GET", "/catalogs"), ("POST", "/catalogs"), ("DELETE", "/catalogs"),
    ("PUT", "/catalogs/rename"), ("PUT", "/catalogs/assign"),
    ("GET", "/products/{pid}/inventory"), ("GET", "/products/{pid}/inventory/summary"),
    ("POST", "/products/{pid}/inventory/validate"), ("POST", "/products/{pid}/inventory/import"),
    ("POST", "/products/{pid}/inventory/manual"), ("DELETE", "/products/{pid}/inventory/{item_id}"),
    ("PUT", "/products/{pid}/inventory/{item_id}"), ("POST", "/products/{pid}/inventory/{item_id}/file"),
    ("GET", "/products/{pid}/inventory/template"), ("PUT", "/products/{pid}/inventory/schema"),
    ("POST", "/products/{pid}/inventory/transform/inspect"), ("POST", "/products/{pid}/inventory/transform"),
    ("GET", "/orders"), ("GET", "/orders/{oid}"), ("POST", "/orders/{oid}/complete"),
    ("POST", "/orders/{oid}/refund"), ("POST", "/orders/{oid}/email/retry"),
    ("GET", "/products/{pid}/image"),
]

@pytest.mark.parametrize("method,path", CONTRACTS)
def test_management_routes_exist_with_required_method(method, path):
    full = "/api/public/tenant/full" + path
    assert any(route.path == full and method in route.methods for route in router.routes)

@pytest.mark.parametrize("source", FILES, ids=lambda path: path.stem)
def test_frontend_management_uses_no_owner_urls_or_global_authorization(source):
    text = source.read_text()
    assert not re.search(r"[\"'`]/(?:api/)?admin/", text)
    assert "api.defaults.headers.common" not in text
    assert not re.search(r'to=[\"\']/(?:products|catalogs)[?\"\']', text)


def test_legacy_panel_uses_canonical_implementation():
    source = (ROOT / "frontend/src/pages/TenantPanel.jsx").read_text()
    assert 'export { default } from "./TenantAdmin"' in source
    assert "Authorization" not in source
