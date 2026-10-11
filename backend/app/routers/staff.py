"""/api/staff: manage staff accounts (Admin only, except the trainer dropdown list)."""
import math
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_RECEPTIONIST
from app.database import get_db
from app.dependencies.auth import require_admin, require_roles
from app.dependencies.common import get_client_ip
from app.models import User
from app.schemas.common import Page, RoleName, StaffStatus
from app.schemas.staff import (
    PasswordResetIn, StaffAdminOut, StaffCreate, StaffPublicOut, StaffUpdate,
)
from app.services import staff_service

router = APIRouter(prefix="/staff", tags=["Staff"])


# NOTE: "/trainers" must be declared BEFORE "/{staff_id}", otherwise "trainers"
# would be read as an id.
@router.get("/trainers", response_model=list[StaffPublicOut])
def list_trainers(
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(ROLE_ADMIN, ROLE_RECEPTIONIST)),
):
    """Active trainers (no salary or contact data). Used for 'assign trainer' dropdowns."""
    return [StaffPublicOut.from_profile(p) for p in staff_service.list_active_trainers(db)]


@router.get("", response_model=Page[StaffAdminOut])
def list_staff(
    search: Optional[str] = Query(None, max_length=100),
    role: Optional[RoleName] = None,
    status_filter: Optional[StaffStatus] = Query(None, alias="status"),
    sort_by: Literal["full_name", "created_at", "hire_date"] = "full_name",
    order: Literal["asc", "desc"] = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    items, total = staff_service.list_staff(
        db, search=search, role=role, status=status_filter,
        sort_by=sort_by, order=order, page=page, page_size=page_size,
    )
    return Page[StaffAdminOut](
        items=[StaffAdminOut.from_profile(p) for p in items],
        total=total, page=page, page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=StaffAdminOut, status_code=status.HTTP_201_CREATED)
def create_staff(
    payload: StaffCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    profile = staff_service.create_staff(db, payload, admin, get_client_ip(request))
    return StaffAdminOut.from_profile(profile)


@router.get("/{staff_id}", response_model=StaffAdminOut)
def read_staff(staff_id: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return StaffAdminOut.from_profile(staff_service.get_staff(db, staff_id))


@router.patch("/{staff_id}", response_model=StaffAdminOut)
def update_staff(
    staff_id: int,
    payload: StaffUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    profile = staff_service.update_staff(db, staff_id, payload, admin, get_client_ip(request))
    return StaffAdminOut.from_profile(profile)


@router.delete("/{staff_id}", response_model=StaffAdminOut)
def deactivate_staff(
    staff_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Deactivates the account (soft delete). History is kept."""
    profile = staff_service.deactivate_staff(db, staff_id, admin, get_client_ip(request))
    return StaffAdminOut.from_profile(profile)


@router.post("/{staff_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_staff_password(
    staff_id: int,
    payload: PasswordResetIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    staff_service.reset_password(db, staff_id, payload.new_password, admin, get_client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
