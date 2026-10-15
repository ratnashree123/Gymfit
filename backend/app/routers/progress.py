"""/api/progress: body measurements and progress over time (Admin, and Trainers for their own members)."""
import math
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request, status as http
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_fitness_staff
from app.dependencies.common import get_client_ip
from app.models import User
from app.schemas.auth import MessageOut
from app.schemas.fitness import (
    FitnessSummary, ProgressCreate, ProgressOut, ProgressPage, ProgressUpdate, SeriesOut,
)
from app.services import progress_service

router = APIRouter(prefix="/progress", tags=["Fitness progress"])


@router.get("/members/{member_id}/series", response_model=SeriesOut)
def progress_series(member_id: int, date_from: Optional[date] = None, date_to: Optional[date] = None,
                    db: Session = Depends(get_db), user: User = Depends(require_fitness_staff)):
    """Chart-ready points (oldest first, with BMI) and the change since the first measurement."""
    return progress_service.series(db, user, member_id, date_from, date_to)


@router.get("/members/{member_id}/summary", response_model=FitnessSummary)
def progress_summary(member_id: int, db: Session = Depends(get_db), user: User = Depends(require_fitness_staff)):
    """Goal, active plan, first and latest measurements, BMI and changes in one call."""
    return progress_service.summary(db, user, member_id)


@router.get("", response_model=ProgressPage)
def list_progress(
    member_id: int = Query(..., description="Whose measurements"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_fitness_staff),
):
    items, total = progress_service.list_records(db, user, member_id=member_id, date_from=date_from,
                                                 date_to=date_to, order=order, page=page, page_size=page_size)
    return ProgressPage(items=items, total=total, page=page, page_size=page_size,
                        pages=math.ceil(total / page_size) if total else 0)


@router.post("", response_model=ProgressOut, status_code=http.HTTP_201_CREATED)
def create_progress(payload: ProgressCreate, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_fitness_staff)):
    """Every measurement is optional (voluntary), but a record cannot be empty. One record per member per day."""
    record_id = progress_service.create_record(db, payload, user, get_client_ip(request))
    return progress_service.record_response(db, record_id)


@router.get("/{record_id}", response_model=ProgressOut)
def read_progress(record_id: int, db: Session = Depends(get_db), user: User = Depends(require_fitness_staff)):
    return progress_service.to_out(progress_service.get_record(db, record_id, user))


@router.patch("/{record_id}", response_model=ProgressOut)
def update_progress(record_id: int, payload: ProgressUpdate, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_fitness_staff)):
    progress_service.update_record(db, record_id, payload, user, get_client_ip(request))
    return progress_service.record_response(db, record_id)


@router.delete("/{record_id}", response_model=MessageOut)
def delete_progress(record_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_fitness_staff)):
    """Body data can be erased. The audit log keeps only that the record existed."""
    progress_service.delete_record(db, record_id, user, get_client_ip(request))
    return MessageOut(message="Progress record deleted")
