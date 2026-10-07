import pytest
from fastapi import HTTPException

from admin_routes import DiscountBody, _validate_discount


def test_discount_rejects_non_finite_value():
    body = DiscountBody(name="Promo", mode="fixed", value=float("nan"), fixed_currency="IDR")
    with pytest.raises(HTTPException) as error:
        _validate_discount(body)
    assert error.value.status_code == 400


def test_discount_rejects_invalid_date_and_reversed_range():
    invalid = DiscountBody(name="Promo", value=10, starts_at="not-a-date")
    with pytest.raises(HTTPException) as error:
        _validate_discount(invalid)
    assert "starts_at" in error.value.detail

    reversed_range = DiscountBody(
        name="Promo", value=10,
        starts_at="2026-09-28T00:00:00+07:00",
        ends_at="2026-09-27T23:00:00+07:00",
    )
    with pytest.raises(HTTPException) as error:
        _validate_discount(reversed_range)
    assert "setelah" in error.value.detail


def test_discount_accepts_valid_timezone_aware_range():
    body = DiscountBody(
        name="  Promo  ", mode="percent", value=10,
        starts_at="2026-09-27T00:00:00+07:00",
        ends_at="2026-09-28T00:00:00+07:00",
    )
    _validate_discount(body)
