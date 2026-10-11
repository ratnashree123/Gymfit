"""/api/plans: membership plans. Admin manages; Admin and Receptionist can read."""
from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_RECEPTIONIST
from app.database import get_db
from app.dependencies.auth import require_admin, require_roles
from app.dependencies.common import get_client_ip
from app.models import User
from app.schemas.common import PlanType
from app.schemas.plan import PlanCreate, PlanOut, PlanUpdate
from app.services import plan_service

router = APIRouter(prefix="/plans", tags=["Membership plans"])


@router.get("", response_model=list[PlanOut])
def list_plans(
    active_only: bool = False,
    plan_type: Optional[PlanType] = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(ROLE_ADMIN, ROLE_RECEPTIONIST)),
):
    return [PlanOut.from_plan(p) for p in plan_service.list_plans(db, active_only=active_only, plan_type=plan_type)]


@router.post("", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(payload: PlanCreate, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    return PlanOut.from_plan(plan_service.create_plan(db, payload, admin, get_client_ip(request)))


@router.get("/{plan_id}", response_model=PlanOut)
def read_plan(plan_id: int, db: Session = Depends(get_db),
              _user: User = Depends(require_roles(ROLE_ADMIN, ROLE_RECEPTIONIST))):
    return PlanOut.from_plan(plan_service.get_plan(db, plan_id))


@router.patch("/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, payload: PlanUpdate, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    return PlanOut.from_plan(plan_service.update_plan(db, plan_id, payload, admin, get_client_ip(request)))


@router.delete("/{plan_id}", response_model=PlanOut)
def deactivate_plan(plan_id: int, request: Request, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    """Deactivates the plan (it is never deleted, old memberships keep working)."""
    return PlanOut.from_plan(plan_service.deactivate_plan(db, plan_id, admin, get_client_ip(request)))
