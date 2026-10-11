"""/api/members: registration, search, profiles, memberships, photos."""
import math
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status as http
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_RECEPTIONIST
from app.database import get_db
from app.dependencies.auth import require_admin, require_any_staff, require_roles
from app.dependencies.common import get_client_ip
from app.models import User
from app.schemas.auth import MessageOut
from app.schemas.common import Page
from app.schemas.member import MemberCreate, MemberDetailOut, MemberListItem, MemberUpdate
from app.schemas.membership import AssignMembershipIn, MembershipOut, RenewMembershipIn
from app.services import member_service, membership_service, photo_service
from app.utils.dates import gym_today
from app.utils.images import MAX_PHOTO_BYTES

router = APIRouter(prefix="/members", tags=["Members"])

front_desk = require_roles(ROLE_ADMIN, ROLE_RECEPTIONIST)  # may create and edit members


@router.get("", response_model=Page[MemberListItem])
def list_members(
    search: Optional[str] = Query(None, max_length=100, description="Name, phone or member code"),
    status: Optional[Literal["active", "upcoming", "expired", "inactive", "no_membership"]] = None,
    expiring_soon: bool = False,
    trainer_id: Optional[int] = None,
    deleted: bool = False,
    sort_by: Literal["full_name", "registration_date", "member_code", "created_at"] = "full_name",
    order: Literal["asc", "desc"] = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_any_staff),
):
    """Trainers automatically see only the members assigned to them."""
    items, total = member_service.list_members(
        db, user, search=search, status=status, expiring_soon=expiring_soon,
        trainer_id=trainer_id, deleted=deleted, sort_by=sort_by, order=order,
        page=page, page_size=page_size,
    )
    return Page[MemberListItem](
        items=items, total=total, page=page, page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=MemberDetailOut, status_code=http.HTTP_201_CREATED)
def create_member(payload: MemberCreate, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(front_desk)):
    member = member_service.create_member(db, payload, user, get_client_ip(request))
    return member_service.detail_out(db, member, user)


@router.get("/{member_id}", response_model=MemberDetailOut)
def read_member(member_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_staff)):
    return member_service.detail_out(db, member_service.get_member(db, member_id, user), user)


@router.patch("/{member_id}", response_model=MemberDetailOut)
def update_member(member_id: int, payload: MemberUpdate, request: Request,
                  db: Session = Depends(get_db), user: User = Depends(front_desk)):
    member = member_service.update_member(db, member_id, payload, user, get_client_ip(request))
    return member_service.detail_out(db, member, user)


@router.delete("/{member_id}", response_model=MessageOut)
def delete_member(member_id: int, request: Request, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    """Soft delete: hides the member but keeps all history."""
    member_service.soft_delete(db, member_id, admin, get_client_ip(request))
    return MessageOut(message="Member deleted")


@router.post("/{member_id}/restore", response_model=MemberDetailOut)
def restore_member(member_id: int, request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    member = member_service.restore(db, member_id, admin, get_client_ip(request))
    return member_service.detail_out(db, member, admin)


# ----------------------------------------------------------------- memberships
@router.get("/{member_id}/memberships", response_model=list[MembershipOut])
def membership_history(member_id: int, db: Session = Depends(get_db), user: User = Depends(front_desk)):
    member = member_service.get_member(db, member_id, user)
    today = gym_today()
    return [membership_service.membership_out(m, today)
            for m in membership_service.list_for_member(db, member.id)]


@router.post("/{member_id}/memberships", response_model=MembershipOut, status_code=http.HTTP_201_CREATED)
def assign_plan(member_id: int, payload: AssignMembershipIn, request: Request,
                db: Session = Depends(get_db), user: User = Depends(front_desk)):
    membership = membership_service.assign_plan(
        db, member_id, payload.plan_id, payload.start_date, user, get_client_ip(request))
    return membership_service.membership_out(membership, gym_today())


@router.post("/{member_id}/renew", response_model=MembershipOut, status_code=http.HTTP_201_CREATED)
def renew_membership(member_id: int, payload: RenewMembershipIn, request: Request,
                     db: Session = Depends(get_db), user: User = Depends(front_desk)):
    membership = membership_service.renew(
        db, member_id, payload.plan_id, payload.start_date, user, get_client_ip(request))
    return membership_service.membership_out(membership, gym_today())


@router.post("/{member_id}/memberships/{membership_id}/cancel", response_model=MembershipOut)
def cancel_membership(member_id: int, membership_id: int, request: Request,
                      db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    membership = membership_service.cancel(db, member_id, membership_id, admin, get_client_ip(request))
    return membership_service.membership_out(membership, gym_today())


# ----------------------------------------------------------------- photo
@router.post("/{member_id}/photo", response_model=MemberDetailOut)
def upload_photo(member_id: int, request: Request, file: UploadFile = File(...),
                 db: Session = Depends(get_db), user: User = Depends(front_desk)):
    data = file.file.read(MAX_PHOTO_BYTES + 1)  # never read more than the limit
    member = member_service.set_photo(db, member_id, data, user, get_client_ip(request))
    return member_service.detail_out(db, member, user)


@router.get("/{member_id}/photo")
def download_photo(member_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_staff)):
    """Photos are private: only logged-in staff who may see this member can fetch them."""
    member = member_service.get_member(db, member_id, user)
    path, media_type = photo_service.resolve(member.photo_path)
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.delete("/{member_id}/photo", response_model=MemberDetailOut)
def delete_photo(member_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(front_desk)):
    member = member_service.remove_photo(db, member_id, user, get_client_ip(request))
    return member_service.detail_out(db, member, user)
