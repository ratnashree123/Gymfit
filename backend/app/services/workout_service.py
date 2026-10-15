"""Workout plans and their exercises.

Who may use this: Admins, and Trainers for the members assigned to them.
Receptionists have no access to workout or body data.
A member has at most ONE active plan at a time.
"""
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.constants import ROLE_ADMIN, ROLE_TRAINER
from app.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models import Member, StaffProfile, User, WorkoutExercise, WorkoutPlan
from app.schemas.billing import MemberRef
from app.schemas.fitness import (
    DayOut, ExerciseIn, ExerciseOut, ExerciseUpdate, PlanCreate, PlanDetailOut, PlanListItem,
    PlanUpdate, ReorderIn,
)
from app.services import member_service
from app.services.audit_service import log_action
from app.services.fitness_rules import MAX_EXERCISES_PER_DAY, reorder_problem, validate_exercise_load
from app.utils.dates import gym_today

LOADERS = (selectinload(WorkoutPlan.exercises), selectinload(WorkoutPlan.member),
           selectinload(WorkoutPlan.trainer))


# ------------------------------------------------------------------ access
def require_fitness_role(user: User) -> None:
    if user.role.name not in (ROLE_ADMIN, ROLE_TRAINER):
        raise ForbiddenError("You do not have permission to see workout or body data")


def member_for(db: Session, member_id: int, user: User) -> Member:
    """The member, or 404. A trainer asking for someone else's member gets 404 (not 403)."""
    require_fitness_role(user)
    return member_service.get_member(db, member_id, user)


def lock_member(db: Session, member_id: int) -> None:
    """SELECT ... FOR UPDATE: two people editing the same member's plans are handled one after the other."""
    db.scalar(select(Member).where(Member.id == member_id).with_for_update())


def _check_trainer(db: Session, trainer_id: int) -> None:
    profile = db.get(StaffProfile, trainer_id)
    if (profile is None or profile.user.role.name != ROLE_TRAINER or profile.status != "active"
            or not profile.user.is_active):
        raise BadRequestError("The trainer must be an active trainer")


# ------------------------------------------------------------------ output
def exercise_out(ex: WorkoutExercise) -> ExerciseOut:
    return ExerciseOut(id=ex.id, plan_id=ex.plan_id, day_number=ex.day_number, muscle_group=ex.muscle_group,
                       exercise_name=ex.exercise_name, sets=ex.sets, reps=ex.reps,
                       duration_minutes=ex.duration_minutes, rest_seconds=ex.rest_seconds,
                       sort_order=ex.sort_order, notes=ex.notes)


def list_item(plan: WorkoutPlan) -> PlanListItem:
    member = plan.member
    return PlanListItem(
        id=plan.id, member=MemberRef(id=member.id, member_code=member.member_code, full_name=member.full_name),
        trainer_id=plan.trainer_id, trainer_name=plan.trainer.user.full_name if plan.trainer else None,
        title=plan.title, goal=plan.goal, status=plan.status, start_date=plan.start_date,
        end_date=plan.end_date, exercise_count=len(plan.exercises),
        training_days=len({e.day_number for e in plan.exercises}), created_at=plan.created_at)


def detail(plan: WorkoutPlan) -> PlanDetailOut:
    by_day: dict[int, list[WorkoutExercise]] = {}
    for ex in sorted(plan.exercises, key=lambda e: (e.day_number, e.sort_order, e.id)):
        by_day.setdefault(ex.day_number, []).append(ex)
    days = [DayOut(day_number=day, muscle_groups=list(dict.fromkeys(e.muscle_group for e in exercises)),
                   exercises=[exercise_out(e) for e in exercises])
            for day, exercises in sorted(by_day.items())]
    return PlanDetailOut(**list_item(plan).model_dump(), notes=plan.notes, days=days)


def _snapshot(plan: WorkoutPlan) -> dict:
    return {"member_id": plan.member_id, "trainer_id": plan.trainer_id, "title": plan.title,
            "status": plan.status, "start_date": plan.start_date, "end_date": plan.end_date}


# ------------------------------------------------------------------ plans
def _load(db: Session, plan_id: int) -> Optional[WorkoutPlan]:
    return db.scalar(select(WorkoutPlan).where(WorkoutPlan.id == plan_id).options(*LOADERS))


def get_plan(db: Session, plan_id: int, user: User) -> WorkoutPlan:
    plan = _load(db, plan_id)
    if plan is None:
        raise NotFoundError("Workout plan not found")
    member_for(db, plan.member_id, user)  # scope check: 404 for an unassigned trainer
    return plan


def plan_response(db: Session, plan_id: int) -> PlanDetailOut:
    db.expire_all()
    return detail(_load(db, plan_id))


def _ensure_no_active(db: Session, member_id: int, exclude_plan_id: Optional[int] = None) -> None:
    stmt = select(WorkoutPlan).where(WorkoutPlan.member_id == member_id, WorkoutPlan.status == "active")
    if exclude_plan_id is not None:
        stmt = stmt.where(WorkoutPlan.id != exclude_plan_id)
    other = db.scalar(stmt.limit(1))
    if other is not None:
        raise ConflictError(f"This member already has an active plan ('{other.title}'). "
                            "Complete or archive it first")


def create_plan(db: Session, data: PlanCreate, user: User, ip: Optional[str]) -> int:
    member = member_for(db, data.member_id, user)
    lock_member(db, member.id)

    if data.trainer_id is not None and user.role.name != ROLE_ADMIN:
        raise ForbiddenError("Only an Admin can choose the trainer of a plan")
    if user.role.name == ROLE_TRAINER:
        trainer_id = user.staff_profile.id
    else:
        trainer_id = data.trainer_id if data.trainer_id is not None else member.assigned_trainer_id
        if data.trainer_id is not None:
            _check_trainer(db, data.trainer_id)

    start = data.start_date or gym_today()
    if data.end_date is not None and data.end_date < start:
        raise BadRequestError("end_date cannot be before start_date")
    _ensure_no_active(db, member.id)

    per_day: dict[int, int] = {}
    for ex in data.exercises:
        per_day[ex.day_number] = per_day.get(ex.day_number, 0) + 1
        if per_day[ex.day_number] > MAX_EXERCISES_PER_DAY:
            raise BadRequestError(f"A day can have at most {MAX_EXERCISES_PER_DAY} exercises")

    plan = WorkoutPlan(member_id=member.id, trainer_id=trainer_id, title=data.title, goal=data.goal,
                       start_date=start, end_date=data.end_date, status="active", notes=data.notes)
    db.add(plan)
    db.flush()
    counters: dict[int, int] = {}
    for ex in data.exercises:
        counters[ex.day_number] = counters.get(ex.day_number, 0) + 1
        db.add(WorkoutExercise(plan_id=plan.id, day_number=ex.day_number, muscle_group=ex.muscle_group,
                               exercise_name=ex.exercise_name, sets=ex.sets, reps=ex.reps,
                               duration_minutes=ex.duration_minutes, rest_seconds=ex.rest_seconds,
                               notes=ex.notes, sort_order=counters[ex.day_number]))
    db.flush()
    log_action(db, user_id=user.id, action="workout.plan_create", entity_type="workout_plan",
               entity_id=plan.id, new={**_snapshot(plan), "exercises": len(data.exercises)}, ip=ip)
    db.commit()
    return plan.id


def list_plans(db: Session, user: User, *, member_id: Optional[int], status: Optional[str],
               search: Optional[str], trainer_id: Optional[int], page: int, page_size: int):
    require_fitness_role(user)
    conditions = [Member.is_deleted.is_(False)]
    if user.role.name == ROLE_TRAINER:
        if user.staff_profile is None:
            return [], 0
        conditions.append(Member.assigned_trainer_id == user.staff_profile.id)
    elif trainer_id is not None:
        conditions.append(WorkoutPlan.trainer_id == trainer_id)
    if member_id is not None:
        conditions.append(WorkoutPlan.member_id == member_id)
    if status:
        conditions.append(WorkoutPlan.status == status)
    if search and search.strip():
        pattern = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(or_(*[col.ilike(pattern, escape="\\") for col in (
            WorkoutPlan.title, WorkoutPlan.goal, Member.full_name, Member.member_code)]))

    def joined(stmt):
        return stmt.join(Member, Member.id == WorkoutPlan.member_id).where(*conditions)

    total = db.scalar(joined(select(func.count(WorkoutPlan.id)))) or 0
    plans = db.scalars(joined(select(WorkoutPlan)).options(*LOADERS)
                       .order_by(WorkoutPlan.start_date.desc(), WorkoutPlan.id.desc())
                       .offset((page - 1) * page_size).limit(page_size)).all()
    return [list_item(p) for p in plans], total


def update_plan(db: Session, plan_id: int, data: PlanUpdate, user: User, ip: Optional[str]) -> None:
    plan = get_plan(db, plan_id, user)
    lock_member(db, plan.member_id)
    db.refresh(plan)
    changes = data.model_dump(exclude_unset=True)

    for field in ("title", "start_date", "status"):
        if field in changes and changes[field] is None:
            raise BadRequestError(f"'{field}' cannot be empty")
    if plan.status != "active" and set(changes) - {"status"}:
        raise BadRequestError("Only an active plan can be edited. Set its status back to 'active' first")
    if "trainer_id" in changes:
        if user.role.name != ROLE_ADMIN:
            raise ForbiddenError("Only an Admin can change the trainer of a plan")
        if changes["trainer_id"] is not None:
            _check_trainer(db, changes["trainer_id"])

    new_status = changes.get("status", plan.status)
    if new_status == "active" and plan.status != "active":
        _ensure_no_active(db, plan.member_id, exclude_plan_id=plan.id)

    start = changes.get("start_date", plan.start_date)
    end = changes["end_date"] if "end_date" in changes else plan.end_date
    if end is not None and end < start:
        raise BadRequestError("end_date cannot be before start_date")
    if new_status == "completed" and plan.status != "completed" and end is None:
        end = max(gym_today(), start)  # finishing a plan closes it today

    old = _snapshot(plan)
    for field in ("title", "goal", "start_date", "notes", "trainer_id", "status"):
        if field in changes:
            setattr(plan, field, changes[field])
    plan.end_date = end
    db.flush()
    log_action(db, user_id=user.id, action="workout.plan_update", entity_type="workout_plan",
               entity_id=plan.id, old=old, new={**_snapshot(plan), "changed": sorted(changes)}, ip=ip)
    db.commit()


# ------------------------------------------------------------------ exercises
def _require_active(plan: WorkoutPlan) -> None:
    if plan.status != "active":
        raise BadRequestError("Only an active plan can be edited. Set its status back to 'active' first")


def _day_count(db: Session, plan_id: int, day: int) -> int:
    return db.scalar(select(func.count(WorkoutExercise.id)).where(
        WorkoutExercise.plan_id == plan_id, WorkoutExercise.day_number == day)) or 0


def _next_order(db: Session, plan_id: int, day: int) -> int:
    return (db.scalar(select(func.coalesce(func.max(WorkoutExercise.sort_order), 0)).where(
        WorkoutExercise.plan_id == plan_id, WorkoutExercise.day_number == day)) or 0) + 1


def _exercise_snapshot(ex: WorkoutExercise) -> dict:
    return {"plan_id": ex.plan_id, "day_number": ex.day_number, "muscle_group": ex.muscle_group,
            "exercise_name": ex.exercise_name, "sets": ex.sets, "reps": ex.reps,
            "duration_minutes": ex.duration_minutes, "rest_seconds": ex.rest_seconds}


def _plan_for_exercise(db: Session, exercise_id: int, user: User) -> tuple[WorkoutExercise, WorkoutPlan]:
    ex = db.get(WorkoutExercise, exercise_id)
    if ex is None:
        raise NotFoundError("Exercise not found")
    plan = get_plan(db, ex.plan_id, user)
    lock_member(db, plan.member_id)
    db.refresh(plan)
    db.refresh(ex)
    return ex, plan


def add_exercise(db: Session, plan_id: int, data: ExerciseIn, user: User, ip: Optional[str]) -> ExerciseOut:
    plan = get_plan(db, plan_id, user)
    lock_member(db, plan.member_id)
    db.refresh(plan)
    _require_active(plan)
    if _day_count(db, plan.id, data.day_number) >= MAX_EXERCISES_PER_DAY:
        raise BadRequestError(f"A day can have at most {MAX_EXERCISES_PER_DAY} exercises")
    ex = WorkoutExercise(plan_id=plan.id, day_number=data.day_number, muscle_group=data.muscle_group,
                         exercise_name=data.exercise_name, sets=data.sets, reps=data.reps,
                         duration_minutes=data.duration_minutes, rest_seconds=data.rest_seconds,
                         notes=data.notes, sort_order=_next_order(db, plan.id, data.day_number))
    db.add(ex)
    db.flush()
    log_action(db, user_id=user.id, action="workout.exercise_add", entity_type="workout_exercise",
               entity_id=ex.id, new=_exercise_snapshot(ex), ip=ip)
    db.commit()
    db.refresh(ex)
    return exercise_out(ex)


def update_exercise(db: Session, exercise_id: int, data: ExerciseUpdate, user: User,
                    ip: Optional[str]) -> ExerciseOut:
    ex, plan = _plan_for_exercise(db, exercise_id, user)
    _require_active(plan)
    changes = data.model_dump(exclude_unset=True)
    for field in ("day_number", "muscle_group", "exercise_name"):
        if field in changes and changes[field] is None:
            raise BadRequestError(f"'{field}' cannot be empty")

    merged = {f: changes.get(f, getattr(ex, f)) for f in ("sets", "reps", "duration_minutes")}
    problem = validate_exercise_load(merged["sets"], merged["reps"], merged["duration_minutes"])
    if problem:
        raise BadRequestError(problem)

    old = _exercise_snapshot(ex)
    new_day = changes.get("day_number", ex.day_number)
    if new_day != ex.day_number:
        if _day_count(db, plan.id, new_day) >= MAX_EXERCISES_PER_DAY:
            raise BadRequestError(f"A day can have at most {MAX_EXERCISES_PER_DAY} exercises")
        ex.sort_order = _next_order(db, plan.id, new_day)  # a moved exercise goes to the end of its new day
    for field, value in changes.items():
        setattr(ex, field, value)
    db.flush()
    log_action(db, user_id=user.id, action="workout.exercise_update", entity_type="workout_exercise",
               entity_id=ex.id, old=old, new=_exercise_snapshot(ex), ip=ip)
    db.commit()
    db.refresh(ex)
    return exercise_out(ex)


def delete_exercise(db: Session, exercise_id: int, user: User, ip: Optional[str]) -> None:
    ex, plan = _plan_for_exercise(db, exercise_id, user)
    _require_active(plan)
    log_action(db, user_id=user.id, action="workout.exercise_delete", entity_type="workout_exercise",
               entity_id=ex.id, old=_exercise_snapshot(ex), ip=ip)
    db.delete(ex)
    db.commit()


def reorder(db: Session, plan_id: int, data: ReorderIn, user: User, ip: Optional[str]) -> None:
    plan = get_plan(db, plan_id, user)
    lock_member(db, plan.member_id)
    db.refresh(plan)
    _require_active(plan)
    current = db.scalars(select(WorkoutExercise).where(
        WorkoutExercise.plan_id == plan.id, WorkoutExercise.day_number == data.day_number)).all()
    problem = reorder_problem([e.id for e in current], data.exercise_ids)
    if problem:
        raise BadRequestError(problem)
    by_id = {e.id: e for e in current}
    for position, exercise_id in enumerate(data.exercise_ids, start=1):
        by_id[exercise_id].sort_order = position
    log_action(db, user_id=user.id, action="workout.exercise_reorder", entity_type="workout_plan",
               entity_id=plan.id, new={"day_number": data.day_number, "order": data.exercise_ids}, ip=ip)
    db.commit()
