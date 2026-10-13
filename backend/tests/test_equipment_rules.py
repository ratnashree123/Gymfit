from datetime import date, timedelta
from decimal import Decimal

from app.services.equipment_rules import (
    UNSET, can_transition, inventory_value, maintenance_urgency, next_due_after_completion,
    next_equipment_status,
)

TODAY = date(2026, 6, 15)


def d(days):
    return TODAY + timedelta(days=days)


def urgency(status="available", condition="good", dues=(), alert=7):
    return maintenance_urgency(status, condition, list(dues), TODAY, alert)


# ---------- job status machine ----------
def test_job_transitions():
    assert can_transition("scheduled", "in_progress") and can_transition("scheduled", "completed")
    assert can_transition("scheduled", "cancelled") and can_transition("in_progress", "completed")
    assert can_transition("in_progress", "cancelled")
    assert not can_transition("in_progress", "scheduled") and not can_transition("scheduled", "scheduled")
    for finished in ("completed", "cancelled"):
        for new in ("scheduled", "in_progress", "completed", "cancelled"):
            assert not can_transition(finished, new)          # history is locked
    assert not can_transition("scheduled", "banana")


# ---------- equipment status follows the jobs ----------
def test_starting_a_job_puts_the_item_under_maintenance():
    assert next_equipment_status("routine", "scheduled", "in_progress", False, "available") == "under_maintenance"
    assert next_equipment_status("repair", "scheduled", "in_progress", False, "damaged") == "under_maintenance"


def test_completing_a_job_makes_the_item_available_unless_another_job_is_running():
    assert next_equipment_status("repair", "in_progress", "completed", False, "under_maintenance") == "available"
    assert next_equipment_status("routine", "scheduled", "completed", False, "available") == "available"
    assert next_equipment_status("repair", "in_progress", "completed", True, "under_maintenance") == "under_maintenance"


def test_a_routine_service_does_not_repair_a_broken_item_but_a_repair_does():
    assert next_equipment_status("routine", "scheduled", "completed", False, "damaged") == "damaged"
    assert next_equipment_status("inspection", "scheduled", "completed", False, "damaged") == "damaged"
    assert next_equipment_status("repair", "scheduled", "completed", False, "damaged") == "available"


def test_cancelling_half_done_work():
    assert next_equipment_status("repair", "in_progress", "cancelled", False, "under_maintenance") == "damaged"
    assert next_equipment_status("routine", "in_progress", "cancelled", False, "under_maintenance") == "available"
    assert next_equipment_status("inspection", "in_progress", "cancelled", False, "under_maintenance") == "available"
    assert next_equipment_status("repair", "in_progress", "cancelled", True, "under_maintenance") == "under_maintenance"


def test_cancelling_a_job_that_never_started_changes_nothing():
    for current in ("available", "damaged", "under_maintenance"):
        assert next_equipment_status("repair", "scheduled", "cancelled", False, current) == current


# ---------- next maintenance date ----------
def test_a_date_typed_by_the_admin_always_wins():
    assert next_due_after_completion(d(-5), TODAY, "routine", provided=d(90)) == d(90)
    assert next_due_after_completion(d(30), TODAY, "routine", provided=None) is None      # explicit clear
    assert next_due_after_completion(d(-5), TODAY, "repair", provided=d(10)) == d(10)


def test_a_satisfied_due_date_is_cleared_but_a_future_one_is_kept():
    assert next_due_after_completion(d(-3), TODAY, "routine", UNSET) is None
    assert next_due_after_completion(TODAY, TODAY, "inspection", UNSET) is None
    assert next_due_after_completion(d(20), TODAY, "routine", UNSET) == d(20)
    assert next_due_after_completion(None, TODAY, "routine", UNSET) is None


def test_a_repair_never_touches_the_routine_schedule():
    assert next_due_after_completion(d(-3), TODAY, "repair", UNSET) == d(-3)
    assert next_due_after_completion(d(20), TODAY, "repair", UNSET) == d(20)


# ---------- urgency ----------
def test_damaged_is_always_urgent_even_with_a_future_date():
    result = urgency("damaged", dues=[d(30)])
    assert (result.level, result.code) == ("urgent", "damaged")


def test_under_maintenance_is_being_handled_so_it_is_not_flagged():
    assert urgency("under_maintenance", dues=[d(-10)]).level == "ok"
    assert urgency("under_maintenance", condition="poor").code == "under_maintenance"


def test_overdue_is_urgent_and_counts_days():
    one = urgency(dues=[d(-1)])
    assert (one.level, one.code, one.message) == ("urgent", "overdue", "Maintenance overdue by 1 day")
    assert urgency(dues=[d(-10), d(5)]).message == "Maintenance overdue by 10 days"      # the earliest date counts


def test_due_today_and_due_soon_window():
    assert urgency(dues=[TODAY]).message == "Maintenance due today"
    assert urgency(dues=[d(1)]).message == "Maintenance due in 1 day"
    assert urgency(dues=[d(7)]).code == "due_soon"
    assert urgency(dues=[d(8)]).level == "ok"
    assert urgency(dues=[d(8)], alert=10).level == "soon"
    assert urgency(dues=[d(3)], alert=0).level == "ok"


def test_poor_condition_is_flagged_soon_but_overdue_wins():
    assert urgency(condition="poor").code == "poor_condition"
    assert urgency(condition="poor", dues=[d(-2)]).code == "overdue"
    assert urgency(condition="fair").level == "ok" and urgency(condition="new").level == "ok"


def test_no_dates_means_ok():
    assert urgency().level == "ok" and urgency().due_date is None


# ---------- money ----------
def test_inventory_value_is_price_times_quantity():
    assert inventory_value(Decimal("1500.50"), 4) == Decimal("6002.00")
    assert inventory_value(Decimal("0.10"), 3) == Decimal("0.30")
    assert inventory_value(None, 5) == Decimal("0.00")
