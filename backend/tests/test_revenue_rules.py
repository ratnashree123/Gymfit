from datetime import date
from decimal import Decimal

import pytest

from app.services.revenue_rules import (
    bucket_key, bucket_keys, build_series, csv_safe, default_range, validate_range,
)

D = Decimal


def test_bucket_keys():
    d = date(2026, 3, 7)
    assert bucket_key(d, "daily") == "2026-03-07"
    assert bucket_key(d, "monthly") == "2026-03"
    assert bucket_key(d, "yearly") == "2026"


def test_default_ranges():
    today = date(2026, 3, 15)
    assert default_range("daily", today) == (date(2026, 2, 14), today)
    assert default_range("monthly", today) == (date(2025, 4, 1), today)   # 12 months incl. this one
    assert default_range("monthly", date(2026, 12, 5)) == (date(2026, 1, 1), date(2026, 12, 5))
    assert default_range("yearly", today) == (date(2022, 1, 1), today)


def test_buckets_have_no_gaps_across_month_and_year_boundaries():
    assert bucket_keys(date(2026, 1, 30), date(2026, 2, 2), "daily") == [
        "2026-01-30", "2026-01-31", "2026-02-01", "2026-02-02"]
    assert bucket_keys(date(2025, 11, 20), date(2026, 2, 1), "monthly") == [
        "2025-11", "2025-12", "2026-01", "2026-02"]
    assert bucket_keys(date(2024, 5, 1), date(2026, 1, 1), "yearly") == ["2024", "2025", "2026"]


def test_series_sums_and_zero_fills():
    rows = [(date(2026, 3, 1), D("500.00")), (date(2026, 3, 1), D("250.50")), (date(2026, 3, 3), D("100"))]
    series = build_series(rows, "daily", date(2026, 3, 1), date(2026, 3, 4))
    assert [(s["label"], s["amount"], s["count"]) for s in series] == [
        ("2026-03-01", D("750.50"), 2), ("2026-03-02", D("0.00"), 0),
        ("2026-03-03", D("100.00"), 1), ("2026-03-04", D("0.00"), 0)]
    monthly = build_series(rows, "monthly", date(2026, 2, 1), date(2026, 3, 31))
    assert [(s["label"], s["amount"]) for s in monthly] == [("2026-02", D("0.00")), ("2026-03", D("850.50"))]


def test_range_validation():
    with pytest.raises(ValueError):
        validate_range("daily", date(2026, 3, 2), date(2026, 3, 1))
    with pytest.raises(ValueError):
        validate_range("daily", date(2025, 1, 1), date(2026, 3, 1))
    with pytest.raises(ValueError):
        validate_range("monthly", date(2010, 1, 1), date(2026, 1, 1))
    with pytest.raises(ValueError):
        validate_range("yearly", date(2000, 1, 1), date(2026, 1, 1))
    with pytest.raises(ValueError):
        validate_range("weekly", date(2026, 1, 1), date(2026, 1, 2))
    validate_range("daily", date(2025, 3, 1), date(2026, 2, 28))  # exactly 365 days: fine


def test_csv_injection_is_neutralised():
    assert csv_safe("=HYPERLINK(\"http://evil\")") == "'=HYPERLINK(\"http://evil\")"
    assert csv_safe("+91 98765") == "'+91 98765"
    assert csv_safe("-5") == "'-5"
    assert csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert csv_safe("\t=1") == "'\t=1"
    assert csv_safe("Anita Sharma") == "Anita Sharma"
    assert csv_safe(None) == ""
    assert csv_safe(D("1500.00")) == "1500.00"
