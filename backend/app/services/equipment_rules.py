"""Equipment and maintenance rules (no database).

Equipment status is ONLY one of: available, damaged, under_maintenance.
Maintenance job status is ONLY one of: scheduled, in_progress, completed, cancelled.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Sequence


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()  # "the caller did not send this field at all"

# A finished or cancelled job is history and can never change again.
JOB_TRANSITIONS = {
    "scheduled": {"in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def can_transition(old: str, new: str) -> bool:
    return new in JOB_TRANSITIONS.get(old, set())


def next_equipment_status(job_type: str, old_job_status: str, new_job_status: str,
                          other_in_progress: bool, current: str) -> str:
    """What the equipment's status becomes when a job changes status."""
    if new_job_status == "in_progress":
        return "under_maintenance"
    if other_in_progress:
        return "under_maintenance"            # another job is still being worked on
    if new_job_status == "completed":
        if current == "damaged" and job_type != "repair":
            return "damaged"                  # a routine service or inspection does not fix a broken item
        return "available"
    if new_job_status == "cancelled" and old_job_status == "in_progress":
        # Work was stopped half-way: a repair that never finished leaves the item broken.
        return "damaged" if job_type == "repair" else "available"
    return current


def next_due_after_completion(current_next: Optional[date], performed: date, job_type: str,
                              provided=UNSET) -> Optional[date]:
    """The equipment's next maintenance date after a job is completed.

    * a date typed by the admin always wins (even an empty one, which clears it);
    * otherwise a due date that this job has just satisfied is cleared;
    * a repair never touches the routine schedule.
    """
    if provided is not UNSET:
        return provided
    if job_type != "repair" and current_next is not None and current_next <= performed:
        return None
    return current_next


@dataclass(frozen=True)
class Urgency:
    level: str  # urgent | soon | ok
    code: str  # damaged | overdue | poor_condition | due_soon | under_maintenance | ok
    message: str
    due_date: Optional[date] = None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def maintenance_urgency(status: str, condition: str, due_dates: Sequence[date], today: date,
                        alert_days: int) -> Urgency:
    """How urgently does this item need attention? due_dates = its next planned maintenance dates."""
    if status == "damaged":
        return Urgency("urgent", "damaged", "Damaged: needs repair")
    if status == "under_maintenance":
        return Urgency("ok", "under_maintenance", "Being serviced")

    earliest = min(due_dates) if due_dates else None
    if earliest is not None and earliest < today:
        return Urgency("urgent", "overdue",
                       f"Maintenance overdue by {_plural((today - earliest).days, 'day')}", earliest)
    if condition == "poor":
        return Urgency("soon", "poor_condition", "Poor condition: consider servicing or replacing", earliest)
    if earliest is not None and earliest <= today + timedelta(days=alert_days):
        days = (earliest - today).days
        when = "today" if days == 0 else f"in {_plural(days, 'day')}"
        return Urgency("soon", "due_soon", f"Maintenance due {when}", earliest)
    return Urgency("ok", "ok", "OK", earliest)


def inventory_value(price: Optional[Decimal], quantity: int) -> Decimal:
    """purchase_price is the price of ONE item, so the value of a record is price x quantity."""
    if price is None:
        return Decimal("0.00")
    return (Decimal(price) * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
