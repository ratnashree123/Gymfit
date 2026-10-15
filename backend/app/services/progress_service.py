"""Body measurements and fitness progress.

This is health data. Access: Admins, and Trainers for their own members.
The audit log records WHICH fields changed, never the measurements themselves.
"""
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models import Member, MemberProgress, User, WorkoutPlan
from app.schemas.billing import MemberRef
from app.schemas.fitness import (
    FitnessSummary, MetricChange, ProgressCreate, ProgressOut, ProgressPoint, ProgressUpdate, SeriesOut,
)
from app.services import workout_service
from app.services.audit_service import log_action
from app.services.fitness_rules import all_changes, bmi_category, build_points, calc_bmi
from app.utils.dates import gym_today

MEASUREMENTS = ("weight_kg", "height_cm", "body_fat_pct", "chest_cm", "waist_cm", "hips_cm")
LOADERS = (selectinload(MemberProgress.member), selectinload(MemberProgress.recorder))


def _ref(member: Member) -> MemberRef:
    return MemberRef(id=member.id, member_code=member.member_code, full_name=member.full_name)


def to_out(rec: MemberProgress) -> ProgressOut:
    return ProgressOut(
        id=rec.id, member=_ref(rec.member), recorded_on=rec.recorded_on, weight_kg=rec.weight_kg,
        height_cm=rec.height_cm, body_fat_pct=rec.body_fat_pct, chest_cm=rec.chest_cm,
        waist_cm=rec.waist_cm, hips_cm=rec.hips_cm, goal=rec.goal, notes=rec.notes,
        recorded_by_name=rec.recorder.full_name if rec.recorder else None, created_at=rec.created_at)


def _has_content(rec: MemberProgress) -> bool:
    return any(getattr(rec, f) is not None for f in (*MEASUREMENTS, "goal", "notes"))


def _same_day_record(db: Session, member_id: int, day: date, exclude_id: Optional[int] = None) -> bool:
    stmt = select(func.count(MemberProgress.id)).where(
        MemberProgress.member_id == member_id, MemberProgress.recorded_on == day)
    if exclude_id is not None:
        stmt = stmt.where(MemberProgress.id != exclude_id)
    return bool(db.scalar(stmt))


def _load(db: Session, record_id: int) -> Optional[MemberProgress]:
    return db.scalar(select(MemberProgress).where(MemberProgress.id == record_id).options(*LOADERS))


def get_record(db: Session, record_id: int, user: User) -> MemberProgress:
    rec = _load(db, record_id)
    if rec is None:
        raise NotFoundError("Progress record not found")
    workout_service.member_for(db, rec.member_id, user)  # 404 for an unassigned trainer
    return rec


def record_response(db: Session, record_id: int) -> ProgressOut:
    db.expire_all()
    return to_out(_load(db, record_id))


# ------------------------------------------------------------------ write
def create_record(db: Session, data: ProgressCreate, user: User, ip: Optional[str]) -> int:
    member = workout_service.member_for(db, data.member_id, user)
    workout_service.lock_member(db, member.id)
    day = data.recorded_on or gym_today()
    if _same_day_record(db, member.id, day):
        raise ConflictError("There is already a record for this date. Edit that one instead")

    rec = MemberProgress(member_id=member.id, recorded_on=day, recorded_by=user.id, goal=data.goal,
                         notes=data.notes, **{f: getattr(data, f) for f in MEASUREMENTS})
    db.add(rec)
    db.flush()
    log_action(db, user_id=user.id, action="progress.create", entity_type="member_progress",
               entity_id=rec.id,
               new={"member_id": member.id, "recorded_on": day,
                    "fields": [f for f in (*MEASUREMENTS, "goal", "notes") if getattr(rec, f) is not None]}, ip=ip)
    db.commit()
    return rec.id


def update_record(db: Session, record_id: int, data: ProgressUpdate, user: User, ip: Optional[str]) -> None:
    rec = get_record(db, record_id, user)
    workout_service.lock_member(db, rec.member_id)
    db.refresh(rec)
    changes = data.model_dump(exclude_unset=True)
    if "recorded_on" in changes:
        if changes["recorded_on"] is None:
            raise BadRequestError("'recorded_on' cannot be empty")
        if changes["recorded_on"] != rec.recorded_on and _same_day_record(
                db, rec.member_id, changes["recorded_on"], exclude_id=rec.id):
            raise ConflictError("There is already a record for this date")
    for field, value in changes.items():
        setattr(rec, field, value)
    if not _has_content(rec):
        db.rollback()
        raise BadRequestError("A record needs at least one measurement, goal or note. Delete it instead")
    db.flush()
    log_action(db, user_id=user.id, action="progress.update", entity_type="member_progress",
               entity_id=rec.id, new={"member_id": rec.member_id, "changed": sorted(changes)}, ip=ip)
    db.commit()


def delete_record(db: Session, record_id: int, user: User, ip: Optional[str]) -> None:
    """Health data can be erased. The audit log keeps only that a record existed, never its values."""
    rec = get_record(db, record_id, user)
    workout_service.lock_member(db, rec.member_id)
    log_action(db, user_id=user.id, action="progress.delete", entity_type="member_progress",
               entity_id=rec.id, old={"member_id": rec.member_id, "recorded_on": rec.recorded_on}, ip=ip)
    db.delete(rec)
    db.commit()


# ------------------------------------------------------------------ read
def list_records(db: Session, user: User, *, member_id: int, date_from: Optional[date], date_to: Optional[date],
                 order: str, page: int, page_size: int):
    workout_service.member_for(db, member_id, user)
    if date_from and date_to and date_to < date_from:
        raise BadRequestError("'date_to' must not be before 'date_from'")
    conditions = [MemberProgress.member_id == member_id]
    if date_from:
        conditions.append(MemberProgress.recorded_on >= date_from)
    if date_to:
        conditions.append(MemberProgress.recorded_on <= date_to)
    total = db.scalar(select(func.count(MemberProgress.id)).where(*conditions)) or 0
    first = MemberProgress.recorded_on.asc() if order == "asc" else MemberProgress.recorded_on.desc()
    second = MemberProgress.id.asc() if order == "asc" else MemberProgress.id.desc()
    rows = db.scalars(select(MemberProgress).where(*conditions).options(*LOADERS)
                      .order_by(first, second).offset((page - 1) * page_size).limit(page_size)).all()
    return [to_out(r) for r in rows], total


def _all_records(db: Session, member_id: int, date_from: Optional[date] = None,
                 date_to: Optional[date] = None) -> list[MemberProgress]:
    stmt = select(MemberProgress).where(MemberProgress.member_id == member_id)
    if date_from:
        stmt = stmt.where(MemberProgress.recorded_on >= date_from)
    if date_to:
        stmt = stmt.where(MemberProgress.recorded_on <= date_to)
    return list(db.scalars(stmt.options(*LOADERS).order_by(MemberProgress.recorded_on, MemberProgress.id)).all())


def series(db: Session, user: User, member_id: int, date_from: Optional[date], date_to: Optional[date]) -> SeriesOut:
    member = workout_service.member_for(db, member_id, user)
    if date_from and date_to and date_to < date_from:
        raise BadRequestError("'date_to' must not be before 'date_from'")

    def in_window(day: date) -> bool:
        return (date_from is None or day >= date_from) and (date_to is None or day <= date_to)

    # BMI needs the latest known height, which may be measured BEFORE the window. So the points are
    # built from ALL records and then cut down to the window; the changes use only the window.
    everything = _all_records(db, member.id)
    points = [p for p in build_points(everything) if in_window(p["recorded_on"])]
    window = [r for r in everything if in_window(r.recorded_on)]
    return SeriesOut(member=_ref(member), points=[ProgressPoint(**p) for p in points],
                     changes=[MetricChange(**c) for c in all_changes(window)])


def summary(db: Session, user: User, member_id: int) -> FitnessSummary:
    member = workout_service.member_for(db, member_id, user)
    records = _all_records(db, member.id)
    plan = db.scalar(select(WorkoutPlan).where(WorkoutPlan.member_id == member.id, WorkoutPlan.status == "active")
                     .options(*workout_service.LOADERS))

    goal = next((r.goal for r in reversed(records) if r.goal), None)
    if goal is None and plan is not None:
        goal = plan.goal
    weight = next((r.weight_kg for r in reversed(records) if r.weight_kg is not None), None)
    height = next((r.height_cm for r in reversed(records) if r.height_cm is not None), None)
    bmi = calc_bmi(weight, height)

    return FitnessSummary(
        member=_ref(member), records=len(records), current_goal=goal,
        active_plan=workout_service.list_item(plan) if plan is not None else None,
        first=to_out(records[0]) if records else None, latest=to_out(records[-1]) if records else None,
        bmi=bmi, bmi_category=bmi_category(bmi) if bmi is not None else None,
        changes=[MetricChange(**c) for c in all_changes(records)])
