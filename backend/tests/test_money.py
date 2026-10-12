from decimal import Decimal

import pytest

from app.services.money import (
    MoneyError, calculate_invoice, discount_exceeds_percent, invoice_status, quantize,
)

D = Decimal


def test_plain_invoice_has_no_discount_or_tax():
    a = calculate_invoice(D("1500"))
    assert (a.subtotal, a.discount, a.tax, a.total) == (D("1500.00"), D("0.00"), D("0.00"), D("1500.00"))


def test_percent_discount_then_tax_on_discounted_price():
    a = calculate_invoice(D("1000"), discount_percent=D("10"), tax_percent=D("18"))
    assert a.discount == D("100.00")
    assert a.tax == D("162.00")      # 18% of 900, not of 1000
    assert a.total == D("1062.00")


def test_fixed_discount():
    a = calculate_invoice(D("1500"), discount_amount=D("250.50"), tax_percent=D("5"))
    assert a.discount == D("250.50") and a.tax == D("62.48") and a.total == D("1311.98")


def test_rounding_is_half_up_to_two_places():
    assert quantize("2.675") == D("2.68")
    assert quantize("0.005") == D("0.01")
    assert calculate_invoice(D("99.99"), tax_percent=D("5.5")).tax == D("5.50")


def test_bad_discounts_and_tax_are_rejected():
    for kwargs in (
        {"discount_amount": D("10"), "discount_percent": D("5")},
        {"discount_amount": D("2000")},
        {"discount_percent": D("101")},
        {"discount_percent": D("-1")},
        {"discount_amount": D("-1")},
        {"tax_percent": D("-1")},
        {"tax_percent": D("101")},
    ):
        with pytest.raises(MoneyError):
            calculate_invoice(D("1500"), **kwargs)


def test_full_discount_gives_zero_total():
    assert calculate_invoice(D("500"), discount_percent=D("100"), tax_percent=D("18")).total == D("0.00")


def test_no_float_surprises():
    assert calculate_invoice(D("0.10") + D("0.20")).total == D("0.30")


def test_receptionist_discount_cap():
    assert discount_exceeds_percent(D("1000"), D("100.01"), D("10")) is True
    assert discount_exceeds_percent(D("1000"), D("100.00"), D("10")) is False


def test_invoice_status_comes_only_from_payments():
    total = D("1000")
    assert invoice_status(total, D("0")) == "pending"
    assert invoice_status(total, D("0.01")) == "partial"
    assert invoice_status(total, D("999.99")) == "partial"
    assert invoice_status(total, D("1000")) == "paid"
    assert invoice_status(total, D("0"), cancelled=True) == "cancelled"
    assert invoice_status(D("0"), D("0")) == "pending"   # a zero invoice is never auto-'paid'
