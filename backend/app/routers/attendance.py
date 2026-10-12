"""/api/attendance: check-in, check-out, who is inside, history, corrections, reports."""
import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status as http
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_admin, require_any_staff, require_front_desk
from app.dependencies.common import get_client_ip
from app.models import User
from app.schemas.attendance import (
    AttendanceCorrection, AttendanceOut, AttendancePage, AttendancePeriod, AttendanceReport,
    AttendanceStatus, CheckInIn, CheckOutIn, CloseStaleOut, InsideOut, LookupItem, RemoveIn,
)
from app.schemas.auth import MessageOut
from app.services import attendance_service

router = APIRouter(prefix="/attendance", tags=["Attendance"])


# NOTE: fixed paths ("/lookup", "/inside", ...) are declared BEFORE "/{attendance_id}".
@router.get("/lookup", response_model=list[LookupItem])
def lookup_members(
    search: str = Query(..., min_length=2, max_length=100, description="Name, phone or member code"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_front_desk),
):
    """Reception's quick search: shows if the member is inside and whether they may enter."""
    return attendance_service.lookup(db, search)


@router.post("/check-in", response_model=AttendanceOut, status_code=http.HTTP_201_CREATED)
def check_in(payload: CheckInIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_front_desk)):
    visit = attendance_service.check_in(db, payload.member_id, payload.override_reason, user,
                                        get_client_ip(request))
    return attendance_service.visit_out(db, visit.id)


@router.post("/check-out", response_model=AttendanceOut)
def check_out(payload: CheckOutIn, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_front_desk)):
    visit = attendance_service.check_out(db, payload.member_id, user, get_client_ip(request))
    return attendance_service.visit_out(db, visit.id)


@router.get("/inside", response_model=InsideOut)
def who_is_inside(db: Session = Depends(get_db), user: User = Depends(require_any_staff)):
    """Everyone currently inside (trainers see only their own members)."""
    items, stale_count = attendance_service.list_inside(db, user)
    return InsideOut(count=len(items), stale_count=stale_count, items=items)


@router.post("/close-stale", response_model=CloseStaleOut)
def close_stale_visits(request: Request, db: Session = Depends(get_db),
                       user: User = Depends(require_front_desk)):
    """Closes visits that were never checked out (older than the auto-checkout limit)."""
    return CloseStaleOut(closed=attendance_service.close_stale(db, user, get_client_ip(request)))


@router.get("/report", response_model=AttendanceReport)
def attendance_report(
    period: AttendancePeriod = "day",
    on_date: Optional[date] = Query(None, alias="date", description="Any date inside the day / week / month"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_front_desk),
):
    return attendance_service.report(db, period, on_date)


@router.get("/export.csv")
def export_attendance_csv(date_from: date, date_to: date, db: Session = Depends(get_db),
                          _admin: User = Depends(require_admin)):
    content = attendance_service.export_csv(db, date_from, date_to)
    filename = f"attendance_{date_from.isoformat()}_{date_to.isoformat()}.csv"
    return Response(content=content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "no-store"})


@router.get("", response_model=AttendancePage)
def list_attendance(
    member_id: Optional[int] = None,
    status: Optional[AttendanceStatus] = None,
    search: Optional[str] = Query(None, max_length=100),
    period: Optional[AttendancePeriod] = Query(None, description="day, week (Mon-Sun) or month"),
    on_date: Optional[date] = Query(None, alias="date", description="Reference date for 'period' (default today)"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_any_staff),
):
    """History, newest first. Use `period` (+ `date`) OR `date_from`/`date_to`. Trainers see their own members only."""
    items, total = attendance_service.list_attendance(
        db, user, member_id=member_id, status=status, search=search, period=period,
        on_date=on_date, date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    return AttendancePage(items=items, total=total, page=page, page_size=page_size,
                          pages=math.ceil(total / page_size) if total else 0)


@router.get("/{attendance_id}", response_model=AttendanceOut)
def read_attendance(attendance_id: int, db: Session = Depends(get_db),
                    _user: User = Depends(require_front_desk)):
    return attendance_service.visit_out(db, attendance_id)


@router.patch("/{attendance_id}", response_model=AttendanceOut)
def correct_attendance(attendance_id: int, payload: AttendanceCorrection, request: Request,
                       db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Admin fix for a wrong time. A reason is required and the old values go to the audit log."""
    visit = attendance_service.correct(db, attendance_id, payload, admin, get_client_ip(request))
    return attendance_service.visit_out(db, visit.id)


@router.post("/{attendance_id}/remove", response_model=MessageOut)
def remove_attendance(attendance_id: int, payload: RemoveIn, request: Request,
                      db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """For a check-in made by mistake. The whole record is saved in the audit log first."""
    attendance_service.remove(db, attendance_id, payload.reason, admin, get_client_ip(request))
    return MessageOut(message="Attendance record removed")
