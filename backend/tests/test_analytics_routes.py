import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from server import app
from auth import get_current_admin

@pytest.fixture
def mock_admin():
    return {"_id": "test_admin", "username": "admin", "role": "admin"}

def test_analytics_endpoints(mock_admin):
    async def run():
        app.dependency_overrides[get_current_admin] = lambda: mock_admin
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            track_resp = await ac.post("/api/analytics/track", json={
                "channel": "web_store", "event_type": "page_view", "path": "/store"
            })
            assert track_resp.status_code == 200
            assert track_resp.json() == {"ok": True}

            click_resp = await ac.post("/api/analytics/track", json={
                "channel": "web_store", "event_type": "click", "product_id": "p1", "product_name": "Product 1"
            })
            assert click_resp.status_code == 200

            cart_resp = await ac.post("/api/analytics/track", json={
                "channel": "web_store", "event_type": "add_to_cart", "product_id": "p1", "product_name": "Product 1"
            })
            assert cart_resp.status_code == 200

            summary_resp = await ac.get("/api/admin/analytics/summary?time_range=7d")
            assert summary_resp.status_code == 200
            data = summary_resp.json()
            assert set(("profile_web", "shopping_web", "telegram_bot", "top_clicked_products", "top_cart_products")) <= set(data)
        app.dependency_overrides.clear()

    import asyncio
    asyncio.run(run())
