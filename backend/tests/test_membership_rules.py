"""Pure-logic tests (no database, no web server)."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.services.membership_rules import compute_end_date, membership_state, summarize

TODAY = date(2026, 6, 15)


def ms(start, end, status="active", plan="Monthly", id=1):
    return SimpleNamespace(id=id, start_date=start, end_date=end, status=status,
                           plan=SimpleNamespace(name=plan))


def test_end_date_counts_the_start_day():
    assert compute_end_date(date(2026, 1, 1), 30) == date(2026, 1, 30)
    assert compute_end_date(date(2026, 1, 1), 1) == date(2026, 1, 1)
    assert compute_end_date(date(2026, 1, 1), 365) == date(2026, 12, 31)


def test_end_date_crosses_month_and_leap_year():
    assert compute_end_date(date(2028, 2, 1), 29) == date(2028, 2, 29)
    assert compute_end_date(date(2026, 1, 31), 30) == date(2026, 3, 1)


def test_end_date_rejects_zero_days():
    with pytest.raises(ValueError):
        compute_end_date(date(2026, 1, 1), 0)


def test_membership_state_for_one_row():
    assert membership_state(TODAY, TODAY, False, TODAY) == "active"            # last day still counts
    assert membership_state(TODAY - timedelta(days=30), TODAY - timedelta(days=1), False, TODAY) == "expired"
    assert membership_state(TODAY + timedelta(days=1), TODAY + timedelta(days=30), False, TODAY) == "upcoming"
    assert membership_state(TODAY, TODAY + timedelta(days=5), True, TODAY) == "cancelled"


def test_summary_without_memberships():
    assert summarize([], "active", TODAY, 7).membership_status == "no_membership"
    assert summarize([], "inactive", TODAY, 7).membership_status == "inactive"


def test_summary_active_and_days_left():
    s = summarize([ms(TODAY - timedelta(days=10), TODAY + timedelta(days=20))], "active", TODAY, 7)
    assert s.membership_status == "active"
    assert s.days_left == 20
    assert s.expiring_soon is False
    assert s.plan_name == "Monthly"


def test_summary_expiring_soon_window():
    for days_left, expected in [(0, True), (7, True), (8, False)]:
        s = summarize([ms(TODAY - timedelta(days=10), TODAY + timedelta(days=days_left))], "active", TODAY, 7)
        assert s.expiring_soon is expected, days_left


def test_summary_expired_and_upcoming():
    expired = summarize([ms(TODAY - timedelta(days=60), TODAY - timedelta(days=31))], "active", TODAY, 7)
    assert expired.membership_status == "expired"
    assert expired.days_left == -31 and expired.expiring_soon is False

    upcoming = summarize([ms(TODAY + timedelta(days=5), TODAY + timedelta(days=34))], "active", TODAY, 7)
    assert upcoming.membership_status == "upcoming"


def test_summary_renewed_in_advance_is_not_expiring_soon():
    current = ms(TODAY - timedelta(days=25), TODAY + timedelta(days=4), id=1)
    renewal = ms(TODAY + timedelta(days=5), TODAY + timedelta(days=34), id=2)
    s = summarize([current, renewal], "active", TODAY, 7)
    assert s.membership_status == "active"
    assert s.expires_on == TODAY + timedelta(days=34)
    assert s.expiring_soon is False


def test_summary_ignores_cancelled_and_respects_inactive_members():
    cancelled = ms(TODAY - timedelta(days=1), TODAY + timedelta(days=29), status="cancelled")
    assert summarize([cancelled], "active", TODAY, 7).membership_status == "no_membership"
    live = ms(TODAY - timedelta(days=1), TODAY + timedelta(days=29))
    assert summarize([live], "inactive", TODAY, 7).membership_status == "inactive"
