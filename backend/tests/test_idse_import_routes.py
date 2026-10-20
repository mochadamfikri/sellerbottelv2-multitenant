import io
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
import openpyxl
from idse_import_routes import router, require_tenant_operator, get_tenant_context
from idse_workbook_schema import inspect_workbook


def app(authorized):
    a = FastAPI(); a.include_router(router)
    if authorized:
        a.dependency_overrides[require_tenant_operator] = lambda: {'_id':'admin'}
        a.dependency_overrides[get_tenant_context] = lambda: SimpleNamespace(tenant_id='test')
    return TestClient(a)


def test_template_roundtrip_preview_never_applies():
    c = app(True)
    response = c.get('/api/v2/import-excel/template')
    assert response.status_code == 200
    assert inspect_workbook(response.content)['structural_valid']
    response = c.post('/api/v2/import-excel/preview', files={'file':('template.xlsx',response.content)})
    assert response.status_code == 200
    assert response.json()['apply_allowed'] is False
    assert response.json()['tenant_id'] == 'test'


def test_unauthorized_and_invalid_file():
    assert app(False).get('/api/v2/import-excel/template').status_code in (401,403,400)
    c = app(True)
    assert c.post('/api/v2/import-excel/preview',files={'file':('bad.xlsx',b'SECRET_PAYLOAD')}).status_code == 400
    assert c.post('/api/v2/import-excel/preview',files={'file':('bad.csv',b'SECRET_PAYLOAD')}).status_code == 400
    response = c.post('/api/v2/import-excel/preview',files={'file':('bad.xlsx',b'SECRET_PAYLOAD')})
    assert 'SECRET_PAYLOAD' not in response.text
