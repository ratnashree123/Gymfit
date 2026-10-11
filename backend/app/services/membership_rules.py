"""Pure membership rules (no database). Easy to test and easy to explain.

A membership is valid on its start_date AND its end_date (both included).
Example: a 30-day plan starting 1 Jan ends on 30 Jan.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional, Sequence


def compute_end_date(start: date, duration_days: int) -> date:
    if duration_days < 1:
        raise ValueError("duration_days must be at least 1")
    return start + timedelta(days=duration_days - 1)


def membership_state(start: date, end: date, cancelled: bool, today: date) -> str:
    """'cancelled', 'upcoming', 'active' or 'expired' for ONE membership row."""
    if cancelled:
        return "cancelled"
    if start > today:
        return "upcoming"
    if end >= today:
        return "active"
    return "expired"


@dataclass
class MembershipSummary:
    membership_status: str  # active | upcoming | expired | no_membership | inactive
    plan_name: Optional[str]
    expires_on: Optional[date]
    days_left: Optional[int]
    expiring_soon: bool
    current: Any  # the membership row to show (or None)


def summarize(memberships: Sequence, member_status: str, today: date, alert_days: int) -> MembershipSummary:
    """Work out a member's overall membership status from all their membership rows.

    Each row needs: id, status, start_date, end_date, plan.name
    """
    live = [m for m in memberships if m.status != "cancelled"]

    if not live:
        status = "inactive" if member_status == "inactive" else "no_membership"
        return MembershipSummary(status, None, None, None, False, None)

    covering_today = [m for m in live if m.start_date <= today <= m.end_date]
    latest = max(live, key=lambda m: (m.end_date, m.id))
    shown = max(covering_today, key=lambda m: (m.end_date, m.id)) if covering_today else latest

    if member_status == "inactive":
        status = "inactive"
    elif covering_today:
        status = "active"
    elif any(m.start_date > today for m in live):
        status = "upcoming"
    else:
        status = "expired"

    days_left = (latest.end_date - today).days
    expiring_soon = status == "active" and 0 <= days_left <= alert_days
    return MembershipSummary(status, shown.plan.name, latest.end_date, days_left, expiring_soon, shown)
