"""Business logic for staff accounts (users + staff_profiles)."""
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_TRAINER
from app.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models import Role, StaffProfile, User
from app.schemas.staff import StaffCreate, StaffUpdate
from app.security import hash_password
from app.services.audit_service import log_action

SORT_COLUMNS = {
    "full_name": User.full_name,
    "created_at": StaffProfile.created_at,
    "hire_date": StaffProfile.hire_date,
}

# These fields may not be set to null.
REQUIRED_ON_UPDATE = {"full_name", "role", "phone", "status"}


def _snapshot(profile: StaffProfile) -> dict:
    """What we write to the audit log (never contains the password hash)."""
    return {
        "full_name": profile.user.full_name,
        "email": profile.user.email,
        "role": profile.user.role.name,
        "phone": profile.phone,
        "address": profile.address,
        "specialization": profile.specialization,
        "working_schedule": profile.working_schedule,
        "hire_date": profile.hire_date,
        "salary": profile.salary,
        "status": profile.status,
        "is_active": profile.user.is_active,
    }


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _other_active_admins(db: Session, exclude_user_id: int) -> int:
    stmt = (
        select(func.count(User.id))
        .join(Role, User.role_id == Role.id)
        .where(Role.name == ROLE_ADMIN, User.is_active.is_(True), User.id != exclude_user_id)
    )
    return db.scalar(stmt) or 0


def get_staff(db: Session, staff_id: int) -> StaffProfile:
    profile = db.get(StaffProfile, staff_id)
    if profile is None:
        raise NotFoundError("Staff member not found")
    return profile


def create_staff(db: Session, data: StaffCreate, actor: User, ip: Optional[str]) -> StaffProfile:
    role = db.scalar(select(Role).where(Role.name == data.role))
    if role is None:
        raise BadRequestError("Unknown role")
    if db.scalar(select(User.id).where(User.email == data.email)) is not None:
        raise ConflictError("A user with this email already exists")

    user = User(
        role_id=role.id,
        full_name=data.full_name,
        email=data.email,
        password_hash=hash_password(data.password),
        is_active=True,
    )
    profile = StaffProfile(
        user=user,
        phone=data.phone,
        address=data.address,
        specialization=data.specialization,
        working_schedule=data.working_schedule,
        hire_date=data.hire_date,
        salary=data.salary,
        status="active",
    )
    # One transaction: the user, the profile and the audit row are saved together or not at all.
    db.add(profile)
    db.flush()
    log_action(db, user_id=actor.id, action="staff.create", entity_type="staff_profile",
               entity_id=profile.id, new=_snapshot(profile), ip=ip)
    db.commit()
    db.refresh(profile)
    return profile


def list_staff(
    db: Session,
    *,
    search: Optional[str],
    role: Optional[str],
    status: Optional[str],
    sort_by: str,
    order: str,
    page: int,
    page_size: int,
) -> tuple[list[StaffProfile], int]:
    filters = []
    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        filters.append(
            or_(
                User.full_name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
                StaffProfile.phone.ilike(pattern, escape="\\"),
                StaffProfile.specialization.ilike(pattern, escape="\\"),
            )
        )
    if role:
        filters.append(Role.name == role)
    if status:
        filters.append(StaffProfile.status == status)

    count_stmt = (
        select(func.count(StaffProfile.id))
        .select_from(StaffProfile)
        .join(StaffProfile.user)
        .join(User.role)
    )
    list_stmt = select(StaffProfile).join(StaffProfile.user).join(User.role)
    if filters:
        count_stmt = count_stmt.where(*filters)
        list_stmt = list_stmt.where(*filters)

    sort_column = SORT_COLUMNS.get(sort_by, User.full_name)
    direction = sort_column.desc() if order == "desc" else sort_column.asc()
    list_stmt = list_stmt.order_by(direction, StaffProfile.id).offset((page - 1) * page_size).limit(page_size)

    total = db.scalar(count_stmt) or 0
    items = list(db.scalars(list_stmt).unique().all())
    return items, total


def list_active_trainers(db: Session) -> list[StaffProfile]:
    stmt = (
        select(StaffProfile)
        .join(StaffProfile.user)
        .join(User.role)
        .where(Role.name == ROLE_TRAINER, StaffProfile.status == "active", User.is_active.is_(True))
        .order_by(User.full_name)
    )
    return list(db.scalars(stmt).unique().all())


def update_staff(db: Session, staff_id: int, data: StaffUpdate, actor: User,
                 ip: Optional[str]) -> StaffProfile:
    profile = get_staff(db, staff_id)
    user = profile.user
    changes = data.model_dump(exclude_unset=True)

    for field in changes:
        if field in REQUIRED_ON_UPDATE and changes[field] is None:
            raise BadRequestError(f"'{field}' cannot be empty")

    old = _snapshot(profile)
    is_self = user.id == actor.id

    if "role" in changes and changes["role"] != user.role.name:
        if is_self:
            raise BadRequestError("You cannot change your own role")
        new_role = db.scalar(select(Role).where(Role.name == changes["role"]))
        if new_role is None:
            raise BadRequestError("Unknown role")
        if user.role.name == ROLE_ADMIN and _other_active_admins(db, user.id) == 0:
            raise BadRequestError("At least one active Admin must remain")
        user.role = new_role

    if "status" in changes:
        becoming_inactive = changes["status"] == "inactive"
        if becoming_inactive and is_self:
            raise BadRequestError("You cannot deactivate your own account")
        if becoming_inactive and user.role.name == ROLE_ADMIN and _other_active_admins(db, user.id) == 0:
            raise BadRequestError("At least one active Admin must remain")
        profile.status = changes["status"]
        user.is_active = not becoming_inactive  # login access follows the status

    if "full_name" in changes:
        user.full_name = changes["full_name"]
    for field in ("phone", "address", "specialization", "working_schedule", "hire_date", "salary"):
        if field in changes:
            setattr(profile, field, changes[field])

    db.flush()
    log_action(db, user_id=actor.id, action="staff.update", entity_type="staff_profile",
               entity_id=profile.id, old=old, new=_snapshot(profile), ip=ip)
    db.commit()
    db.refresh(profile)
    return profile


def deactivate_staff(db: Session, staff_id: int, actor: User, ip: Optional[str]) -> StaffProfile:
    """Soft delete: the record stays (payments, workouts and logs refer to it)."""
    return update_staff(db, staff_id, StaffUpdate(status="inactive"), actor, ip)


def reset_password(db: Session, staff_id: int, new_password: str, actor: User,
                   ip: Optional[str]) -> None:
    profile = get_staff(db, staff_id)
    profile.user.password_hash = hash_password(new_password)
    log_action(db, user_id=actor.id, action="staff.password_reset", entity_type="staff_profile",
               entity_id=profile.id, ip=ip)  # the password itself is never logged
    db.commit()
