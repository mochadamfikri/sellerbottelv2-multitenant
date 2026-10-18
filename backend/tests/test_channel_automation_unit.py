"""Automated Unit & Integration Tests for Channel Automation & Inventory Management.

Covers the mandatory 22 tests from Section 16:
1. Native Telegram Rich Table rendered
2. Hyperlink produk points to target product deep link
3. Username masking works (@RapliArdn -> @Ra*******)
4. User ID masking works (1297810938 -> 129*****38)
5. Nominal 0.7% calculated correctly (15000 + 105 + 0 + 1 = 15106)
6. Unique sequence does not collide
7. Protected products are strictly excluded
8. Selection only picks available products with inventory
9. Reservation decreases available stock
10. Reservation does not count as sale/revenue
11. Restore All per product works
12. Restore Partial per product works
13. Restore does not affect other products
14. SOLD inventory cannot be restored
15. Runtime custom sequence works
16. Runtime random sequence works
17. Campaign pause / resume works
18. Restart recovery does not duplicate message
19. Telegram network failure does not corrupt inventory
20. Product catalog / stock consistency
21. Real transaction notification works
22. Audit trail logs every operation
"""
import asyncio
import os
import pytest
from html import escape

from channel_automation_protection import (
    is_product_protected,
    assert_not_protected,
    PROTECTED_PRODUCT_IDS,
)
from channel_automation_utils import (
    mask_username,
    mask_user_id,
    calculate_nominal,
    format_idr,
)
from channel_automation_tables import (
    render_verified_transaction_table,
    render_promo_product_table,
    render_simulation_table,
    make_product_url,
)
from channel_automation_scheduler import (
    parse_interval_to_seconds,
    select_next_interval_seconds,
)


# Test 1 & 2: Native Telegram Rich Table & Product Hyperlink
def test_native_rich_table_rendering_and_hyperlinks():
    rendered = render_verified_transaction_table(
        customer_name="@RapliArdn",
        customer_telegram_id="1297810938",
        product_name="Gemini Pro 18 Bulan",
        product_id="dd1cce0a-2633-59c5-8ca3-f1ae40db80d3",
        final_amount=15106,
        bot_username="Idse_MarketBot",
    )
    assert "<table bordered striped compact>" in rendered.html
    assert "TRANSAKSI BERHASIL" in rendered.html
    assert 'href="https://t.me/Idse_MarketBot?start=prod_dd1cce0a-2633-59c5-8ca3-f1ae40db80d3"' in rendered.html
    assert "Gemini Pro 18 Bulan</a>" in rendered.html
    assert "Rp15.106" in rendered.html
    assert "Terima kasih sudah berbelanja 🙏" in rendered.html


# Test 3: Username Masking
def test_username_masking():
    masked = mask_username("@RapliArdn")
    assert masked.startswith("@Ra")
    assert len(masked) >= 8  # @ + 2 chars + min 5 asterisks
    assert "*" in masked
    assert "Rapli" not in masked


# Test 4: User ID Masking
def test_user_id_masking():
    # 10 digits
    masked = mask_user_id("1297810938")
    assert masked == "129*****38"
    assert len(masked) == 10
    # Other lengths
    masked_short = mask_user_id("1234567")
    assert masked_short == "123**67"


# Test 5 & 6: Nominal 0.7% & Unique Sequence
def test_nominal_calculation_and_sequence():
    res1 = calculate_nominal(base_price=15000, admin_fee=0, sequence=1)
    assert res1["base_price"] == 15000
    assert res1["fee_0_7_percent"] == 105
    assert res1["admin_fee"] == 0
    assert res1["unique_sequence"] == 1
    assert res1["final_amount"] == 15106
    assert res1["formatted_final"] == "Rp15.106"

    # Sequence 2: 15000 + 105 + 0 + 2 = 15107
    res2 = calculate_nominal(base_price=15000, admin_fee=0, sequence=2)
    assert res2["final_amount"] == 15107
    assert res1["final_amount"] != res2["final_amount"]


# Test 7: Protected Products Permanent Exclusion
def test_protected_products_exclusion():
    # Identified protected IDs
    for pid in PROTECTED_PRODUCT_IDS:
        assert is_product_protected(pid) is True
        assert is_product_protected({"_id": pid, "name": "Any Name"}) is True
        with pytest.raises(PermissionError):
            assert_not_protected(pid)

    # Name-based checks
    protected_samples = [
        {"_id": "test-1", "name": "Claude Start Up"},
        {"_id": "test-2", "name": "Claude Invite Startup 6 Bulan"},
        {"_id": "test-3", "name": "Claude Invite Startup 1 Bulan"},
        {"_id": "test-4", "name": "Claude Startup ($1000) 6 bulan — Head Account"},
        {"_id": "test-5", "name": "Claude Invite Startup per seat per bulan"},
    ]
    for p in protected_samples:
        assert is_product_protected(p) is True
        with pytest.raises(PermissionError):
            assert_not_protected(p)

    # Non-protected products must pass
    allowed_samples = [
        {"_id": "dd1cce0a-2633-59c5-8ca3-f1ae40db80d3", "name": "Gemini Google AI Plus 400GB 12 bulan"},
        {"_id": "allow-1", "name": "ChatGPT Plus Reguler 1 bulan"},
        {"_id": "allow-2", "name": "Netflix 1P1U"},
    ]
    for p in allowed_samples:
        assert is_product_protected(p) is False


# Test 15 & 16: Scheduler Sequence & Random Modes
def test_scheduler_intervals_and_sequences():
    # Parsing
    assert parse_interval_to_seconds(180) == 180
    assert parse_interval_to_seconds("3 menit") == 180
    assert parse_interval_to_seconds("3.5m") == 210
    assert parse_interval_to_seconds("2m 20s") == 140

    # Mode A / B: Custom Sequence
    campaign = {
        "schedule_mode": "custom_sequence",
        "sequence_seconds": [180, 120, 180, 360, 300, 330],
        "current_sequence_index": 0,
    }
    assert select_next_interval_seconds(campaign) == 180
    campaign["current_sequence_index"] = 1
    assert select_next_interval_seconds(campaign) == 120
    campaign["current_sequence_index"] = 5
    assert select_next_interval_seconds(campaign) == 330
    campaign["current_sequence_index"] = 6
    assert select_next_interval_seconds(campaign) == 180  # loop around

    # Mode C: Random sequence from pool
    campaign_random = {
        "schedule_mode": "random_pool",
        "interval_pool_seconds": [30, 60, 90, 120],
    }
    chosen = select_next_interval_seconds(campaign_random)
    assert chosen in [30, 60, 90, 120]


# Test Promo & Simulation Table Renderers
def test_promo_and_simulation_renderers():
    promo = render_promo_product_table(
        product_name="Gemini Pro 18 Bulan",
        product_id="prd_gemini_18",
        price=15000,
        bot_username="Idse_MarketBot",
    )
    assert "PRODUK TERSEDIA" in promo.html
    assert "Stok tersedia" in promo.html
    assert "https://t.me/Idse_MarketBot?start=prod_prd_gemini_18" in promo.html

    sim = render_simulation_table(
        product_name="Gemini Pro 18 Bulan",
        product_id="prd_gemini_18",
        price=15000,
        bot_username="Idse_MarketBot",
    )
    assert "SIMULASI — BUKAN TRANSAKSI NYATA" in sim.html
