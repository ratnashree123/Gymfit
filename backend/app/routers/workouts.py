"""/api/workouts: workout plans and exercises (Admin, and Trainers for their own members)."""
import math
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status as http
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_fitness_staff
from app.dependencies.common import get_client_ip
from app.models import User
from app.schemas.auth import MessageOut
from app.schemas.fitness import (
    ExerciseIn, ExerciseOut, ExerciseUpdate, PlanCreate, PlanDetailOut, PlanPage, PlanStatus,
    PlanUpdate, ReorderIn,
)
from app.services import workout_service
from app.services.fitness_rules import KNOWN_MUSCLE_GROUPS

router = APIRouter(prefix="/workouts", tags=["Workout plans"])


# NOTE: "/muscle-groups" and "/plans" are fixed paths, declared BEFORE the "{id}" ones.
@router.get("/muscle-groups", response_model=list[str])
def muscle_groups(_user: User = Depends(require_fitness_staff)):
    """Suggested muscle groups for a dropdown. Other names are accepted too."""
    return list(KNOWN_MUSCLE_GROUPS)


@router.get("/plans", response_model=PlanPage)
def list_plans(
    member_id: Optional[int] = None,
    status: Optional[PlanStatus] = None,
    search: Optional[str] = Query(None, max_length=100, description="Plan title or goal, member name or code"),
    trainer_id: Optional[int] = Query(None, description="Admin only: plans written by this trainer"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_fitness_staff),
):
    """Trainers see only the plans of their own members."""
    items, total = workout_service.list_plans(db, user, member_id=member_id, status=status, search=search,
                                              trainer_id=trainer_id, page=page, page_size=page_size)
    return PlanPage(items=items, total=total, page=page, page_size=page_size,
                    pages=math.ceil(total / page_size) if total else 0)


@router.post("/plans", response_model=PlanDetailOut, status_code=http.HTTP_201_CREATED)
def create_plan(payload: PlanCreate, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_fitness_staff)):
    """A member can have only one active plan at a time."""
    plan_id = workout_service.create_plan(db, payload, user, get_client_ip(request))
    return workout_service.plan_response(db, plan_id)


@router.get("/plans/{plan_id}", response_model=PlanDetailOut)
def read_plan(plan_id: int, db: Session = Depends(get_db), user: User = Depends(require_fitness_staff)):
    return workout_service.detail(workout_service.get_plan(db, plan_id, user))


@router.patch("/plans/{plan_id}", response_model=PlanDetailOut)
def update_plan(plan_id: int, payload: PlanUpdate, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_fitness_staff)):
    """Only an active plan can be edited. Completed and archived plans can only change status."""
    workout_service.update_plan(db, plan_id, payload, user, get_client_ip(request))
    return workout_service.plan_response(db, plan_id)


@router.post("/plans/{plan_id}/exercises", response_model=ExerciseOut, status_code=http.HTTP_201_CREATED)
def add_exercise(plan_id: int, payload: ExerciseIn, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_fitness_staff)):
    return workout_service.add_exercise(db, plan_id, payload, user, get_client_ip(request))


@router.post("/plans/{plan_id}/reorder", response_model=PlanDetailOut)
def reorder_exercises(plan_id: int, payload: ReorderIn, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_fitness_staff)):
    """Put the exercises of one day in a new order. List every exercise of that day once."""
    workout_service.reorder(db, plan_id, payload, user, get_client_ip(request))
    return workout_service.plan_response(db, plan_id)


@router.patch("/exercises/{exercise_id}", response_model=ExerciseOut)
def update_exercise(exercise_id: int, payload: ExerciseUpdate, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_fitness_staff)):
    return workout_service.update_exercise(db, exercise_id, payload, user, get_client_ip(request))


@router.delete("/exercises/{exercise_id}", response_model=MessageOut)
def delete_exercise(exercise_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_fitness_staff)):
    workout_service.delete_exercise(db, exercise_id, user, get_client_ip(request))
    return MessageOut(message="Exercise removed")
