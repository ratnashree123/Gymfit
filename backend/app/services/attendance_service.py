"""Check-in, check-out, the 'who is inside' list, corrections and reports."""
import csv
import io
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.constants import ROLE_ADMIN, ROLE_TRAINER
from app.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models import Attendance, Member, Membership, User
from app.models._common import utcnow
from app.schemas.attendance import (
    AccessOut, AttendanceCorrection, AttendanceOut, AttendanceReport, LookupItem, SeriesPoint,
)
from app.schemas.billing import MemberRef
from app.services import settings_service
from app.services.attendance_rules import (
    AccessDecision, average_minutes, build_series, evaluate_access, is_stale, peak_of,
    period_range, visit_minutes,
)
from app.services.audit_service import log_action
from app.services.revenue_rules import csv_safe
from app.utils.dates import gym_today, gym_tz
from app.utils.timezones import format_local, local_range_to_utc, to_utc_naive, utc_to_local

MAX_VISIT = timedelta(hours=24)
FUTURE_SKEW = timedelta(minutes=5)
MAX_RANGE_DAYS = 366
FAR_FUTURE = datetime(9999, 1, 1)


# ------------------------------------------------------------------ small helpers
def _profile_id(user: User) -> Optional[int]:
    return user.staff_profile.id if user.staff_profile else None


def _stale_hours(db: Session) -> int:
    return max(1, settings_service.get_int(db, "auto_checkout_hours", 8))


def _loaders():
    return (selectinload(Attendance.member), selectinload(Attendance.checked_in_user),
            selectinload(Attendance.checked_out_user))


def to_out(visit: Attendance, now: datetime, tz, stale_hours: int) -> AttendanceOut:
    member = visit.member
    is_open = visit.check_out_at is None
    return AttendanceOut(
        id=visit.id,
        member=MemberRef(id=member.id, member_code=member.member_code, full_name=member.full_name),
        check_in_at=visit.check_in_at, check_in_local=format_local(visit.check_in_at, tz),
        check_out_at=visit.check_out_at,
        check_out_local=None if is_open else format_local(visit.check_out_at, tz),
        duration_minutes=visit.duration_minutes,
        minutes_inside=visit_minutes(visit.check_in_at, now) if is_open else None,
        status=visit.status,
        is_stale=is_open and is_stale(visit.check_in_at, now, stale_hours),
        checked_in_by_name=visit.checked_in_user.full_name if visit.checked_in_user else None,
        checked_out_by_name=visit.checked_out_user.full_name if visit.checked_out_user else None,
        notes=visit.notes,
    )


def _outs(db: Session, visits) -> list[AttendanceOut]:
    now, tz, hours = utcnow(), gym_tz(), _stale_hours(db)
    return [to_out(v, now, tz, hours) for v in visits]


def get_visit(db: Session, attendance_id: int) -> Attendance:
    visit = db.scalar(select(Attendance).where(Attendance.id == attendance_id).options(*_loaders()))
    if visit is None:
        raise NotFoundError("Attendance record not found")
    return visit


def visit_out(db: Session, attendance_id: int) -> AttendanceOut:
    return _outs(db, [get_visit(db, attendance_id)])[0]


def _lock_member(db: Session, member_id: int, *, allow_deleted: bool = False) -> Member:
    """SELECT ... FOR UPDATE: two desks checking the same member in at once run one after the other."""
    member = db.scalar(select(Member).where(Member.id == member_id).with_for_update())
    if member is None or (member.is_deleted and not allow_deleted):
        raise NotFoundError("Member not found")
    return member


def _open_visit(db: Session, member_id: int) -> Optional[Attendance]:
    return db.scalar(select(Attendance).where(
        Attendance.member_id == member_id, Attendance.check_out_at.is_(None)))


# ------------------------------------------------------------------ access
def _access_settings(db: Session) -> tuple[int, bool]:
    return (settings_service.get_int(db, "grace_period_days", 0),
            settings_service.get_bool(db, "allow_checkin_unpaid", False))


def _memberships_by_member(db: Session, member_ids: list[int]) -> dict[int, list[Membership]]:
    grouped: dict[int, list[Membership]] = {i: [] for i in member_ids}
    if member_ids:
        stmt = (select(Membership).options(selectinload(Membership.invoices))
                .where(Membership.member_id.in_(member_ids), Membership.status != "cancelled"))
        for membership in db.scalars(stmt).all():
            grouped[membership.member_id].append(membership)
    return grouped


def decide_access(db: Session, member: Member, today: date) -> AccessDecision:
    grace, allow_unpaid = _access_settings(db)
    memberships = _memberships_by_member(db, [member.id])[member.id]
    return evaluate_access(member.status, memberships, today, grace, allow_unpaid)


def _access_out(decision: AccessDecision) -> AccessOut:
    return AccessOut(allowed=decision.allowed, code=decision.code, message=decision.message,
                     expires_on=decision.expires_on, in_grace=decision.in_grace)


def lookup(db: Session, search: str, limit: int = 10) -> list[LookupItem]:
    """The reception desk's quick search: who is this, are they inside, may they enter?"""
    pattern = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    members = list(db.scalars(
        select(Member).where(
            Member.is_deleted.is_(False),
            or_(Member.full_name.ilike(pattern, escape="\\"), Member.phone.ilike(pattern, escape="\\"),
                Member.member_code.ilike(pattern, escape="\\")))
        .order_by(Member.full_name, Member.id).limit(limit)).all())
    ids = [m.id for m in members]
    today, tz = gym_today(), gym_tz()
    grace, allow_unpaid = _access_settings(db)
    memberships = _memberships_by_member(db, ids)
    open_visits = {v.member_id: v for v in db.scalars(
        select(Attendance).where(Attendance.member_id.in_(ids), Attendance.check_out_at.is_(None))).all()} if ids else {}

    items = []
    for m in members:
        visit = open_visits.get(m.id)
        items.append(LookupItem(
            member=MemberRef(id=m.id, member_code=m.member_code, full_name=m.full_name),
            phone=m.phone, status=m.status, inside=visit is not None,
            inside_since_local=format_local(visit.check_in_at, tz) if visit else None,
            access=_access_out(evaluate_access(m.status, memberships[m.id], today, grace, allow_unpaid))))
    return items


# ------------------------------------------------------------------ check-in / check-out
def _auto_close(db: Session, visit: Attendance, hours: int, actor: Optional[User], ip: Optional[str]) -> None:
    """Closes a forgotten visit. The real exit time is unknown, so the stay is capped at `hours`."""
    visit.check_out_at = visit.check_in_at + timedelta(hours=hours)
    visit.duration_minutes = hours * 60
    visit.status = "auto_closed"
    visit.checked_out_by = None
    note = "Auto-closed: no check-out was recorded"
    visit.notes = f"{visit.notes} | {note}"[:255] if visit.notes else note
    log_action(db, user_id=actor.id if actor else None, action="attendance.auto_close",
               entity_type="attendance", entity_id=visit.id,
               old={"status": "inside"}, new={"status": "auto_closed", "check_out_at": visit.check_out_at}, ip=ip)


def check_in(db: Session, member_id: int, override_reason: Optional[str], actor: User,
             ip: Optional[str]) -> Attendance:
    member = _lock_member(db, member_id)
    now, tz, today, hours = utcnow(), gym_tz(), gym_today(), _stale_hours(db)

    open_visit = _open_visit(db, member.id)
    if open_visit is not None:
        if not is_stale(open_visit.check_in_at, now, hours):
            since = format_local(open_visit.check_in_at, tz, "%I:%M %p")
            raise ConflictError(f"{member.full_name} is already checked in (since {since})")
        # A forgotten check-out from an earlier visit: close it safely, keep that cleanup even
        # if this check-in is refused below, then continue.
        _auto_close(db, open_visit, hours, actor, ip)
        db.commit()
        member = _lock_member(db, member_id)

    decision = decide_access(db, member, today)
    note = None
    if not decision.allowed:
        if not override_reason:
            raise ForbiddenError(decision.message)
        if actor.role.name != ROLE_ADMIN:
            raise ForbiddenError(f"{decision.message}. Only an Admin can override this")
        note = f"Override by {actor.full_name}: {override_reason}"[:255]

    visit = Attendance(member_id=member.id, check_in_at=now, status="inside",
                       checked_in_by=actor.id, notes=note)
    db.add(visit)
    try:
        db.flush()
    except IntegrityError:
        # The database's own one-open-visit-per-member rule caught a simultaneous check-in.
        db.rollback()
        raise ConflictError("This member is already checked in")
    log_action(db, user_id=actor.id,
               action="attendance.check_in_override" if note else "attendance.check_in",
               entity_type="attendance", entity_id=visit.id,
               new={"member_id": member.id, "access": decision.code, "override_reason": override_reason}, ip=ip)
    db.commit()
    return get_visit(db, visit.id)


def check_out(db: Session, member_id: int, actor: User, ip: Optional[str]) -> Attendance:
    member = _lock_member(db, member_id, allow_deleted=True)   # always let someone leave
    visit = _open_visit(db, member.id)
    if visit is None:
        raise BadRequestError(f"{member.full_name} is not checked in")
    out_time = max(utcnow(), visit.check_in_at)
    visit.check_out_at = out_time
    visit.duration_minutes = visit_minutes(visit.check_in_at, out_time)
    visit.status = "completed"
    visit.checked_out_by = actor.id
    log_action(db, user_id=actor.id, action="attendance.check_out", entity_type="attendance",
               entity_id=visit.id, new={"member_id": member.id, "duration_minutes": visit.duration_minutes}, ip=ip)
    db.commit()
    return get_visit(db, visit.id)


def close_stale(db: Session, actor: User, ip: Optional[str]) -> int:
    hours = _stale_hours(db)
    cutoff = utcnow() - timedelta(hours=hours)
    stale = db.scalars(select(Attendance).where(
        Attendance.check_out_at.is_(None), Attendance.check_in_at <= cutoff)).all()
    for visit in stale:
        _auto_close(db, visit, hours, actor, ip)
    db.commit()
    return len(stale)


# ------------------------------------------------------------------ lists
def _scope(user: User, conditions: list) -> bool:
    """Trainers only see their own members. Returns False when a trainer has no profile (sees nothing)."""
    if user.role.name == ROLE_TRAINER:
        profile_id = _profile_id(user)
        if profile_id is None:
            return False
        conditions.append(Member.assigned_trainer_id == profile_id)
    return True


def list_inside(db: Session, user: User) -> tuple[list[AttendanceOut], int]:
    conditions = [Attendance.check_out_at.is_(None)]
    if not _scope(user, conditions):
        return [], 0
    visits = db.scalars(
        select(Attendance).join(Member, Member.id == Attendance.member_id).where(*conditions)
        .options(*_loaders()).order_by(Attendance.check_in_at, Attendance.id)).all()
    outs = _outs(db, visits)
    return outs, sum(1 for o in outs if o.is_stale)


def _resolve_range(period: Optional[str], on_date: Optional[date], date_from: Optional[date],
                   date_to: Optional[date]) -> Optional[tuple[date, date]]:
    if period and (date_from or date_to):
        raise BadRequestError("Use either 'period' or 'date_from'/'date_to', not both")
    if period:
        return period_range(period, on_date or gym_today())
    if date_from or date_to:
        start, end = date_from or date(2000, 1, 1), date_to or gym_today()
        if end < start:
            raise BadRequestError("'date_to' must not be before 'date_from'")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise BadRequestError(f"Choose a range of at most {MAX_RANGE_DAYS} days")
        return start, end
    return None


def list_attendance(db: Session, user: User, *, member_id: Optional[int], status: Optional[str],
                    search: Optional[str], period: Optional[str], on_date: Optional[date],
                    date_from: Optional[date], date_to: Optional[date], page: int, page_size: int):
    day_range = _resolve_range(period, on_date, date_from, date_to)
    conditions: list = []
    if not _scope(user, conditions):
        return [], 0
    if member_id is not None:
        conditions.append(Attendance.member_id == member_id)
    if status:
        conditions.append(Attendance.status == status)
    if search and search.strip():
        pattern = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(or_(Member.full_name.ilike(pattern, escape="\\"),
                              Member.phone.ilike(pattern, escape="\\"),
                              Member.member_code.ilike(pattern, escape="\\")))
    if day_range:
        start_utc, end_utc = local_range_to_utc(day_range[0], day_range[1], gym_tz())
        conditions += [Attendance.check_in_at >= start_utc, Attendance.check_in_at < end_utc]

    def joined(stmt):
        stmt = stmt.join(Member, Member.id == Attendance.member_id)
        return stmt.where(*conditions) if conditions else stmt

    total = db.scalar(joined(select(func.count(Attendance.id)))) or 0
    stmt = (joined(select(Attendance)).options(*_loaders())
            .order_by(Attendance.check_in_at.desc(), Attendance.id.desc())
            .offset((page - 1) * page_size).limit(page_size))
    return _outs(db, db.scalars(stmt).all()), total


# ------------------------------------------------------------------ corrections (Admin)
def _snapshot(visit: Attendance) -> dict:
    return {"member_id": visit.member_id, "check_in_at": visit.check_in_at,
            "check_out_at": visit.check_out_at, "duration_minutes": visit.duration_minutes,
            "status": visit.status, "notes": visit.notes}


def correct(db: Session, attendance_id: int, data: AttendanceCorrection, actor: User,
            ip: Optional[str]) -> Attendance:
    visit = get_visit(db, attendance_id)
    _lock_member(db, visit.member_id, allow_deleted=True)
    tz, now = gym_tz(), utcnow()

    new_in = to_utc_naive(data.check_in_at, tz) if data.check_in_at else visit.check_in_at
    new_out = to_utc_naive(data.check_out_at, tz) if data.check_out_at else visit.check_out_at

    if new_in > now + FUTURE_SKEW or (new_out is not None and new_out > now + FUTURE_SKEW):
        raise BadRequestError("Times cannot be in the future")
    if new_out is not None and new_out < new_in:
        raise BadRequestError("Check-out cannot be before check-in")
    if new_out is not None and new_out - new_in > MAX_VISIT:
        raise BadRequestError("A visit cannot be longer than 24 hours")

    overlapping = db.scalar(select(func.count(Attendance.id)).where(
        Attendance.member_id == visit.member_id, Attendance.id != visit.id,
        Attendance.check_in_at < (new_out or FAR_FUTURE),
        or_(Attendance.check_out_at.is_(None), Attendance.check_out_at > new_in)))
    if overlapping:
        raise ConflictError("These times overlap another visit of the same member")

    old = _snapshot(visit)
    closing_now = data.check_out_at is not None
    visit.check_in_at, visit.check_out_at = new_in, new_out
    if new_out is not None:
        visit.duration_minutes = visit_minutes(new_in, new_out)
        visit.status = "corrected"
        if closing_now:
            visit.checked_out_by = actor.id
    visit.notes = f"Corrected by {actor.full_name}: {data.reason}"[:255]
    db.flush()
    log_action(db, user_id=actor.id, action="attendance.correct", entity_type="attendance",
               entity_id=visit.id, old=old, new={**_snapshot(visit), "reason": data.reason}, ip=ip)
    db.commit()
    return get_visit(db, visit.id)


def remove(db: Session, attendance_id: int, reason: str, actor: User, ip: Optional[str]) -> None:
    """For a check-in made by mistake (wrong member). The full record is kept in the audit log."""
    visit = get_visit(db, attendance_id)
    _lock_member(db, visit.member_id, allow_deleted=True)
    log_action(db, user_id=actor.id, action="attendance.remove", entity_type="attendance",
               entity_id=visit.id, old=_snapshot(visit), new={"reason": reason}, ip=ip)
    db.delete(visit)
    db.commit()


# ------------------------------------------------------------------ numbers for dashboards and reports
def count_inside(db: Session) -> int:
    return db.scalar(select(func.count(Attendance.id)).where(Attendance.check_out_at.is_(None))) or 0


def visits_on(db: Session, day: date) -> int:
    start_utc, end_utc = local_range_to_utc(day, day, gym_tz())
    return db.scalar(select(func.count(Attendance.id)).where(
        Attendance.check_in_at >= start_utc, Attendance.check_in_at < end_utc)) or 0


def report(db: Session, period: str, on_date: Optional[date]) -> AttendanceReport:
    tz = gym_tz()
    start, end = period_range(period, on_date or gym_today())
    start_utc, end_utc = local_range_to_utc(start, end, tz)
    rows = db.execute(
        select(Attendance.member_id, Attendance.check_in_at, Attendance.check_out_at,
               Attendance.duration_minutes, Attendance.status)
        .where(Attendance.check_in_at >= start_utc, Attendance.check_in_at < end_utc)).all()

    series = build_series([(r.member_id, r.check_in_at) for r in rows], period, start, end, tz)
    peak_label, peak_visits = peak_of(series)
    durations = [r.duration_minutes for r in rows
                 if r.status in ("completed", "corrected") and r.duration_minutes is not None]
    return AttendanceReport(
        period=period, date_from=start, date_to=end, visits=len(rows),
        unique_members=len({r.member_id for r in rows}),
        avg_duration_minutes=average_minutes(durations),
        auto_closed_count=sum(1 for r in rows if r.status == "auto_closed"),
        corrected_count=sum(1 for r in rows if r.status == "corrected"),
        still_inside=sum(1 for r in rows if r.check_out_at is None),
        peak_label=peak_label, peak_visits=peak_visits,
        series=[SeriesPoint(**p) for p in series])


def export_csv(db: Session, date_from: date, date_to: date) -> str:
    day_range = _resolve_range(None, None, date_from, date_to)
    tz = gym_tz()
    start_utc, end_utc = local_range_to_utc(day_range[0], day_range[1], tz)
    visits = db.scalars(
        select(Attendance).where(Attendance.check_in_at >= start_utc, Attendance.check_in_at < end_utc)
        .options(*_loaders()).order_by(Attendance.check_in_at, Attendance.id)).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Member code", "Member name", "Check-in (local)", "Check-out (local)",
                     "Duration (min)", "Status", "Checked in by", "Checked out by", "Notes"])
    for v in visits:
        writer.writerow([csv_safe(x) for x in (
            v.member.member_code, v.member.full_name, format_local(v.check_in_at, tz, "%Y-%m-%d %H:%M"),
            format_local(v.check_out_at, tz, "%Y-%m-%d %H:%M") if v.check_out_at else "",
            v.duration_minutes if v.duration_minutes is not None else "", v.status,
            v.checked_in_user.full_name if v.checked_in_user else "",
            v.checked_out_user.full_name if v.checked_out_user else "", v.notes)])
    return "\ufeff" + buffer.getvalue()
