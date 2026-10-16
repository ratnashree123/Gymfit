"""The dashboard: every number comes from the database, through the same rules as the other screens."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_TRAINER
from app.models import (
    Attendance, Equipment, Member, Membership, MembershipPlan, Payment, Role, StaffProfile, User,
)
from app.models._common import utcnow
from app.schemas.dashboard import (
    DashboardAttendance, DashboardEquipment, DashboardMembers, DashboardMemberships, DashboardMoney,
    DashboardOut, DistributionSlice,
)
from app.services import (
    attendance_service, equipment_service, invoice_service, member_filters, member_service,
    notification_service, report_service, settings_service,
)
from app.utils.dates import gym_today, gym_tz
from app.utils.timezones import local_range_to_utc

REVENUE_MONTHS = 6


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _months_back(day: date, months: int) -> date:
    """First day of the month `months` months before day's month."""
    index = day.year * 12 + (day.month - 1) - months
    return date(index // 12, index % 12 + 1, 1)


def build(db: Session, user: User) -> DashboardOut:
    today, tz = gym_today(), gym_tz()
    alert_days = settings_service.get_int(db, "expiry_alert_days", 7)
    is_trainer, is_admin = user.role.name == ROLE_TRAINER, user.role.name == ROLE_ADMIN

    # A trainer's numbers cover only the members assigned to them.
    trainer_scope: list = []
    if is_trainer:
        profile_id = user.staff_profile.id if user.staff_profile else -1
        trainer_scope = [Member.assigned_trainer_id == profile_id]
    member_scope = [Member.is_deleted.is_(False), *trainer_scope]

    # ---- members and memberships
    counts = member_filters.status_counts(db, today, alert_days, member_scope)
    month_start = today.replace(day=1)
    members = DashboardMembers(
        total=counts["total"], active=counts["total"] - counts["inactive"], inactive=counts["inactive"],
        joined_this_month=db.scalar(select(func.count(Member.id)).where(
            *member_scope, Member.registration_date >= month_start)) or 0)
    memberships = DashboardMemberships(
        active=counts["active"], expiring_soon=counts["expiring_soon"], expired=counts["expired"],
        upcoming=counts["upcoming"], no_membership=counts["no_membership"], inactive=counts["inactive"],
        alert_days=alert_days)

    # ---- attendance (same rules as /api/attendance)
    day_start, day_end = local_range_to_utc(today, today, tz)
    stale_before = utcnow() - timedelta(hours=max(1, settings_service.get_int(db, "auto_checkout_hours", 8)))

    def attendance_count(*extra) -> int:
        stmt = select(func.count(Attendance.id)).join(Member, Member.id == Attendance.member_id)
        return db.scalar(stmt.where(*trainer_scope, *extra)) or 0

    attendance = DashboardAttendance(
        visits_today=attendance_count(Attendance.check_in_at >= day_start, Attendance.check_in_at < day_end),
        inside_now=attendance_count(Attendance.check_out_at.is_(None)),
        stale_inside=attendance_count(Attendance.check_out_at.is_(None), Attendance.check_in_at <= stale_before))

    # ---- money and staff (not for trainers)
    money = trainers_total = revenue_chart = None
    if not is_trainer:
        month_from, month_to = local_range_to_utc(month_start, today, tz)

        def collected(start, end):
            total, count = db.execute(select(func.coalesce(func.sum(Payment.amount), 0), func.count(Payment.id))
                                      .where(Payment.payment_date >= start, Payment.payment_date < end)).one()
            return _money(total), int(count)

        today_total, today_count = collected(day_start, day_end)
        pending = invoice_service.summary(db, None)
        money = DashboardMoney(
            collected_today=today_total, payments_today=today_count,
            collected_this_month=collected(month_from, month_to)[0],
            pending_count=pending.pending_count, overdue_count=pending.overdue_count,
            outstanding_total=pending.outstanding_total, overdue_total=pending.overdue_total)
        trainers_total = db.scalar(
            select(func.count(StaffProfile.id)).join(User, User.id == StaffProfile.user_id)
            .join(Role, Role.id == User.role_id)
            .where(Role.name == ROLE_TRAINER, StaffProfile.status == "active", User.is_active.is_(True))) or 0
    if is_admin:
        revenue_chart = report_service.revenue(db, "monthly", _months_back(today, REVENUE_MONTHS - 1), today)

    # ---- equipment (counts only, no prices)
    items = list(db.scalars(select(Equipment).where(Equipment.is_archived.is_(False))).all())
    due_map = equipment_service.due_dates_for(db, [e.id for e in items])
    days = equipment_service.alert_days(db)
    levels = [equipment_service.urgency_for(e, due_map, today, days).level for e in items]
    equipment = DashboardEquipment(
        records=len(items), total_quantity=sum(e.quantity for e in items),
        damaged=sum(1 for e in items if e.status == "damaged"),
        under_maintenance=sum(1 for e in items if e.status == "under_maintenance"),
        urgent=levels.count("urgent"), soon=levels.count("soon"))

    # ---- membership distribution: members with a running membership, by plan
    rows = db.execute(
        select(MembershipPlan.name, func.count(Membership.id))
        .join(Membership, Membership.plan_id == MembershipPlan.id)
        .join(Member, Member.id == Membership.member_id)
        .where(*member_scope, Member.status == "active", Membership.status != "cancelled",
               Membership.start_date <= today, Membership.end_date >= today)
        .group_by(MembershipPlan.id, MembershipPlan.name)
        .order_by(func.count(Membership.id).desc(), MembershipPlan.name)).all()
    distribution = [DistributionSlice(label=name, members=int(total)) for name, total in rows]

    # ---- recent activity (these services already apply the trainer scope)
    recent_members, _ = member_service.list_members(
        db, user, search=None, status=None, expiring_soon=False, trainer_id=None, deleted=False,
        sort_by="created_at", order="desc", page=1, page_size=5)
    recent_attendance, _ = attendance_service.list_attendance(
        db, user, member_id=None, status=None, search=None, period=None, on_date=None,
        date_from=None, date_to=None, page=1, page_size=5)

    return DashboardOut(
        role=user.role.name, scope="own_members" if is_trainer else "all", generated_at=utcnow(),
        members=members, memberships=memberships, attendance=attendance, money=money,
        trainers_total=trainers_total, equipment=equipment, revenue_chart=revenue_chart,
        membership_distribution=distribution, recent_members=recent_members,
        recent_attendance=recent_attendance, unread_notifications=notification_service.unread_count(db, user))
