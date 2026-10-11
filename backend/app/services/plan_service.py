"""Membership plans."""
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models import MembershipPlan, User
from app.schemas.plan import PlanCreate, PlanUpdate
from app.services.audit_service import log_action

REQUIRED_ON_UPDATE = {"name", "duration_days", "price", "is_active"}


def _snapshot(plan: MembershipPlan) -> dict:
    return {
        "name": plan.name, "plan_type": plan.plan_type, "duration_days": plan.duration_days,
        "price": plan.price, "description": plan.description, "benefits": plan.benefits,
        "is_active": plan.is_active,
    }


def _name_taken(db: Session, name: str, exclude_id: Optional[int] = None) -> bool:
    stmt = select(MembershipPlan.id).where(func.lower(MembershipPlan.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(MembershipPlan.id != exclude_id)
    return db.scalar(stmt) is not None


def list_plans(db: Session, *, active_only: bool, plan_type: Optional[str]) -> list[MembershipPlan]:
    stmt = select(MembershipPlan)
    if active_only:
        stmt = stmt.where(MembershipPlan.is_active.is_(True))
    if plan_type:
        stmt = stmt.where(MembershipPlan.plan_type == plan_type)
    return list(db.scalars(stmt.order_by(MembershipPlan.duration_days, MembershipPlan.name)).all())


def get_plan(db: Session, plan_id: int) -> MembershipPlan:
    plan = db.get(MembershipPlan, plan_id)
    if plan is None:
        raise NotFoundError("Plan not found")
    return plan


def create_plan(db: Session, data: PlanCreate, actor: User, ip: Optional[str]) -> MembershipPlan:
    if _name_taken(db, data.name):
        raise ConflictError("A plan with this name already exists")
    plan = MembershipPlan(
        name=data.name, plan_type=data.plan_type, duration_days=data.duration_days,
        price=data.price, description=data.description, benefits=data.benefits,
        is_active=data.is_active,
    )
    db.add(plan)
    db.flush()
    log_action(db, user_id=actor.id, action="plan.create", entity_type="membership_plan",
               entity_id=plan.id, new=_snapshot(plan), ip=ip)
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(db: Session, plan_id: int, data: PlanUpdate, actor: User, ip: Optional[str]) -> MembershipPlan:
    plan = get_plan(db, plan_id)
    changes = data.model_dump(exclude_unset=True)
    for field in changes:
        if field in REQUIRED_ON_UPDATE and changes[field] is None:
            raise BadRequestError(f"'{field}' cannot be empty")
    if "name" in changes and _name_taken(db, changes["name"], exclude_id=plan.id):
        raise ConflictError("A plan with this name already exists")

    old = _snapshot(plan)
    # Existing memberships keep the price they were bought at (price_at_purchase),
    # so changing the price here never rewrites history.
    for field, value in changes.items():
        setattr(plan, field, value)
    db.flush()
    log_action(db, user_id=actor.id, action="plan.update", entity_type="membership_plan",
               entity_id=plan.id, old=old, new=_snapshot(plan), ip=ip)
    db.commit()
    db.refresh(plan)
    return plan


def deactivate_plan(db: Session, plan_id: int, actor: User, ip: Optional[str]) -> MembershipPlan:
    """Plans are never deleted (memberships refer to them). Deactivating hides them."""
    return update_plan(db, plan_id, PlanUpdate(is_active=False), actor, ip)
