"""/api/reports: revenue (Admin only)."""
import math
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_admin, require_front_desk
from app.models import User
from app.schemas.billing import RevenueReport
from app.schemas.dashboard import MembershipReportPage, StatusCounts
from app.services import report_service

MembershipState = Literal["active", "upcoming", "expired", "inactive", "no_membership"]

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/revenue", response_model=RevenueReport)
def revenue_report(
    period: Literal["daily", "monthly", "yearly"] = "daily",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Money collected per day, month or year (gym-local dates). Empty days show as 0 so charts have no gaps."""
    return report_service.revenue(db, period, date_from, date_to)


@router.get("/memberships", response_model=MembershipReportPage)
def membership_report(
    status: Optional[MembershipState] = None,
    plan_id: Optional[int] = Query(None, description="The plan of the member's latest membership"),
    expires_from: Optional[date] = Query(None, description="Membership ends on or after this date"),
    expires_to: Optional[date] = Query(None, description="Membership ends on or before this date"),
    joined_from: Optional[date] = Query(None, description="Registered on or after this date"),
    joined_to: Optional[date] = Query(None, description="Registered on or before this date"),
    search: Optional[str] = Query(None, max_length=100),
    sort_by: Literal["full_name", "registration_date", "member_code", "created_at"] = "full_name",
    order: Literal["asc", "desc"] = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_front_desk),
):
    """Members with their membership state, filtered by status, plan, expiry date or join date.
    `summary` always counts the whole gym."""
    items, total, counts = report_service.membership_report(
        db, user, status=status, plan_id=plan_id, expires_from=expires_from, expires_to=expires_to,
        joined_from=joined_from, joined_to=joined_to, search=search, sort_by=sort_by, order=order,
        page=page, page_size=page_size)
    return MembershipReportPage(items=items, total=total, page=page, page_size=page_size,
                                pages=math.ceil(total / page_size) if total else 0,
                                summary=StatusCounts(**counts))


@router.get("/memberships/export.csv")
def membership_report_csv(
    status: Optional[MembershipState] = None,
    plan_id: Optional[int] = None,
    expires_from: Optional[date] = None,
    expires_to: Optional[date] = None,
    joined_from: Optional[date] = None,
    joined_to: Optional[date] = None,
    search: Optional[str] = Query(None, max_length=100),
    sort_by: Literal["full_name", "registration_date", "member_code", "created_at"] = "full_name",
    order: Literal["asc", "desc"] = "asc",
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """The same report as a CSV download (Admin only: it contains phone numbers and e-mails)."""
    content = report_service.export_memberships_csv(
        db, admin, status=status, plan_id=plan_id, expires_from=expires_from, expires_to=expires_to,
        joined_from=joined_from, joined_to=joined_to, search=search, sort_by=sort_by, order=order)
    return Response(content=content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="memberships.csv"',
                             "Cache-Control": "no-store"})
