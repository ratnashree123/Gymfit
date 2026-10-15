"""workout_plans, workout_exercises, member_progress"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._common import utcnow


class WorkoutPlan(Base):
    __tablename__ = "workout_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    trainer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("staff_profiles.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(120))
    goal: Mapped[Optional[str]] = mapped_column(String(255))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        Enum("active", "completed", "archived", name="workout_status", native_enum=False, length=20),
        default="active",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    member: Mapped["Member"] = relationship(back_populates="workout_plans")
    trainer: Mapped[Optional["StaffProfile"]] = relationship()
    exercises: Mapped[list["WorkoutExercise"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("workout_plans.id", ondelete="CASCADE"))
    day_number: Mapped[int] = mapped_column(Integer)  # 1 = Day 1 ... 7
    muscle_group: Mapped[str] = mapped_column(String(60))
    exercise_name: Mapped[str] = mapped_column(String(120))
    sets: Mapped[Optional[int]] = mapped_column(Integer)
    reps: Mapped[Optional[int]] = mapped_column(Integer)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    rest_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(String(255))

    plan: Mapped["WorkoutPlan"] = relationship(back_populates="exercises")


class MemberProgress(Base):
    __tablename__ = "member_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    recorded_on: Mapped[date] = mapped_column(Date)
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    height_cm: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1))
    body_fat_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 1))
    chest_cm: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1))
    waist_cm: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1))
    hips_cm: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1))
    goal: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[Optional[str]] = mapped_column(String(255))
    recorded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    member: Mapped["Member"] = relationship(back_populates="progress_records")
    recorder: Mapped[Optional["User"]] = relationship(foreign_keys="MemberProgress.recorded_by")
