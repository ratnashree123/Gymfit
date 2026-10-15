from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.fitness_rules import (
    KNOWN_MUSCLE_GROUPS, all_changes, bmi_category, build_points, calc_bmi, metric_change,
    normalize_muscle_group, reorder_problem, validate_exercise_load,
)

D = Decimal


def record(id, day, **values):
    base = dict(weight_kg=None, height_cm=None, body_fat_pct=None, chest_cm=None, waist_cm=None, hips_cm=None)
    return SimpleNamespace(id=id, recorded_on=date(2026, 3, day), **{**base, **values})


# ---------- muscle groups and exercises ----------
def test_muscle_groups_are_tidied_but_unknown_ones_are_kept():
    assert normalize_muscle_group("chest") == "Chest"
    assert normalize_muscle_group("  FULL   body ") == "Full body"
    assert normalize_muscle_group("Rotator cuff") == "Rotator cuff"
    assert "Chest" in KNOWN_MUSCLE_GROUPS and "Cardio" in KNOWN_MUSCLE_GROUPS


def test_an_exercise_needs_sets_and_reps_or_a_duration():
    assert validate_exercise_load(3, 12, None) is None
    assert validate_exercise_load(None, None, 20) is None
    assert validate_exercise_load(3, 12, 5) is None
    for sets, reps in ((3, None), (None, 12), (None, None)):
        assert validate_exercise_load(sets, reps, None) is not None


def test_reorder_must_list_every_exercise_once():
    assert reorder_problem([1, 2, 3], [3, 1, 2]) is None
    assert reorder_problem([1, 2, 3], [1, 2]) is not None
    assert reorder_problem([1, 2, 3], [1, 2, 3, 4]) is not None
    assert reorder_problem([1, 2, 3], [1, 1, 2]) is not None
    assert reorder_problem([], []) is None


# ---------- BMI ----------
def test_bmi_is_rounded_half_up_to_one_decimal():
    assert calc_bmi(D("80"), D("180")) == D("24.7")
    assert calc_bmi(D("78"), D("180")) == D("24.1")
    assert calc_bmi(D("70.00"), D("175.0")) == D("22.9")
    assert calc_bmi(D("60"), D("150")) == D("26.7")


def test_bmi_needs_both_numbers():
    assert calc_bmi(None, D("180")) is None and calc_bmi(D("80"), None) is None
    assert calc_bmi(D("80"), D("0")) is None


def test_bmi_categories_at_the_boundaries():
    assert bmi_category(D("18.4")) == "Underweight" and bmi_category(D("18.5")) == "Healthy range"
    assert bmi_category(D("24.9")) == "Healthy range" and bmi_category(D("25.0")) == "Overweight"
    assert bmi_category(D("29.9")) == "Overweight" and bmi_category(D("30.0")) == "Obese"


# ---------- progress over time ----------
def test_points_are_oldest_first_and_bmi_remembers_the_last_height():
    rows = [record(3, 20, weight_kg=D("76")),                       # no height here: uses 180 from the 1st
            record(1, 1, weight_kg=D("80"), height_cm=D("180")),
            record(2, 10, weight_kg=D("78"), body_fat_pct=D("20.5"))]
    points = build_points(rows)
    assert [p["id"] for p in points] == [1, 2, 3]
    assert [p["bmi"] for p in points] == [D("24.7"), D("24.1"), D("23.5")]
    assert points[1]["body_fat_pct"] == D("20.5") and points[0]["chest_cm"] is None


def test_bmi_is_none_until_a_height_is_known():
    points = build_points([record(1, 1, weight_kg=D("80")), record(2, 5, weight_kg=D("79"), height_cm=D("180"))])
    assert points[0]["bmi"] is None and points[1]["bmi"] == D("24.4")


def test_change_compares_first_and_latest_measurement():
    rows = [record(1, 1, weight_kg=D("80.00"), waist_cm=D("90.0")),
            record(2, 10, weight_kg=D("78.50")),
            record(3, 20, weight_kg=D("76.25"), waist_cm=D("86.5"))]
    weight = metric_change(rows, "weight_kg")
    assert (weight["first_value"], weight["latest_value"], weight["change"]) == (D("80.00"), D("76.25"), D("-3.75"))
    assert weight["first_date"] == date(2026, 3, 1) and weight["latest_date"] == date(2026, 3, 20)
    assert weight["measurements"] == 3
    assert metric_change(rows, "waist_cm")["change"] == D("-3.5")


def test_one_measurement_has_no_change_and_a_missing_one_is_skipped():
    rows = [record(1, 1, weight_kg=D("80"), body_fat_pct=D("22.0"))]
    assert metric_change(rows, "body_fat_pct")["change"] is None
    assert metric_change(rows, "hips_cm") is None
    assert [c["metric"] for c in all_changes(rows)] == ["weight_kg", "body_fat_pct"]
    assert all_changes([]) == []
