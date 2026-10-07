from admin_user_routes import router as admin_user_router
from storefront_routes import _email_code_hash, _safe_attachment_name


def test_email_otp_hash_is_bound_to_email_and_code():
    assert _email_code_hash("buyer@example.com", "123456") != _email_code_hash("other@example.com", "123456")
    assert _email_code_hash("buyer@example.com", "123456") != _email_code_hash("buyer@example.com", "654321")


def test_customer_search_route_is_registered_once():
    routes = [route for route in admin_user_router.routes if route.path == "/api/admin/store-customers"]
    assert len(routes) == 1
    assert "search" in routes[0].endpoint.__annotations__


def test_order_attachment_name_cannot_escape_product_folder():
    assert _safe_attachment_name("../../session file.session", "fallback") == "session_file.session"
