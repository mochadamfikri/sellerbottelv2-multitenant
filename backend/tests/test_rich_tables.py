import pytest
from rich_tables import table_pages
from product_rich_views import warranty_label, product_detail_pages
from history_rich_views import history_pages, transaction_detail_pages

def test_rich_tables_basic():
    headers = ["Col1", "Col2"]
    rows = [["Val1", "Val2"], ["Val3", "Val4"]]
    pages = table_pages("Test Title", headers, rows, page_size=5)
    assert len(pages) == 1
    assert "Test Title" in pages[0].html
    assert "Col1" in pages[0].html
    assert "Val1" in pages[0].html

def test_warranty_label():
    p1 = {"warranty": {"enabled": True, "duration": "30 hari"}}
    assert "30 hari" in warranty_label(p1)
    p2 = {"warranty": {"enabled": False}}
    assert "Tidak Ada" in warranty_label(p2)
    p3 = {}
    assert "Belum diinformasikan" in warranty_label(p3)

def test_history_pages_empty():
    pages = history_pages([], lambda amt, cur: f"{amt} {cur}")
    assert len(pages) == 1
    assert "Riwayat" in pages[0].html
