"""Conversions between the database's UTC times and the gym's local time (stdlib only).

The database stores naive UTC datetimes. People think in local dates ("today's
collection"), so every report must convert before grouping.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def local_range_to_utc(start: date, end: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Local dates start..end (both included) -> [start_utc, end_utc) as naive UTC datetimes."""
    start_utc = datetime.combine(start, time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def utc_to_local(value: datetime, tz: ZoneInfo) -> datetime:
    return value.replace(tzinfo=timezone.utc).astimezone(tz)


def utc_to_local_date(value: datetime, tz: ZoneInfo) -> date:
    return utc_to_local(value, tz).date()


def format_local(value: datetime, tz: ZoneInfo, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    return utc_to_local(value, tz).strftime(fmt)
