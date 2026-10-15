"""Workout plans, exercises and progress measurements."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.billing import MemberRef
from app.schemas.common import OptNotes, OptText255, Page, UTCDateTime
from app.schemas.equipment import PastDate, SaneDate
from app.services.fitness_rules import normalize_muscle_group

PlanStatus = Literal["active", "completed", "archived"]

DayNumber = Annotated[int, Field(ge=1, le=7)]
Sets = Annotated[int, Field(ge=1, le=20)]
Reps = Annotated[int, Field(ge=1, le=200)]
Minutes = Annotated[int, Field(ge=1, le=600)]
RestSeconds = Annotated[int, Field(ge=0, le=1800)]
MuscleGroup = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60),
                        AfterValidator(normalize_muscle_group)]
ExerciseName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
PlanTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]

Weight = Optional[Annotated[Decimal, Field(ge=20, le=400, max_digits=5, decimal_places=2)]]
Height = Optional[Annotated[Decimal, Field(ge=50, le=260, max_digits=5, decimal_places=1)]]
BodyFat = Optional[Annotated[Decimal, Field(ge=2, le=70, max_digits=4, decimal_places=1)]]
Girth = Optional[Annotated[Decimal, Field(ge=20, le=250, max_digits=5, decimal_places=1)]]


# ------------------------------------------------------------------ exercises
class ExerciseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_number: DayNumber
    muscle_group: MuscleGroup
    exercise_name: ExerciseName
    sets: Optional[Sets] = None
    reps: Optional[Reps] = None
    duration_minutes: Optional[Minutes] = None
    rest_seconds: Optional[RestSeconds] = None
    notes: OptText255 = None

    @model_validator(mode="after")
    def needs_a_load(self):
        from app.services.fitness_rules import validate_exercise_load

        problem = validate_exercise_load(self.sets, self.reps, self.duration_minutes)
        if problem:
            raise ValueError(problem)
        return self


class ExerciseUpdate(BaseModel):
    """Only the fields you send are changed."""

    model_config = ConfigDict(extra="forbid")

    day_number: Optional[DayNumber] = None
    muscle_group: Optional[MuscleGroup] = None
    exercise_name: Optional[ExerciseName] = None
    sets: Optional[Sets] = None
    reps: Optional[Reps] = None
    duration_minutes: Optional[Minutes] = None
    rest_seconds: Optional[RestSeconds] = None
    notes: OptText255 = None


class ReorderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_number: DayNumber
    exercise_ids: list[int] = Field(min_length=1, max_length=30)


class ExerciseOut(BaseModel):
    id: int
    plan_id: int
    day_number: int
    muscle_group: str
    exercise_name: str
    sets: Optional[int] = None
    reps: Optional[int] = None
    duration_minutes: Optional[int] = None
    rest_seconds: Optional[int] = None
    sort_order: int
    notes: Optional[str] = None


class DayOut(BaseModel):
    day_number: int
    muscle_groups: list[str]
    exercises: list[ExerciseOut]


# ------------------------------------------------------------------ plans
class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: int
    title: PlanTitle
    goal: OptText255 = None
    start_date: Optional[SaneDate] = None  # default: today
    end_date: Optional[SaneDate] = None
    notes: OptNotes = None
    trainer_id: Optional[int] = None  # Admin only. Default: the member's assigned trainer
    exercises: list[ExerciseIn] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def end_after_start(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[PlanTitle] = None
    goal: OptText255 = None
    start_date: Optional[SaneDate] = None
    end_date: Optional[SaneDate] = None
    status: Optional[PlanStatus] = None
    notes: OptNotes = None
    trainer_id: Optional[int] = None  # Admin only


class PlanListItem(BaseModel):
    id: int
    member: MemberRef
    trainer_id: Optional[int] = None
    trainer_name: Optional[str] = None
    title: str
    goal: Optional[str] = None
    status: str
    start_date: date
    end_date: Optional[date] = None
    exercise_count: int
    training_days: int
    created_at: UTCDateTime


class PlanDetailOut(PlanListItem):
    notes: Optional[str] = None
    days: list[DayOut]


class PlanPage(Page[PlanListItem]):
    pass


# ------------------------------------------------------------------ progress
class ProgressCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: int
    recorded_on: PastDate = None  # default: today
    weight_kg: Weight = None
    height_cm: Height = None
    body_fat_pct: BodyFat = None
    chest_cm: Girth = None
    waist_cm: Girth = None
    hips_cm: Girth = None
    goal: OptText255 = None
    notes: OptText255 = None

    @model_validator(mode="after")
    def not_empty(self):
        content = (self.weight_kg, self.height_cm, self.body_fat_pct, self.chest_cm, self.waist_cm,
                   self.hips_cm, self.goal, self.notes)
        if all(value is None for value in content):
            raise ValueError("Give at least one measurement, a goal or a note")
        return self


class ProgressUpdate(BaseModel):
    """Only the fields you send are changed. Send null to clear a measurement."""

    model_config = ConfigDict(extra="forbid")

    recorded_on: PastDate = None
    weight_kg: Weight = None
    height_cm: Height = None
    body_fat_pct: BodyFat = None
    chest_cm: Girth = None
    waist_cm: Girth = None
    hips_cm: Girth = None
    goal: OptText255 = None
    notes: OptText255 = None

    @model_validator(mode="after")
    def something_sent(self):
        if not self.model_fields_set:
            raise ValueError("Send at least one field to change")
        return self


class ProgressOut(BaseModel):
    id: int
    member: MemberRef
    recorded_on: date
    weight_kg: Optional[Decimal] = None
    height_cm: Optional[Decimal] = None
    body_fat_pct: Optional[Decimal] = None
    chest_cm: Optional[Decimal] = None
    waist_cm: Optional[Decimal] = None
    hips_cm: Optional[Decimal] = None
    goal: Optional[str] = None
    notes: Optional[str] = None
    recorded_by_name: Optional[str] = None
    created_at: UTCDateTime


class ProgressPage(Page[ProgressOut]):
    pass


class ProgressPoint(BaseModel):
    id: int
    recorded_on: date
    weight_kg: Optional[Decimal] = None
    height_cm: Optional[Decimal] = None
    body_fat_pct: Optional[Decimal] = None
    chest_cm: Optional[Decimal] = None
    waist_cm: Optional[Decimal] = None
    hips_cm: Optional[Decimal] = None
    bmi: Optional[Decimal] = None


class MetricChange(BaseModel):
    metric: str
    first_value: Decimal
    first_date: date
    latest_value: Decimal
    latest_date: date
    change: Optional[Decimal] = None  # None when measured only once
    measurements: int


class SeriesOut(BaseModel):
    member: MemberRef
    points: list[ProgressPoint]
    changes: list[MetricChange]


class FitnessSummary(BaseModel):
    member: MemberRef
    records: int
    current_goal: Optional[str] = None  # latest goal written in a measurement, else the active plan's goal
    active_plan: Optional[PlanListItem] = None
    first: Optional[ProgressOut] = None
    latest: Optional[ProgressOut] = None
    bmi: Optional[Decimal] = None  # latest weight with the latest known height
    bmi_category: Optional[str] = None  # adults only; an indicator, not a diagnosis
    changes: list[MetricChange]
