"""Browser smoke test against a local build; every API response is synthetic.

Run with a Python environment containing Playwright, pass --build and --chrome.
No production API calls, emails, payments or Telegram messages are made.
"""
import argparse
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument("--build", required=True)
parser.add_argument("--chrome", required=True)
parser.add_argument("--output", default="/tmp/idse-ui-checks")
args = parser.parse_args()
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)


class SPA(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not Path(self.translate_path(self.path)).is_file():
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SPA, directory=args.build))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}"
products = [{"_id": f"claude-{month}", "name": f"Claude Pro {month} bulan", "catalog_name": "Claude Pro", "stock": 10, "price_idr": 100000 * month, "price_idr_current": 100000 * month, "minimum_purchase_qty": 1, "product_kind": "digital", "delivery_type": "inventory", "active": True, "image_url": "/idse-logo.svg", "catalog_image_url": "/idse-logo.svg", "inventory_schema": ["email", "password"]} for month in (1, 3, 6)]
products += [{**products[0], "_id": "gpt", "name": "ChatGPT Plus", "catalog_name": "ChatGPT"}]
products[2]["stock"] = 0
profile = {"_id": "owner", "email": "owner@example.test", "display_name": "Pelanggan IDSE", "phone": "", "email_verified": True, "balance_idr": 9000000, "telegram_linked": False}
directory = [
    {"_id": "tg1", "first_name": "Telegram Only", "telegram_id": 111, "source": "telegram", "balance_idr": 12000, "purchase_count": 2},
    {"_id": "web1", "first_name": "Website Only", "email": "web@example.test", "source": "web", "balance_idr": 22000, "purchase_count": 1},
    {"_id": "linked1", "first_name": "Linked Customer", "email": "linked@example.test", "telegram_id": 222, "source": "linked", "balance_idr": 32000, "purchase_count": 3},
]
orders = []
errors = []
mutations = []
checks = []


def route_api(route):
    request = route.request
    path = urlparse(request.url).path
    data, status = {}, 200
    if "/api/" not in path:
        if request.url.startswith(base):
            return route.continue_()
        return route.abort()
    if request.method not in ("GET", "OPTIONS"):
        mutations.append(path)
    if path == "/api/auth/me":
        data = {"email": "admin@example.test", "_id": "admin"}
    elif path in ("/api/store/products", "/api/admin/products"):
        data = products
    elif path == "/api/store/config":
        data = {"telegram_bot_username": "OfflineBot"}
    elif path == "/api/store/me":
        if request.method == "PATCH":
            assert set(request.post_data_json) == {"display_name", "phone"}
            profile.update(request.post_data_json)
        data = profile
    elif path == "/api/admin/user-directory":
        query = parse_qs(urlparse(request.url).query)
        term = query.get("search", [""])[0].lower()
        source = query.get("source", ["all"])[0]
        found = [row for row in directory if term in (row.get("first_name", "") + " " + row.get("email", "")).lower()]
        items = [row for row in found if source == "all" or row["source"] == source]
        data = {"items": items, "total": len(items), "page": 1, "pages": 1, "source_counts": {"all": len(found), **{key: sum(row["source"] == key for row in found) for key in ("telegram", "web", "linked")}}}
    elif path == "/api/store/quote":
        data = {"total": 100000, "subtotal": 100000, "items": [{"product_id": "claude-1", "qty": 1, "subtotal": 100000}]}
    elif path == "/api/store/checkout":
        # Leave the request pending long enough to inspect the processing state.
        import time
        expect(page.get_by_role("heading", name="Memproses pesanan Anda", exact=True)).to_be_visible()
        expect(page.locator(".store-processing-orbit img").first).to_be_visible()
        checks.append("Processing popup with rotating cart product image")
        time.sleep(1)
        order = {"_id": "owned", "invoice_id": "TEST-INV-1", "status": "delivered", "total": 100000, "currency": "IDR", "payment_method": "balance", "created_at": "2026-09-28T14:00:00Z", "items": [{"product_id": "claude-1", "name": "Claude Pro 1 bulan", "qty": 1, "unit_price": 100000, "subtotal": 100000}]}
        orders.append(order)
        if request.post_data_json.get("payment_method") == "qris":
            order.update({"_id": "qr-order", "invoice_id": "TEST-QR", "status": "pending_payment", "payment_method": "qris", "qr_image": "/idse-logo.svg", "payment_amount": 100000, "expires_at": "2099-01-01T00:00:00Z"})
        data = order
    elif path == "/api/store/orders":
        data = orders
    elif path == "/api/store/transactions":
        data = [{**o, "id": o["_id"], "type": "order", "reference": o["invoice_id"], "amount": o["total"]} for o in orders]
    elif path == "/api/store/orders/owned/delivery":
        data = {"invoice_id": "TEST-INV-1", "ready": True, "products": [{"product_id": "claude-1", "name": "Claude Pro 1 bulan", "accounts": [{"email": "account@example.test", "password": "synthetic-secret"}], "files": []}]}
    elif path == "/api/store/orders/owned/download":
        return route.fulfill(status=200, content_type="text/plain", body="IDSE Marketplace\naccount@example.test\nsynthetic-secret")
    elif path == "/api/admin/catalogs":
        data = [{"name": name, "products": [p for p in products if p["catalog_name"] == name]} for name in ("Claude Pro", "ChatGPT")]
    elif path == "/api/admin/bot-moderation/followup/config":
        data = {"mode": "none", "channel_ids": [], "exempt_user_ids": [], "exempt_catalogs": [], "exempt_product_ids": [], "exempt_resellers": True}
    elif path.endswith("/history") or path.endswith("/broadcasts"):
        data = []
    elif "/inventory" in path:
        data = {"schema": ["email", "password"], "available": 1, "reserved": 0, "sold": 0, "total": 1, "items": [{"_id": "stock-1", "status": "available", "item": {"email": "stock@example.test", "password": "synthetic"}}]}
    elif path == "/api/admin/bot-moderation/users":
        data = []
    else:
        data = []
    route.fulfill(status=status, content_type="application/json", body=json.dumps(data))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=args.chrome, headless=True, args=["--no-sandbox"])
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    context.route("**/*", route_api)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base + "/store")
    expect(page.get_by_role("heading", name="Upgrade harimu.", exact=False)).to_be_visible()
    expect(page.get_by_role("heading", name="Jelajahi katalog", exact=True)).to_be_visible()
    page.screenshot(path=str(output / "home-desktop.png"), full_page=True)
    page.get_by_label("Cari produk dari beranda").fill("Claude")
    page.get_by_role("button", name="Cari produk", exact=True).click()
    expect(page.get_by_label("Cari katalog atau produk")).to_have_value("Claude")
    checks.append("Homepage merchandising and search query preserved")
    page.goto(base + "/store/products")
    expect(page).to_have_title("IDSE Marketplace")
    expect(page.get_by_role("heading", name="Claude Pro", exact=True)).to_be_visible()
    expect(page.get_by_text("Claude Pro 1 bulan", exact=True)).to_have_count(0)
    checks.append("Catalog-first storefront")
    page.get_by_role("heading", name="Claude Pro", exact=True).click()
    expect(page.get_by_role("button", name="Tambah Claude Pro 1 bulan ke keranjang")).to_be_visible()
    expect(page.get_by_role("button", name="Tambah ChatGPT Plus ke keranjang")).to_have_count(0)
    page.get_by_label("Tema tampilan").select_option("dark")
    expect(page.locator(".storefront-theme")).to_have_attribute("data-theme", "dark")
    page.reload()
    expect(page.locator(".storefront-theme")).to_have_attribute("data-theme", "dark")
    page.screenshot(path=str(output / "catalog-dark-desktop.png"), full_page=True)
    page.get_by_label("Tema tampilan").select_option("auto")
    page.emulate_media(color_scheme="dark")
    expect(page.locator(".storefront-theme")).to_have_attribute("data-theme", "dark")
    page.emulate_media(color_scheme="light")
    expect(page.locator(".storefront-theme")).to_have_attribute("data-theme", "light")
    checks.append("Auto/light/dark and saved manual preference")
    page.get_by_role("link", name="Claude Pro 3 bulan", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("heading", name="Claude Pro 3 bulan", exact=True)).to_be_visible()
    assert page.locator(".backdrop-blur-md").evaluate("el => getComputedStyle(el).backdropFilter").startswith("blur(")
    dialog.get_by_role("radio", name="PRO · 6 bulan", exact=False).click()
    expect(dialog.get_by_role("heading", name="Claude Pro 6 bulan", exact=True)).to_be_visible()
    expect(dialog.get_by_role("button", name="Tambah ke keranjang", exact=True)).to_be_disabled()
    dialog.get_by_role("radio", name="PRO · 3 bulan", exact=False).click()
    dialog.get_by_label("Jumlah", exact=True).fill("2")
    page.screenshot(path=str(output / "product-variants-modal.png"))
    dialog.get_by_role("button", name="Tambah ke keranjang", exact=True).click()
    expect(page.get_by_text("Produk telah ditambahkan di keranjang", exact=True)).to_be_visible(timeout=7000)
    assert page.evaluate("JSON.parse(localStorage.getItem('store_cart'))") == [{"pid": "claude-3", "qty": 2}]
    page.keyboard.press("Tab")
    assert page.evaluate("Boolean(document.activeElement.closest('[role=dialog]'))"), "Modal focus escaped"
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert "catalog=" in page.url
    page.goto(base + "/store/product/claude-1")
    expect(page.get_by_role("dialog").get_by_role("heading", name="Claude Pro 1 bulan", exact=True)).to_be_visible()
    page.get_by_role("button", name="Tutup detail produk").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert "catalog=" in page.url
    page.evaluate("localStorage.setItem('store_cart', '[]')")
    page.reload()
    checks.append("Blur modal, variant switch, sold-out guard, quantity, focus trap, Escape, deep links")
    add = page.get_by_role("button", name="Tambah Claude Pro 1 bulan ke keranjang")
    add.click()
    expect(add).to_be_disabled()
    expect(add.locator(".animate-spin")).to_be_visible()
    page.wait_for_timeout(4200)
    expect(page.get_by_label("Keranjang, 0 item")).to_be_visible()
    expect(page.get_by_text("Produk telah ditambahkan di keranjang", exact=True)).to_be_visible(timeout=2000)
    expect(page.get_by_label("Keranjang, 1 item")).to_be_visible()
    checks.append("Five-second add spinner, one cart item, animated notification")
    page.get_by_label("Keranjang, 1 item").click()
    page.get_by_role("radio", name="Saldo IDR", exact=False).check()
    checkout = page.get_by_role("button", name="Bayar dengan Saldo", exact=False)
    expect(checkout).to_be_enabled()
    checkout.click()
    expect(page.get_by_role("heading", name="Pesanan berhasil diproses", exact=True)).to_be_visible(timeout=15000)
    expect(page.get_by_text("Popup akan ditutup otomatis dalam 10 detik.", exact=True)).to_be_visible()
    page.screenshot(path=str(output / "checkout-success.png"))
    expect(page.get_by_role("heading", name="Pesanan berhasil diproses", exact=True)).to_have_count(0, timeout=12000)
    checks.append("Checkout success and ten-second automatic close")
    page.get_by_role("button", name="TEST-INV-1", exact=False).click()
    expect(page.get_by_text("account@example.test", exact=True)).to_be_visible()
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="Unduh TXT").click()
    download = downloaded.value
    assert "synthetic-secret" in Path(download.path()).read_text()
    checks.append("Owned account details and TXT download")
    page.get_by_role("button", name="Tutup", exact=True).click()
    page.evaluate("localStorage.setItem('store_cart', JSON.stringify([{pid:'claude-1',qty:1}]))")
    page.goto(base + "/store/cart")
    page.get_by_role("button", name="Bayar dengan QRIS", exact=False).click()
    expect(page.get_by_role("heading", name="QRIS All Payment", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Pesanan berhasil diproses", exact=True)).to_have_count(0)
    orders[-1]["status"] = "delivered"
    expect(page.get_by_role("heading", name="Pesanan berhasil diproses", exact=True)).to_be_visible(timeout=10000)
    page.get_by_role("button", name="Tutup status checkout").click()
    expect(page.get_by_role("heading", name="Pesanan berhasil diproses", exact=True)).to_have_count(0)
    checks.append("QRIS waits for completion; success popup can close manually")
    page.goto(base + "/store/profile")
    page.get_by_role("button", name="Edit profil", exact=True).click()
    page.get_by_label("Nama tampilan", exact=True).fill("Nama Diperbarui")
    page.get_by_label("Nomor kontak", exact=False).fill("+62 81234567890")
    page.get_by_role("button", name="Simpan profil", exact=True).click()
    expect(page.get_by_text("Profil berhasil diperbarui.", exact=True)).to_be_visible()
    expect(page.get_by_label("Email login", exact=True)).to_be_disabled()
    page.reload()
    expect(page.get_by_label("Nama tampilan", exact=True)).to_have_value("Nama Diperbarui")
    expect(page.get_by_label("Nomor kontak", exact=False)).to_have_value("+62 81234567890")
    page.get_by_role("button", name="Edit profil", exact=True).click()
    page.get_by_label("Nama tampilan", exact=True).fill("Unsaved change")
    page.get_by_role("button", name="Batal", exact=True).click()
    expect(page.get_by_label("Nama tampilan", exact=True)).to_have_value("Nama Diperbarui")
    page.screenshot(path=str(output / "profile-edit.png"), full_page=True)
    checks.append("Profile edit persists, cancel restores, login identity remains read-only")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base + "/store/products")
    page.get_by_label("Tema tampilan").select_option("dark")
    expect(page.get_by_role("heading", name="Claude Pro", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Mobile horizontal overflow"
    page.get_by_role("button", name="Buka menu").click()
    expect(page.get_by_role("navigation", name="Menu mobile").get_by_role("link", name="Beranda", exact=False)).to_be_visible()
    assert page.get_by_role("navigation", name="Menu mobile").locator("a svg").count() >= 7
    page.wait_for_timeout(350)
    page.screenshot(path=str(output / "catalog-mobile.png"), full_page=True, animations="disabled")
    checks.append("Mobile catalog, menu and no horizontal overflow")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(base + "/catalogs")
    expect(page.get_by_text("Claude Pro", exact=True).first).to_be_visible()
    page.screenshot(path=str(output / "admin-catalogs.png"), full_page=True)
    checks.append("Admin catalog page")
    page.goto(base + "/users")
    expect(page.get_by_role("cell", name="Telegram Only", exact=True)).to_be_visible()
    page.get_by_role("button", name="Website saja", exact=False).click()
    expect(page.get_by_role("cell", name="Website Only", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="Telegram Only", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Web + Telegram", exact=False).click()
    expect(page.get_by_role("cell", name="Linked Customer", exact=True)).to_be_visible()
    page.get_by_role("button", name="Semua pengguna", exact=False).click()
    page.get_by_placeholder("Email, nama, @username, atau ID Telegram").fill("web@example.test")
    expect(page.get_by_role("cell", name="Website Only", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name="Linked Customer", exact=True)).to_have_count(0)
    page.screenshot(path=str(output / "admin-user-source-filter.png"), full_page=True)
    checks.append("Admin source filters and search use server directory without duplicates")
    assert not errors, errors
    assert all(p in ("/api/store/quote", "/api/store/checkout", "/api/store/me") for p in mutations)
    report = {"passed": checks, "browser_errors": errors, "mocked_mutations": mutations}
    (output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    browser.close()
server.shutdown()
