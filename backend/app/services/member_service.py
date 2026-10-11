"""Members: register, search, view, edit, soft-delete, photo."""
import uuid
from datetime import timedelta
from typing import Optional

from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.constants import ROLE_ADMIN, ROLE_TRAINER
from app.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models import Member, Membership, StaffProfile, User
from app.schemas.member import MemberCreate, MemberDetailOut, MemberListItem, MemberUpdate, TrainerRef
from app.services import membership_service, photo_service, settings_service
from app.services.audit_service import log_action
from app.services.membership_rules import MembershipSummary, summarize
from app.utils.dates import gym_today

SORT_COLUMNS = {
    "full_name": Member.full_name,
    "registration_date": Member.registration_date,
    "member_code": Member.member_code,
    "created_at": Member.created_at,
}
REQUIRED_ON_UPDATE = {"full_name", "phone", "status"}
EDITABLE_FIELDS = (
    "full_name", "phone", "email", "gender", "date_of_birth", "address",
    "emergency_contact_name", "emergency_contact_phone", "status", "assigned_trainer_id",
)


# ----------------------------------------------------------------- helpers
def _profile_id(user: User) -> Optional[int]:
    return user.staff_profile.id if user.staff_profile else None


def can_view_medical(member: Member, user: User) -> bool:
    """Admin always. A Trainer only for members assigned to them. Receptionists never."""
    if user.role.name == ROLE_ADMIN:
        return True
    if user.role.name == ROLE_TRAINER:
        profile_id = _profile_id(user)
        return profile_id is not None and member.assigned_trainer_id == profile_id
    return False


def _snapshot(member: Member) -> dict:
    """For the audit log. Medical notes are deliberately NOT copied into the log."""
    return {
        "member_code": member.member_code, "full_name": member.full_name, "phone": member.phone,
        "email": member.email, "gender": member.gender, "date_of_birth": member.date_of_birth,
        "address": member.address, "emergency_contact_name": member.emergency_contact_name,
        "emergency_contact_phone": member.emergency_contact_phone, "status": member.status,
        "assigned_trainer_id": member.assigned_trainer_id, "is_deleted": member.is_deleted,
    }


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_trainer(db: Session, trainer_id: int) -> None:
    profile = db.get(StaffProfile, trainer_id)
    if (profile is None or profile.user.role.name != ROLE_TRAINER
            or profile.status != "active" or not profile.user.is_active):
        raise BadRequestError("The assigned trainer must be an active trainer")


def _phone_conflict(db: Session, phone: str, exclude_id: Optional[int] = None) -> None:
    stmt = select(Member).where(Member.phone == phone)
    if exclude_id is not None:
        stmt = stmt.where(Member.id != exclude_id)
    existing = db.scalar(stmt)
    if existing is None:
        return
    if existing.is_deleted:
        raise ConflictError(
            f"A deleted member record ({existing.member_code}) already uses this phone number. "
            "Ask an Admin to restore it."
        )
    raise ConflictError(f"A member with this phone number already exists ({existing.member_code})")


# ----------------------------------------------------------------- reading
def get_member(db: Session, member_id: int, user: User, *, include_deleted: bool = False) -> Member:
    member = db.get(Member, member_id)
    if member is None or (member.is_deleted and not include_deleted):
        raise NotFoundError("Member not found")
    if user.role.name == ROLE_TRAINER:
        profile_id = _profile_id(user)
        # 404 (not 403): a trainer must not learn that other members exist.
        if profile_id is None or member.assigned_trainer_id != profile_id:
            raise NotFoundError("Member not found")
    return member


def _load_memberships(db: Session, member_ids: list[int]) -> dict[int, list[Membership]]:
    grouped: dict[int, list[Membership]] = {member_id: [] for member_id in member_ids}
    if not member_ids:
        return grouped
    stmt = (
        select(Membership).options(joinedload(Membership.plan))
        .where(Membership.member_id.in_(member_ids), Membership.status != "cancelled")
    )
    for membership in db.scalars(stmt).unique().all():
        grouped[membership.member_id].append(membership)
    return grouped


def _summaries(db: Session, members: list[Member]) -> dict[int, MembershipSummary]:
    today = gym_today()
    alert_days = settings_service.get_int(db, "expiry_alert_days", 7)
    grouped = _load_memberships(db, [m.id for m in members])
    return {m.id: summarize(grouped[m.id], m.status, today, alert_days) for m in members}


def _list_fields(member: Member, summary: MembershipSummary) -> dict:
    trainer = member.assigned_trainer
    return dict(
        id=member.id, member_code=member.member_code, full_name=member.full_name,
        phone=member.phone, email=member.email, gender=member.gender, status=member.status,
        registration_date=member.registration_date,
        membership_status=summary.membership_status, plan_name=summary.plan_name,
        expires_on=summary.expires_on, days_left=summary.days_left,
        expiring_soon=summary.expiring_soon,
        assigned_trainer=TrainerRef(id=trainer.id, full_name=trainer.user.full_name) if trainer else None,
        has_photo=bool(member.photo_path),
    )


def list_item_out(member: Member, summary: MembershipSummary) -> MemberListItem:
    return MemberListItem(**_list_fields(member, summary))


def detail_out(db: Session, member: Member, user: User) -> MemberDetailOut:
    summary = _summaries(db, [member])[member.id]
    visible = can_view_medical(member, user)
    current = (membership_service.membership_out(summary.current, gym_today())
               if summary.current is not None else None)
    return MemberDetailOut(
        **_list_fields(member, summary),
        date_of_birth=member.date_of_birth, address=member.address,
        emergency_contact_name=member.emergency_contact_name,
        emergency_contact_phone=member.emergency_contact_phone,
        photo_url=f"/api/members/{member.id}/photo" if member.photo_path else None,
        medical_notes=member.medical_notes if visible else None,
        medical_notes_visible=visible,
        current_membership=current,
        is_deleted=member.is_deleted,
        created_at=member.created_at, updated_at=member.updated_at,
    )


def list_members(
    db: Session, user: User, *, search: Optional[str], status: Optional[str],
    expiring_soon: bool, trainer_id: Optional[int], deleted: bool,
    sort_by: str, order: str, page: int, page_size: int,
) -> tuple[list[MemberListItem], int]:
    if deleted and user.role.name != ROLE_ADMIN:
        raise ForbiddenError("Only an Admin can view deleted members")

    today = gym_today()
    alert_days = settings_service.get_int(db, "expiry_alert_days", 7)

    # Reusable "does this member have ..." questions, asked inside SQL.
    def has_any():
        return exists().where(Membership.member_id == Member.id, Membership.status != "cancelled")

    def covers_today():
        return exists().where(
            Membership.member_id == Member.id, Membership.status != "cancelled",
            Membership.start_date <= today, Membership.end_date >= today,
        )

    def starts_later():
        return exists().where(
            Membership.member_id == Member.id, Membership.status != "cancelled",
            Membership.start_date > today,
        )

    latest_end = (
        select(func.max(Membership.end_date))
        .where(Membership.member_id == Member.id, Membership.status != "cancelled")
        .scalar_subquery()
    )

    conditions = [Member.is_deleted.is_(deleted)]

    if user.role.name == ROLE_TRAINER:
        profile_id = _profile_id(user)
        if profile_id is None:
            return [], 0
        conditions.append(Member.assigned_trainer_id == profile_id)
    elif trainer_id is not None:
        conditions.append(Member.assigned_trainer_id == trainer_id)

    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        conditions.append(or_(
            Member.full_name.ilike(pattern, escape="\\"),
            Member.phone.ilike(pattern, escape="\\"),
            Member.member_code.ilike(pattern, escape="\\"),
        ))

    is_active_member = Member.status == "active"
    if status == "inactive":
        conditions.append(Member.status == "inactive")
    elif status == "active":
        conditions += [is_active_member, covers_today()]
    elif status == "upcoming":
        conditions += [is_active_member, not_(covers_today()), starts_later()]
    elif status == "expired":
        conditions += [is_active_member, not_(covers_today()), not_(starts_later()), has_any()]
    elif status == "no_membership":
        conditions += [is_active_member, not_(has_any())]

    if expiring_soon:
        conditions += [
            is_active_member, covers_today(),
            latest_end >= today, latest_end <= today + timedelta(days=alert_days),
        ]

    total = db.scalar(select(func.count(Member.id)).where(and_(*conditions))) or 0

    sort_column = SORT_COLUMNS.get(sort_by, Member.full_name)
    direction = sort_column.desc() if order == "desc" else sort_column.asc()
    stmt = (
        select(Member).where(and_(*conditions))
        .options(selectinload(Member.assigned_trainer))
        .order_by(direction, Member.id)
        .offset((page - 1) * page_size).limit(page_size)
    )
    members = list(db.scalars(stmt).all())
    summaries = _summaries(db, members)
    return [list_item_out(m, summaries[m.id]) for m in members], total


# ----------------------------------------------------------------- writing
def create_member(db: Session, data: MemberCreate, actor: User, ip: Optional[str]) -> Member:
    _phone_conflict(db, data.phone)
    if data.assigned_trainer_id is not None:
        _validate_trainer(db, data.assigned_trainer_id)
    plan = membership_service.get_assignable_plan(db, data.plan_id) if data.plan_id is not None else None

    member = Member(
        member_code=f"TMP-{uuid.uuid4().hex[:15]}",  # replaced below, once the id is known
        full_name=data.full_name, phone=data.phone, email=data.email, gender=data.gender,
        date_of_birth=data.date_of_birth, address=data.address,
        emergency_contact_name=data.emergency_contact_name,
        emergency_contact_phone=data.emergency_contact_phone,
        medical_notes=data.medical_notes,
        registration_date=data.registration_date or gym_today(),
        status="active", assigned_trainer_id=data.assigned_trainer_id, created_by=actor.id,
    )
    # One transaction: member + code + optional first membership + audit row.
    db.add(member)
    db.flush()
    member.member_code = f"GF-{member.id:06d}"  # unique without any race between two receptionists
    if plan is not None:
        membership_service.insert_membership(db, member, plan, data.membership_start_date, actor, ip)
    log_action(db, user_id=actor.id, action="member.create", entity_type="member",
               entity_id=member.id, new=_snapshot(member), ip=ip)
    db.commit()
    db.refresh(member)
    return member


def update_member(db: Session, member_id: int, data: MemberUpdate, actor: User, ip: Optional[str]) -> Member:
    member = get_member(db, member_id, actor)
    changes = data.model_dump(exclude_unset=True)

    for field in changes:
        if field in REQUIRED_ON_UPDATE and changes[field] is None:
            raise BadRequestError(f"'{field}' cannot be empty")
    if "medical_notes" in changes and actor.role.name != ROLE_ADMIN:
        raise ForbiddenError("Only an Admin can change medical notes")
    if "phone" in changes and changes["phone"] != member.phone:
        _phone_conflict(db, changes["phone"], exclude_id=member.id)
    if changes.get("assigned_trainer_id") is not None:
        _validate_trainer(db, changes["assigned_trainer_id"])

    old = _snapshot(member)
    for field in EDITABLE_FIELDS:
        if field in changes:
            setattr(member, field, changes[field])
    if "medical_notes" in changes:
        member.medical_notes = changes["medical_notes"]

    db.flush()
    new = _snapshot(member)
    if "medical_notes" in changes:
        new["medical_notes_changed"] = True
    log_action(db, user_id=actor.id, action="member.update", entity_type="member",
               entity_id=member.id, old=old, new=new, ip=ip)
    db.commit()
    db.refresh(member)
    return member


def soft_delete(db: Session, member_id: int, actor: User, ip: Optional[str]) -> None:
    """The row stays (payments, attendance and memberships refer to it); it is just hidden."""
    member = get_member(db, member_id, actor)
    member.is_deleted = True
    log_action(db, user_id=actor.id, action="member.delete", entity_type="member",
               entity_id=member.id, old={"is_deleted": False}, new={"is_deleted": True}, ip=ip)
    db.commit()


def restore(db: Session, member_id: int, actor: User, ip: Optional[str]) -> Member:
    member = get_member(db, member_id, actor, include_deleted=True)
    if not member.is_deleted:
        raise BadRequestError("This member is not deleted")
    member.is_deleted = False
    log_action(db, user_id=actor.id, action="member.restore", entity_type="member",
               entity_id=member.id, old={"is_deleted": True}, new={"is_deleted": False}, ip=ip)
    db.commit()
    db.refresh(member)
    return member


# ----------------------------------------------------------------- photo
def set_photo(db: Session, member_id: int, data: bytes, actor: User, ip: Optional[str]) -> Member:
    member = get_member(db, member_id, actor)
    new_file = photo_service.validate_and_save(member.member_code, data)
    old_file = member.photo_path
    member.photo_path = new_file
    log_action(db, user_id=actor.id, action="member.photo_update", entity_type="member",
               entity_id=member.id, ip=ip)
    try:
        db.commit()
    except Exception:
        db.rollback()
        photo_service.delete_file(new_file)  # do not leave an orphan file behind
        raise
    photo_service.delete_file(old_file)
    db.refresh(member)
    return member


def remove_photo(db: Session, member_id: int, actor: User, ip: Optional[str]) -> Member:
    member = get_member(db, member_id, actor)
    old_file = member.photo_path
    if not old_file:
        raise NotFoundError("This member has no photo")
    member.photo_path = None
    log_action(db, user_id=actor.id, action="member.photo_remove", entity_type="member",
               entity_id=member.id, ip=ip)
    db.commit()
    photo_service.delete_file(old_file)
    db.refresh(member)
    return member
