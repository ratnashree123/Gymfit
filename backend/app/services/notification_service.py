"""Notifications: membership expiry, expired memberships, overdue payments, maintenance.

Each staff member gets their own rows (so each has their own read / unread state):
  * Admins and Receptionists: everything.
  * Trainers: only the membership notices of their own members.
The notices are re-computed from the real data ("sync"), so they appear on their own and disappear
when the cause is gone (member renewed, invoice paid, item repaired). There is no scheduler, so the
sync runs when notifications are opened, at most every few minutes, or when asked for.
"""
import threading
import time
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.constants import ROLE_ADMIN, ROLE_RECEPTIONIST, ROLE_TRAINER
from app.exceptions import NotFoundError
from app.models import Equipment, Invoice, Member, Notification, User
from app.schemas.dashboard import NotificationOut, SyncOut
from app.services import equipment_service, member_filters, member_service, settings_service
from app.services.notification_rules import (
    AUTO_TYPES, MESSAGE_MAX, TITLE_MAX, Desired, diff, expired_notice, expiring_notice,
    maintenance_notice, overdue_notice, trim,
)
from app.utils.dates import gym_today

MIN_INTERVAL = 300.0   # seconds between automatic syncs
FORCE_INTERVAL = 30.0  # seconds between syncs that were asked for
_lock = threading.Lock()
_last_sync = 0.0


def reset_throttle() -> None:
    global _last_sync
    with _lock:
        _last_sync = 0.0


# ------------------------------------------------------------------ what should exist
def _audiences(db: Session) -> tuple[list[int], dict[int, int]]:
    users = db.scalars(select(User).where(User.is_active.is_(True)).options(selectinload(User.staff_profile))).all()
    front = [u.id for u in users if u.role.name in (ROLE_ADMIN, ROLE_RECEPTIONIST)]
    trainers = {u.staff_profile.id: u.id for u in users
                if u.role.name == ROLE_TRAINER and u.staff_profile is not None and u.staff_profile.status == "active"}
    return front, trainers


def compute_desired(db: Session) -> list[Desired]:
    today = gym_today()
    alert_days = settings_service.get_int(db, "expiry_alert_days", 7)
    expired_window = settings_service.get_int(db, "notification_expired_days", 30)
    currency = settings_service.get_str(db, "currency_symbol", "\u20b9")
    front, trainer_users = _audiences(db)
    desired: list[Desired] = []

    # ---- memberships (front desk, plus the member's own trainer)
    not_deleted = Member.is_deleted.is_(False)
    expiring = list(db.scalars(select(Member).where(
        not_deleted, *member_filters.expiring_conditions(today, alert_days))).all())
    lapsed = list(db.scalars(select(Member).where(
        not_deleted, *member_filters.status_conditions("expired", today),
        member_filters.latest_end() >= today - timedelta(days=expired_window))).all())
    summaries = member_service.summaries(db, expiring + lapsed)

    def audience(member: Member) -> list[int]:
        trainer_user = trainer_users.get(member.assigned_trainer_id)
        return front + ([trainer_user] if trainer_user is not None else [])

    for m in expiring:
        s = summaries[m.id]
        title, message = expiring_notice(m.full_name, m.member_code, s.plan_name or "Membership", s.expires_on, s.days_left)
        desired += [Desired(uid, "membership_expiring", "member", m.id, title, message) for uid in audience(m)]
    for m in lapsed:
        s = summaries[m.id]
        title, message = expired_notice(m.full_name, m.member_code, s.plan_name or "Membership", s.expires_on)
        desired += [Desired(uid, "membership_expired", "member", m.id, title, message) for uid in audience(m)]

    # ---- overdue payments (front desk)
    overdue = db.scalars(select(Invoice).where(
        Invoice.status.in_(("pending", "partial")), Invoice.due_date.is_not(None), Invoice.due_date < today)
        .options(selectinload(Invoice.member), selectinload(Invoice.payments))).all()
    for inv in overdue:
        if inv.member.is_deleted:
            continue
        paid = sum((p.amount for p in inv.payments), inv.total_amount - inv.total_amount)
        balance = f"{currency}{inv.total_amount - paid:,.2f}"
        title, message = overdue_notice(inv.member.full_name, inv.member.member_code, inv.invoice_number, balance, inv.due_date)
        desired += [Desired(uid, "payment_pending", "invoice", inv.id, title, message) for uid in front]

    # ---- equipment (front desk). 'soon' and 'urgent' are separate notices, so an item that gets worse
    # raises a NEW unread notification instead of silently changing a read one.
    items = list(db.scalars(select(Equipment).where(Equipment.is_archived.is_(False))).all())
    due_map = equipment_service.due_dates_for(db, [e.id for e in items])
    days = equipment_service.alert_days(db)
    for eq in items:
        u = equipment_service.urgency_for(eq, due_map, today, days)
        if u.level == "ok":
            continue
        title, message = maintenance_notice(eq.name, eq.equipment_code, u.level, u.message)
        desired += [Desired(uid, "maintenance_due", f"equipment_{u.level}", eq.id, title, message) for uid in front]

    return [Desired(d.user_id, d.type, d.related_type, d.related_id,
                    trim(d.title, TITLE_MAX), trim(d.message, MESSAGE_MAX)) for d in desired]


# ------------------------------------------------------------------ syncing
def sync(db: Session) -> SyncOut:
    desired = compute_desired(db)
    existing = list(db.scalars(select(Notification).where(Notification.type.in_(AUTO_TYPES))).all())
    changes = diff(existing, desired)
    by_id = {n.id: n for n in existing}

    for notification_id in changes.delete_ids:
        db.delete(by_id[notification_id])
    for notification_id, want in changes.update:
        row = by_id[notification_id]
        row.title, row.message = want.title, want.message  # keeps is_read as it was
    for want in changes.create:
        db.add(Notification(user_id=want.user_id, type=want.type, title=want.title, message=want.message,
                            related_type=want.related_type, related_id=want.related_id, is_read=False))
    db.commit()
    return SyncOut(skipped=False, created=len(changes.create), updated=len(changes.update),
                   removed=len(changes.delete_ids))


def maybe_sync(db: Session, force: bool = False) -> SyncOut:
    """Runs the sync unless one ran very recently."""
    global _last_sync
    interval = FORCE_INTERVAL if force else MIN_INTERVAL
    with _lock:
        now = time.monotonic()
        if _last_sync and now - _last_sync < interval:
            return SyncOut(skipped=True)
        previous, _last_sync = _last_sync, now
    try:
        return sync(db)
    except Exception:
        with _lock:
            _last_sync = previous
        raise


# ------------------------------------------------------------------ one user's notifications
def to_out(n: Notification) -> NotificationOut:
    return NotificationOut(id=n.id, type=n.type, title=n.title, message=n.message,
                           related_type=n.related_type, related_id=n.related_id,
                           is_read=n.is_read, created_at=n.created_at)


def unread_count(db: Session, user: User) -> int:
    return db.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user.id, Notification.is_read.is_(False))) or 0


def list_for_user(db: Session, user: User, *, unread_only: bool, type_: Optional[str], page: int, page_size: int):
    maybe_sync(db)
    conditions = [Notification.user_id == user.id]
    if unread_only:
        conditions.append(Notification.is_read.is_(False))
    if type_:
        conditions.append(Notification.type == type_)
    total = db.scalar(select(func.count(Notification.id)).where(*conditions)) or 0
    rows = db.scalars(select(Notification).where(*conditions)
                      .order_by(Notification.created_at.desc(), Notification.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return [to_out(n) for n in rows], total, unread_count(db, user)


def mark_read(db: Session, user: User, notification_id: int) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:  # somebody else's notification is simply "not found"
        raise NotFoundError("Notification not found")
    n.is_read = True
    db.commit()
    db.refresh(n)
    return n


def mark_all_read(db: Session, user: User) -> int:
    rows = db.scalars(select(Notification).where(
        Notification.user_id == user.id, Notification.is_read.is_(False))).all()
    for n in rows:
        n.is_read = True
    db.commit()
    return len(rows)
