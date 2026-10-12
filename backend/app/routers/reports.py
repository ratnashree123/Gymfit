"""/api/reports: revenue (Admin only)."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_admin
from app.models import User
from app.schemas.billing import RevenueReport
from app.services import report_service

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
