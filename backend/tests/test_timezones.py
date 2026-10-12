from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.utils.timezones import format_local, local_range_to_utc, utc_to_local, utc_to_local_date

IST = ZoneInfo("Asia/Kolkata")  # UTC+5:30


def test_local_day_maps_to_the_right_utc_window():
    start, end = local_range_to_utc(date(2026, 10, 12), date(2026, 10, 12), IST)
    assert start == datetime(2026, 10, 11, 18, 30)
    assert end == datetime(2026, 10, 12, 18, 30)


def test_late_night_ist_payment_belongs_to_the_next_utc_day_but_the_right_local_day():
    paid_utc = datetime(2026, 10, 12, 19, 0)         # 12 Oct 19:00 UTC = 13 Oct 00:30 IST
    assert utc_to_local_date(paid_utc, IST) == date(2026, 10, 13)
    start, end = local_range_to_utc(date(2026, 10, 13), date(2026, 10, 13), IST)
    assert start <= paid_utc < end


def test_range_of_several_days_and_formatting():
    start, end = local_range_to_utc(date(2026, 10, 1), date(2026, 10, 31), IST)
    assert start == datetime(2026, 9, 30, 18, 30) and end == datetime(2026, 10, 31, 18, 30)
    assert format_local(datetime(2026, 10, 12, 10, 15), IST) == "12 Oct 2026, 03:45 PM"
    assert utc_to_local(datetime(2026, 1, 1, 0, 0), IST).hour == 5
