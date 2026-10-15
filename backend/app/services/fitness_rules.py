"""Workout and progress rules (no database)."""
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional, Sequence

KNOWN_MUSCLE_GROUPS = ("Chest", "Back", "Shoulders", "Biceps", "Triceps", "Forearms", "Legs", "Glutes",
                       "Calves", "Core", "Full body", "Cardio", "Mobility", "Other")
METRICS = ("weight_kg", "height_cm", "body_fat_pct", "chest_cm", "waist_cm", "hips_cm")
MAX_EXERCISES_PER_DAY = 30


def normalize_muscle_group(value: str) -> str:
    """'  chest ' -> 'Chest'. A group that is not on the list is kept as typed (tidied)."""
    text = " ".join(value.split())
    return {g.lower(): g for g in KNOWN_MUSCLE_GROUPS}.get(text.lower(), text)


def validate_exercise_load(sets: Optional[int], reps: Optional[int],
                           duration_minutes: Optional[int]) -> Optional[str]:
    """None when the exercise is described well enough, otherwise the reason it is not."""
    if duration_minutes is not None:
        return None  # a timed exercise: running, a plank...
    if sets is not None and reps is not None:
        return None
    return "Give sets AND reps, or a duration in minutes"


def reorder_problem(current_ids: Sequence[int], requested: Sequence[int]) -> Optional[str]:
    if len(set(requested)) != len(requested):
        return "An exercise is listed twice"
    if set(requested) != set(current_ids):
        return "List every exercise of that day exactly once"
    return None


# ------------------------------------------------------------------ BMI
def calc_bmi(weight_kg, height_cm) -> Optional[Decimal]:
    """Body mass index, one decimal. None when weight or height is missing."""
    if weight_kg is None or height_cm is None or Decimal(height_cm) <= 0:
        return None
    metres = Decimal(height_cm) / 100
    return (Decimal(weight_kg) / (metres * metres)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def bmi_category(bmi: Decimal) -> str:
    """Adult ranges only. It is an indicator, not a diagnosis."""
    if bmi < Decimal("18.5"):
        return "Underweight"
    if bmi < Decimal("25"):
        return "Healthy range"
    if bmi < Decimal("30"):
        return "Overweight"
    return "Obese"


# ------------------------------------------------------------------ progress over time
def _ordered(records: Iterable) -> list:
    return sorted(records, key=lambda r: (r.recorded_on, r.id))


def build_points(records: Iterable) -> list[dict]:
    """One point per record, oldest first. BMI uses the latest height known up to that record,
    so a weigh-in without a new height measurement still gets a BMI."""
    points, known_height = [], None
    for r in _ordered(records):
        if r.height_cm is not None:
            known_height = r.height_cm
        points.append({
            "id": r.id, "recorded_on": r.recorded_on, "weight_kg": r.weight_kg, "height_cm": r.height_cm,
            "body_fat_pct": r.body_fat_pct, "chest_cm": r.chest_cm, "waist_cm": r.waist_cm,
            "hips_cm": r.hips_cm, "bmi": calc_bmi(r.weight_kg, known_height),
        })
    return points


def metric_change(records: Iterable, metric: str) -> Optional[dict]:
    """First and latest value of one measurement and the difference. None when never measured.
    The change is None when it was measured only once."""
    values = [(r.recorded_on, getattr(r, metric)) for r in _ordered(records) if getattr(r, metric) is not None]
    if not values:
        return None
    (first_date, first), (latest_date, latest) = values[0], values[-1]
    return {"metric": metric, "first_value": first, "first_date": first_date,
            "latest_value": latest, "latest_date": latest_date,
            "change": (Decimal(latest) - Decimal(first)) if len(values) > 1 else None,
            "measurements": len(values)}


def all_changes(records: Sequence) -> list[dict]:
    return [c for c in (metric_change(records, m) for m in METRICS) if c is not None]
