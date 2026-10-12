from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services.attendance_rules import (
    average_minutes, build_series, evaluate_access, is_stale, peak_of, period_range, visit_minutes,
)
from app.utils.timezones import to_utc_naive

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 6, 15)


def membership(start, end, invoices=(), status="active", id=1):
    return SimpleNamespace(id=id, status=status, start_date=start, end_date=end,
                           invoices=[SimpleNamespace(status=s) for s in invoices])


def access(memberships, member_status="active", grace=0, allow_unpaid=False):
    return evaluate_access(member_status, memberships, TODAY, grace, allow_unpaid)


# ---------- periods ----------
def test_day_week_month_ranges():
    assert period_range("day", date(2026, 3, 12)) == (date(2026, 3, 12), date(2026, 3, 12))
    assert period_range("week", date(2026, 3, 12)) == (date(2026, 3, 9), date(2026, 3, 15))   # Mon..Sun
    assert period_range("week", date(2026, 3, 9)) == (date(2026, 3, 9), date(2026, 3, 15))    # a Monday
    assert period_range("week", date(2026, 3, 15)) == (date(2026, 3, 9), date(2026, 3, 15))   # a Sunday
    assert period_range("month", date(2026, 3, 31)) == (date(2026, 3, 1), date(2026, 3, 31))
    assert period_range("month", date(2026, 12, 5)) == (date(2026, 12, 1), date(2026, 12, 31))
    assert period_range("month", date(2028, 2, 10)) == (date(2028, 2, 1), date(2028, 2, 29))  # leap year


def test_week_can_cross_a_month_and_year():
    assert period_range("week", date(2026, 12, 31)) == (date(2026, 12, 28), date(2027, 1, 3))


# ---------- visit length ----------
def test_visit_minutes_and_stale():
    start = datetime(2026, 6, 15, 10, 0)
    assert visit_minutes(start, datetime(2026, 6, 15, 11, 30, 59)) == 90
    assert visit_minutes(start, start) == 0
    assert visit_minutes(start, start - timedelta(minutes=5)) == 0       # never negative
    assert is_stale(start, start + timedelta(hours=8), 8) is True
    assert is_stale(start, start + timedelta(hours=7, minutes=59), 8) is False


# ---------- access rules ----------
def test_paid_active_membership_is_allowed():
    decision = access([membership(TODAY - timedelta(days=5), TODAY + timedelta(days=25), ["paid"])])
    assert decision.allowed and decision.code == "ok" and decision.expires_on == TODAY + timedelta(days=25)


def test_last_day_still_counts_and_next_day_does_not():
    assert access([membership(TODAY - timedelta(days=29), TODAY, ["paid"])]).allowed
    expired = access([membership(TODAY - timedelta(days=30), TODAY - timedelta(days=1), ["paid"])])
    assert not expired.allowed and expired.code == "expired" and "expired on" in expired.message


def test_grace_period_lets_recent_expiry_in():
    ms = [membership(TODAY - timedelta(days=32), TODAY - timedelta(days=2), ["paid"])]
    assert not access(ms, grace=1).allowed
    decision = access(ms, grace=3)
    assert decision.allowed and decision.code == "grace" and decision.in_grace is True


def test_no_membership_cancelled_and_upcoming():
    assert access([]).code == "no_membership"
    cancelled = membership(TODAY - timedelta(days=1), TODAY + timedelta(days=29), ["paid"], status="cancelled")
    assert access([cancelled]).code == "no_membership"
    upcoming = access([membership(TODAY + timedelta(days=3), TODAY + timedelta(days=32), ["paid"])])
    assert upcoming.code == "not_started" and not upcoming.allowed


def test_inactive_member_is_always_denied():
    ms = [membership(TODAY - timedelta(days=5), TODAY + timedelta(days=25), ["paid"])]
    assert access(ms, member_status="inactive").code == "member_inactive"


def test_unpaid_rules():
    for statuses in (["pending"], ["partial"], ["paid", "pending"]):
        ms = [membership(TODAY - timedelta(days=1), TODAY + timedelta(days=29), statuses)]
        assert access(ms).code == "unpaid"
        assert access(ms, allow_unpaid=True).allowed
    free = [membership(TODAY - timedelta(days=1), TODAY + timedelta(days=29), [])]   # free plan: no invoice
    assert access(free).allowed
    cancelled_bill = [membership(TODAY - timedelta(days=1), TODAY + timedelta(days=29), ["cancelled"])]
    assert access(cancelled_bill).allowed


def test_unpaid_renewal_does_not_block_while_current_period_is_paid():
    current = membership(TODAY - timedelta(days=20), TODAY + timedelta(days=9), ["paid"], id=1)
    renewal = membership(TODAY + timedelta(days=10), TODAY + timedelta(days=39), ["pending"], id=2)
    assert access([current, renewal]).allowed
    later = evaluate_access("active", [current, renewal], TODAY + timedelta(days=12), 0, False)
    assert later.code == "unpaid"            # now the renewal is the current period and is unpaid


# ---------- report helpers ----------
def test_average_minutes():
    assert average_minutes([60, 30, 45]) == 45.0
    assert average_minutes([10, 11]) == 10.5
    assert average_minutes([]) is None


def test_hourly_series_uses_local_hours():
    rows = [(1, datetime(2026, 3, 10, 1, 0)),     # 06:30 IST
            (2, datetime(2026, 3, 10, 1, 15)),    # 06:45 IST
            (1, datetime(2026, 3, 10, 12, 40))]   # 18:10 IST
    series = build_series(rows, "day", date(2026, 3, 10), date(2026, 3, 10), IST)
    assert len(series) == 24
    by = {p["label"]: p for p in series}
    assert by["06"] == {"label": "06", "visits": 2, "unique_members": 2}
    assert by["18"]["visits"] == 1 and by["00"]["visits"] == 0
    assert peak_of(series) == ("06", 2)


def test_late_night_visit_counts_on_the_next_local_day():
    rows = [(1, datetime(2026, 3, 10, 19, 0))]   # 00:30 IST on the 11th
    series = build_series(rows, "week", date(2026, 3, 9), date(2026, 3, 15), IST)
    assert [p["label"] for p in series][0] == "2026-03-09" and len(series) == 7
    assert {p["label"]: p["visits"] for p in series}["2026-03-11"] == 1


def test_daily_series_counts_unique_members_once():
    rows = [(1, datetime(2026, 3, 10, 2, 0)), (1, datetime(2026, 3, 10, 9, 0)), (2, datetime(2026, 3, 10, 3, 0))]
    day = {p["label"]: p for p in build_series(rows, "month", date(2026, 3, 1), date(2026, 3, 31), IST)}["2026-03-10"]
    assert day["visits"] == 3 and day["unique_members"] == 2
    assert peak_of(build_series([], "day", date(2026, 3, 10), date(2026, 3, 10), IST)) == (None, 0)


def test_staff_typed_times_are_read_as_gym_local_unless_they_carry_an_offset():
    assert to_utc_naive(datetime(2026, 3, 10, 10, 0), IST) == datetime(2026, 3, 10, 4, 30)
    aware_utc = datetime(2026, 3, 10, 10, 0, tzinfo=ZoneInfo("UTC"))
    assert to_utc_naive(aware_utc, IST) == datetime(2026, 3, 10, 10, 0)
    aware_ist = datetime(2026, 3, 10, 10, 0, tzinfo=IST)
    assert to_utc_naive(aware_ist, ZoneInfo("UTC")) == datetime(2026, 3, 10, 4, 30)
