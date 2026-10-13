"""/api/maintenance: job history, reminders, and the job life cycle."""
import math
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_admin, require_front_desk
from app.dependencies.common import get_client_ip
from app.models import User
from app.schemas.equipment import (
    JobStatus, JobType, MaintenanceCancel, MaintenanceComplete, MaintenanceOut, MaintenancePage,
    MaintenanceStart, MaintenanceUpdate, RemindersOut,
)
from app.services import maintenance_service

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


# NOTE: "/reminders" is declared BEFORE "/{job_id}".
@router.get("/reminders", response_model=RemindersOut)
def maintenance_reminders(
    days: Optional[int] = Query(None, ge=0, le=365, description="Warn this many days ahead (default: setting, 7)"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_front_desk),
):
    """Urgent (damaged or overdue) and soon-due equipment."""
    return maintenance_service.reminders(db, days)


@router.get("", response_model=MaintenancePage)
def list_jobs(
    equipment_id: Optional[int] = None,
    status: Optional[JobStatus] = None,
    maintenance_type: Optional[JobType] = None,
    overdue: bool = Query(False, description="Only scheduled jobs whose date has passed"),
    search: Optional[str] = Query(None, max_length=100, description="Equipment name or code"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_front_desk),
):
    """Maintenance history (costs are visible to Admins only)."""
    items, total, total_cost = maintenance_service.list_jobs(
        db, user, equipment_id=equipment_id, status=status, maintenance_type=maintenance_type,
        overdue=overdue, search=search, date_from=date_from, date_to=date_to, order=order,
        page=page, page_size=page_size)
    return MaintenancePage(items=items, total=total, page=page, page_size=page_size,
                           pages=math.ceil(total / page_size) if total else 0, total_cost=total_cost)


@router.get("/{job_id}", response_model=MaintenanceOut)
def read_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_front_desk)):
    return maintenance_service.job_response(db, job_id, user)


@router.patch("/{job_id}", response_model=MaintenanceOut)
def update_job(job_id: int, payload: MaintenanceUpdate, request: Request, db: Session = Depends(get_db),
               admin: User = Depends(require_admin)):
    """Scheduled and in-progress jobs only. Finished jobs are history."""
    job = maintenance_service.update_job(db, job_id, payload, admin, get_client_ip(request))
    return maintenance_service.job_response(db, job.id, admin)


@router.post("/{job_id}/start", response_model=MaintenanceOut)
def start_job(job_id: int, payload: MaintenanceStart, request: Request, db: Session = Depends(get_db),
              admin: User = Depends(require_admin)):
    """Work begins: the equipment becomes 'under_maintenance'."""
    job = maintenance_service.start_job(db, job_id, payload, admin, get_client_ip(request))
    return maintenance_service.job_response(db, job.id, admin)


@router.post("/{job_id}/complete", response_model=MaintenanceOut)
def complete_job(job_id: int, payload: MaintenanceComplete, request: Request, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    """Work done: records the cost, updates the equipment's dates and makes it available again."""
    job = maintenance_service.complete_job(db, job_id, payload, admin, get_client_ip(request))
    return maintenance_service.job_response(db, job.id, admin)


@router.post("/{job_id}/cancel", response_model=MaintenanceOut)
def cancel_job(job_id: int, payload: MaintenanceCancel, request: Request, db: Session = Depends(get_db),
               admin: User = Depends(require_admin)):
    job = maintenance_service.cancel_job(db, job_id, payload, admin, get_client_ip(request))
    return maintenance_service.job_response(db, job.id, admin)
