"""SQL rules for 'which members are active / expiring / expired ...'.

One place, used by the member list, the membership report, the dashboard and the notifications,
so every screen always shows the same numbers.
"""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, exists, func, not_, select
from sqlalchemy.orm import Session

from app.models import Member, Membership

STATUS_KEYS = ("active", "upcoming", "expired", "no_membership", "inactive")


def has_any():
    return exists().where(Membership.member_id == Member.id, Membership.status != "cancelled")


def covers_today(today: date):
    return exists().where(
        Membership.member_id == Member.id, Membership.status != "cancelled",
        Membership.start_date <= today, Membership.end_date >= today)


def starts_later(today: date):
    return exists().where(
        Membership.member_id == Member.id, Membership.status != "cancelled",
        Membership.start_date > today)


def latest_end():
    """The latest end date of the member's memberships (NULL when they have none)."""
    return (select(func.max(Membership.end_date))
            .where(Membership.member_id == Member.id, Membership.status != "cancelled")
            .scalar_subquery())


def latest_plan_id():
    """The plan of the member's latest membership."""
    return (select(Membership.plan_id)
            .where(Membership.member_id == Member.id, Membership.status != "cancelled")
            .order_by(Membership.end_date.desc(), Membership.id.desc()).limit(1).scalar_subquery())


def status_conditions(status: Optional[str], today: date) -> list:
    """Conditions for active | upcoming | expired | no_membership | inactive. None gives no condition."""
    active_member = Member.status == "active"
    if status == "inactive":
        return [Member.status == "inactive"]
    if status == "active":
        return [active_member, covers_today(today)]
    if status == "upcoming":
        return [active_member, not_(covers_today(today)), starts_later(today)]
    if status == "expired":
        return [active_member, not_(covers_today(today)), not_(starts_later(today)), has_any()]
    if status == "no_membership":
        return [active_member, not_(has_any())]
    return []


def expiring_conditions(today: date, alert_days: int) -> list:
    """Active members whose membership ends within the next alert_days days."""
    ends = latest_end()
    return [Member.status == "active", covers_today(today), ends >= today,
            ends <= today + timedelta(days=alert_days)]


def status_counts(db: Session, today: date, alert_days: int, base: list) -> dict:
    """How many members are in each state. `base` narrows the group (for example one trainer's members)."""

    def count(extra: list) -> int:
        return db.scalar(select(func.count(Member.id)).where(and_(*base, *extra))) or 0

    counts = {key: count(status_conditions(key, today)) for key in STATUS_KEYS}
    counts["expiring_soon"] = count(expiring_conditions(today, alert_days))
    counts["total"] = count([])
    return counts
