"""/api/dashboard: the numbers and chart data for the home screen."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_any_staff
from app.models import User
from app.schemas.dashboard import DashboardOut
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_any_staff)):
    """Everything the home screen needs in one call, shaped by the caller's role.

    Admin: everything. Receptionist: no revenue chart. Trainer: only their own members, no money, no staff numbers.
    """
    return dashboard_service.build(db, user)
