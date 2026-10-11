"""Assigning plans to members, renewals, history, cancellation."""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, joinedload

from app.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models import Member, Membership, MembershipPlan, User
from app.schemas.membership import MembershipOut
from app.services.audit_service import log_action
from app.services.membership_rules import compute_end_date, membership_state
from app.utils.dates import gym_today

MAX_DAYS_PAST = 365
MAX_DAYS_FUTURE = 365


def membership_out(m: Membership, today: date) -> MembershipOut:
    return MembershipOut(
        id=m.id, member_id=m.member_id, plan_id=m.plan_id, plan_name=m.plan.name,
        start_date=m.start_date, end_date=m.end_date,
        price_at_purchase=m.price_at_purchase, is_renewal=m.is_renewal,
        state=membership_state(m.start_date, m.end_date, m.status == "cancelled", today),
        created_at=m.created_at,
    )


def get_assignable_plan(db: Session, plan_id: int) -> MembershipPlan:
    plan = db.get(MembershipPlan, plan_id)
    if plan is None:
        raise NotFoundError("Plan not found")
    if not plan.is_active:
        raise BadRequestError("This plan is not active")
    if plan.plan_type != "membership":
        raise BadRequestError("Add-on plans are billed separately and cannot start a membership period")
    return plan


def _default_start(db: Session, member_id: int, today: date) -> date:
    """Renewals chain: if the member is still covered, the new period starts the day after."""
    latest_end = db.scalar(
        select(func.max(Membership.end_date)).where(
            Membership.member_id == member_id, Membership.status != "cancelled"
        )
    )
    if latest_end is not None and latest_end >= today:
        return latest_end + timedelta(days=1)
    return today


def _overlaps_existing(db: Session, member_id: int, start: date, end: date) -> bool:
    stmt = select(
        exists().where(
            Membership.member_id == member_id,
            Membership.status != "cancelled",
            Membership.start_date <= end,
            Membership.end_date >= start,
        )
    )
    return bool(db.scalar(stmt))


def insert_membership(
    db: Session, member: Member, plan: MembershipPlan, start_date: Optional[date],
    actor: User, ip: Optional[str], *, action: str = "membership.create",
) -> Membership:
    """Adds the membership to the CURRENT transaction (the caller commits)."""
    if member.status != "active":
        raise BadRequestError("This member is inactive. Reactivate the member first")

    today = gym_today()
    if start_date is None:
        start_date = _default_start(db, member.id, today)
    elif not (today - timedelta(days=MAX_DAYS_PAST) <= start_date <= today + timedelta(days=MAX_DAYS_FUTURE)):
        raise BadRequestError("Start date must be within one year of today")

    end_date = compute_end_date(start_date, plan.duration_days)
    if _overlaps_existing(db, member.id, start_date, end_date):
        raise ConflictError("This period overlaps an existing membership of this member")

    has_history = bool(db.scalar(select(exists().where(
        Membership.member_id == member.id, Membership.status != "cancelled"))))

    membership = Membership(
        member_id=member.id, plan_id=plan.id, start_date=start_date, end_date=end_date,
        price_at_purchase=plan.price, is_renewal=has_history, status="active",
        created_by=actor.id,
    )
    db.add(membership)
    db.flush()
    log_action(db, user_id=actor.id, action=action, entity_type="membership",
               entity_id=membership.id,
               new={"member_id": member.id, "plan": plan.name, "start_date": start_date,
                    "end_date": end_date, "price": plan.price}, ip=ip)
    return membership


def _lock_member(db: Session, member_id: int) -> Member:
    """SELECT ... FOR UPDATE: two receptionists clicking 'renew' at the same moment
    are handled one after the other, so the overlap check cannot be bypassed."""
    member = db.scalar(select(Member).where(Member.id == member_id).with_for_update())
    if member is None or member.is_deleted:
        raise NotFoundError("Member not found")
    return member


def assign_plan(db: Session, member_id: int, plan_id: int, start_date: Optional[date],
                actor: User, ip: Optional[str]) -> Membership:
    member = _lock_member(db, member_id)
    plan = get_assignable_plan(db, plan_id)
    membership = insert_membership(db, member, plan, start_date, actor, ip)
    db.commit()
    db.refresh(membership)
    return membership


def renew(db: Session, member_id: int, plan_id: Optional[int], start_date: Optional[date],
          actor: User, ip: Optional[str]) -> Membership:
    member = _lock_member(db, member_id)
    if plan_id is None:
        last = db.scalar(
            select(Membership).where(Membership.member_id == member_id, Membership.status != "cancelled")
            .order_by(Membership.end_date.desc(), Membership.id.desc()).limit(1)
        )
        if last is None:
            raise BadRequestError("This member has no previous membership. Assign a plan instead")
        plan_id = last.plan_id
    plan = get_assignable_plan(db, plan_id)
    membership = insert_membership(db, member, plan, start_date, actor, ip, action="membership.renew")
    db.commit()
    db.refresh(membership)
    return membership


def list_for_member(db: Session, member_id: int) -> list[Membership]:
    stmt = (
        select(Membership).options(joinedload(Membership.plan))
        .where(Membership.member_id == member_id)
        .order_by(Membership.start_date.desc(), Membership.id.desc())
    )
    return list(db.scalars(stmt).unique().all())


def cancel(db: Session, member_id: int, membership_id: int, actor: User, ip: Optional[str]) -> Membership:
    membership = db.get(Membership, membership_id)
    if membership is None or membership.member_id != member_id:
        raise NotFoundError("Membership not found")
    if membership.status == "cancelled":
        raise BadRequestError("This membership is already cancelled")
    membership.status = "cancelled"
    db.flush()
    log_action(db, user_id=actor.id, action="membership.cancel", entity_type="membership",
               entity_id=membership.id, old={"status": "active"}, new={"status": "cancelled"}, ip=ip)
    db.commit()
    db.refresh(membership)
    return membership
