"""Report helpers (no database): revenue buckets and CSV safety."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

PERIODS = ("daily", "monthly", "yearly")


def bucket_key(day: date, period: str) -> str:
    if period == "daily":
        return day.isoformat()
    if period == "monthly":
        return f"{day.year:04d}-{day.month:02d}"
    if period == "yearly":
        return f"{day.year:04d}"
    raise ValueError("period must be daily, monthly or yearly")


def default_range(period: str, today: date) -> tuple[date, date]:
    if period == "daily":
        return today - timedelta(days=29), today
    if period == "monthly":
        year, month = today.year, today.month - 11
        if month <= 0:
            month += 12
            year -= 1
        return date(year, month, 1), today
    if period == "yearly":
        return date(today.year - 4, 1, 1), today
    raise ValueError("period must be daily, monthly or yearly")


def validate_range(period: str, start: date, end: date) -> None:
    if period not in PERIODS:
        raise ValueError("period must be daily, monthly or yearly")
    if end < start:
        raise ValueError("'to' must not be before 'from'")
    if period == "daily" and (end - start).days + 1 > 366:
        raise ValueError("A daily report can cover at most 366 days")
    months = (end.year - start.year) * 12 + end.month - start.month + 1
    if period == "monthly" and months > 120:
        raise ValueError("A monthly report can cover at most 120 months")
    if period == "yearly" and end.year - start.year + 1 > 20:
        raise ValueError("A yearly report can cover at most 20 years")


def bucket_keys(start: date, end: date, period: str) -> list[str]:
    """Every bucket in the range, so charts have no gaps (empty days show as 0)."""
    validate_range(period, start, end)
    keys: list[str] = []
    if period == "daily":
        day = start
        while day <= end:
            keys.append(day.isoformat())
            day += timedelta(days=1)
    elif period == "monthly":
        year, month = start.year, start.month
        while (year, month) <= (end.year, end.month):
            keys.append(f"{year:04d}-{month:02d}")
            month += 1
            if month == 13:
                year, month = year + 1, 1
    else:
        keys = [f"{year:04d}" for year in range(start.year, end.year + 1)]
    return keys


def build_series(rows: Iterable[tuple[date, Decimal]], period: str, start: date, end: date) -> list[dict]:
    """rows = (local_date, amount) for each payment. Returns [{label, amount, count}, ...]."""
    series = {key: {"label": key, "amount": Decimal("0.00"), "count": 0}
              for key in bucket_keys(start, end, period)}
    for day, amount in rows:
        bucket = series.get(bucket_key(day, period))
        if bucket is not None:
            bucket["amount"] += Decimal(amount)
            bucket["count"] += 1
    return list(series.values())


_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    """Stops 'CSV injection': Excel would run a cell that starts with = + - @ as a formula,
    so such text gets a leading apostrophe and is shown as plain text."""
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_STARTS):
        return "'" + text
    return text
