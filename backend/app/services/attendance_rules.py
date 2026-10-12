"""Attendance rules (no database): who may enter, visit length, report buckets."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

from app.utils.timezones import utc_to_local

PERIODS = ("day", "week", "month")


# ------------------------------------------------------------------ periods
def period_range(period: str, ref: date) -> tuple[date, date]:
    """day = that date. week = Monday..Sunday containing it. month = the calendar month."""
    if period == "day":
        return ref, ref
    if period == "week":
        start = ref - timedelta(days=ref.weekday())
        return start, start + timedelta(days=6)
    if period == "month":
        start = ref.replace(day=1)
        first_of_next = (start + timedelta(days=32)).replace(day=1)
        return start, first_of_next - timedelta(days=1)
    raise ValueError("period must be day, week or month")


# ------------------------------------------------------------------ visits
def visit_minutes(start: datetime, end: datetime) -> int:
    """Whole minutes between check-in and check-out (never negative)."""
    return max(0, int((end - start).total_seconds() // 60))


def is_stale(check_in: datetime, now: datetime, max_hours: int) -> bool:
    """An open visit older than max_hours means somebody forgot to check out."""
    return now - check_in >= timedelta(hours=max_hours)


# ------------------------------------------------------------------ access
@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    code: str  # ok | grace | member_inactive | no_membership | not_started | expired | unpaid
    message: str
    expires_on: Optional[date] = None
    in_grace: bool = False


def evaluate_access(member_status: str, memberships: Sequence, today: date, grace_days: int,
                    allow_unpaid: bool) -> AccessDecision:
    """May this member enter today?

    Each membership needs: id, status, start_date, end_date, invoices (each with .status).
    """
    if member_status != "active":
        return AccessDecision(False, "member_inactive", "This member is inactive. Reactivate the member first")

    live = [m for m in memberships if m.status != "cancelled"]
    if not live:
        return AccessDecision(False, "no_membership", "This member has no membership. Assign a plan first")

    grace = timedelta(days=grace_days)
    covering = [m for m in live if m.start_date <= today <= m.end_date + grace]
    if not covering:
        upcoming = [m for m in live if m.start_date > today]
        if upcoming:
            first = min(upcoming, key=lambda m: (m.start_date, m.id))
            return AccessDecision(False, "not_started",
                                  f"The membership starts on {first.start_date:%d %b %Y}", first.end_date)
        last = max(live, key=lambda m: (m.end_date, m.id))
        return AccessDecision(False, "expired",
                              f"The membership expired on {last.end_date:%d %b %Y}", last.end_date)

    current = max(covering, key=lambda m: (m.end_date, m.id))
    in_grace = current.end_date < today

    if not allow_unpaid and any(i.status in ("pending", "partial") for i in current.invoices):
        return AccessDecision(False, "unpaid", "The membership fee is not fully paid. Record the payment first",
                              current.end_date)

    if in_grace:
        return AccessDecision(True, "grace",
                              f"Membership expired on {current.end_date:%d %b %Y}; "
                              f"still inside the {grace_days}-day grace period",
                              current.end_date, True)
    return AccessDecision(True, "ok", "Allowed", current.end_date)


# ------------------------------------------------------------------ report
def average_minutes(durations: Iterable[int]) -> Optional[float]:
    values = list(durations)
    return round(sum(values) / len(values), 1) if values else None


def build_series(rows: Iterable[tuple[int, datetime]], period: str, start: date, end: date,
                 tz: ZoneInfo) -> list[dict]:
    """rows = (member_id, check_in_at in UTC). 'day' gives 24 hourly buckets,
    'week' and 'month' give one bucket per local date. Empty buckets show as 0."""
    if period == "day":
        labels = [f"{hour:02d}" for hour in range(24)]
    else:
        labels, day = [], start
        while day <= end:
            labels.append(day.isoformat())
            day += timedelta(days=1)

    buckets = {label: {"visits": 0, "members": set()} for label in labels}
    for member_id, checked_in in rows:
        local = utc_to_local(checked_in, tz)
        label = f"{local.hour:02d}" if period == "day" else local.date().isoformat()
        bucket = buckets.get(label)
        if bucket is not None:
            bucket["visits"] += 1
            bucket["members"].add(member_id)
    return [{"label": label, "visits": b["visits"], "unique_members": len(b["members"])}
            for label, b in buckets.items()]


def peak_of(series: Sequence[dict]) -> tuple[Optional[str], int]:
    """The busiest bucket (earliest wins a tie), or (None, 0) when there were no visits."""
    best = max(series, key=lambda p: p["visits"], default=None)
    if best is None or best["visits"] == 0:
        return None, 0
    return best["label"], best["visits"]
