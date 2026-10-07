import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
import catalog_routes as routes
from bulk_product_import import _parse_product_rows
from product_catalog import catalog_name


class Cursor:
    def __init__(self, rows):
        self.rows = deepcopy(rows)

    async def to_list(self, length=None):
        return self.rows


class Collection:
    def __init__(self, rows=()):
        self.rows = deepcopy(list(rows))

    def matching(self, query):
        return [row for row in self.rows if all(
            row.get(key) in value["$in"] if isinstance(value, dict) else row.get(key) == value
            for key, value in query.items())]

    def find(self, query, projection=None):
        return Cursor(self.matching(query))

    async def find_one(self, query):
        return next(iter(self.matching(query)), None)

    async def count_documents(self, query):
        return len(self.matching(query))

    async def update_many(self, query, update):
        rows = self.matching(query)
        for row in rows:
            row.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=len(rows))

    async def update_one(self, query, update, upsert=False):
        rows = self.matching(query)
        if not rows and upsert:
            self.rows.append({**query, **update.get("$setOnInsert", {}), **update.get("$set", {})})
        elif rows:
            rows[0].update(update.get("$set", {}))

    async def delete_one(self, query):
        self.rows = [row for row in self.rows if row not in self.matching(query)]


@pytest.fixture
def database(monkeypatch):
    db = SimpleNamespace(products=Collection([
        {"_id": str(months), "name": f"Claude AI Pro - {months} Bulan", "active": months != 6,
         "stock": months, "price_idr": months * 10000}
        for months in (1, 3, 6)
    ]), product_catalogs=Collection(), settings=Collection())
    monkeypatch.setattr(routes, "db", db)
    return db


def test_existing_variants_and_explicit_assignment():
    assert catalog_name({"name": "Claude AI Pro - 12 Bulan / 1 Tahun"}) == "Claude Pro"
    assert catalog_name({"name": "Claude AI Pro", "catalog_name": "  AI   Premium  "}) == "AI Premium"
    assert catalog_name({"name": "Unknown 1 bulan"}) == "Produk Lainnya"


def test_catalog_management_preserves_price_stock_and_ids(database):
    async def scenario():
        original = deepcopy(database.products.rows)
        assert len((await routes.list_catalogs())[0]["products"]) == 3
        await routes.rename_catalog(routes.RenameBody(old_name="Claude Pro", name="Claude Premium"))
        assert all(p["catalog_name"] == "Claude Premium" for p in database.products.rows)
        await routes.assign_catalog(routes.AssignBody(name="Langganan AI", product_ids=["1", "3"]))
        await routes.delete_catalog("Langganan AI")
        assert [p["catalog_name"] for p in database.products.rows] == ["Produk Lainnya", "Produk Lainnya", "Claude Premium"]
        for before, after in zip(original, database.products.rows):
            assert {k: after[k] for k in before} == before
    asyncio.run(scenario())


def test_invalid_assignment_makes_no_changes(database):
    async def scenario():
        before = deepcopy(database.products.rows)
        with pytest.raises(HTTPException) as error:
            await routes.assign_catalog(routes.AssignBody(name="New", product_ids=["1", "missing"]))
        assert error.value.status_code == 404
        assert database.products.rows == before
        assert database.product_catalogs.rows == []
    asyncio.run(scenario())


def test_duplicate_names_and_empty_catalogs(database):
    async def scenario():
        await routes.create_catalog(routes.CatalogBody(name="Design"))
        await routes.create_catalog(routes.CatalogBody(name="design"))
        assert len(database.product_catalogs.rows) == 1
        with pytest.raises(HTTPException) as error:
            await routes.rename_catalog(routes.RenameBody(old_name="Claude Pro", name="Design"))
        assert error.value.status_code == 409
        await routes.delete_catalog("Design")
        assert database.product_catalogs.rows == []
    asyncio.run(scenario())


def test_excel_catalog_and_legacy_template():
    wb = Workbook()
    ws = wb.active
    ws.append(["Nama Product", "Jenis Product", "Harga IDR", "Katalog"])
    ws.append(["Claude 1 bulan", "A. Produk Digital", 100000, "Claude Pro"])
    products, errors = _parse_product_rows(ws, 15000)
    assert not errors
    assert products[0]["catalog_name"] == "Claude Pro"
    ws.delete_cols(4)
    products, errors = _parse_product_rows(ws, 15000)
    assert not errors
    assert products[0]["catalog_name"] == ""


def test_catalog_routes_are_admin_protected():
    from admin_routes import router
    catalog_routes = [route for route in router.routes if route.path.startswith("/api/admin/catalogs")]
    assert len(catalog_routes) == 5
    assert all(route.dependencies for route in catalog_routes)
