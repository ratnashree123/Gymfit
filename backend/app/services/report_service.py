"""Revenue report and CSV export. All dates are the gym's LOCAL dates."""
import csv
import io
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.exceptions import BadRequestError
from app.models import Invoice, Payment
from app.schemas.billing import METHOD_LABELS, RevenuePoint, RevenueReport
from app.services.revenue_rules import build_series, csv_safe, default_range, validate_range
from app.utils.dates import gym_today, gym_tz
from app.utils.timezones import format_local, local_range_to_utc, utc_to_local_date

MAX_EXPORT_DAYS = 3660


def _resolve_range(period: str, date_from: Optional[date], date_to: Optional[date]) -> tuple[date, date]:
    default_from, default_to = default_range(period, gym_today())
    start, end = date_from or default_from, date_to or default_to
    try:
        validate_range(period, start, end)
    except ValueError as error:
        raise BadRequestError(str(error))
    return start, end


def revenue(db: Session, period: str, date_from: Optional[date], date_to: Optional[date]) -> RevenueReport:
    start, end = _resolve_range(period, date_from, date_to)
    tz = gym_tz()
    start_utc, end_utc = local_range_to_utc(start, end, tz)
    rows = db.execute(
        select(Payment.payment_date, Payment.amount, Payment.method)
        .where(Payment.payment_date >= start_utc, Payment.payment_date < end_utc)
    ).all()

    by_method = {method: Decimal("0.00") for method in METHOD_LABELS}
    total = Decimal("0.00")
    dated = []
    for paid_at, amount, method in rows:
        amount = Decimal(amount)
        total += amount
        by_method[method] = by_method.get(method, Decimal("0.00")) + amount
        dated.append((utc_to_local_date(paid_at, tz), amount))

    series = [RevenuePoint(**point) for point in build_series(dated, period, start, end)]
    return RevenueReport(period=period, date_from=start, date_to=end, total=total,
                         payment_count=len(rows), by_method=by_method, series=series)


def export_csv(db: Session, date_from: date, date_to: date) -> str:
    if date_to < date_from:
        raise BadRequestError("'date_to' must not be before 'date_from'")
    if (date_to - date_from).days > MAX_EXPORT_DAYS:
        raise BadRequestError("Choose a range of at most 10 years")
    tz = gym_tz()
    start_utc, end_utc = local_range_to_utc(date_from, date_to, tz)
    payments = db.scalars(
        select(Payment).where(Payment.payment_date >= start_utc, Payment.payment_date < end_utc)
        .options(selectinload(Payment.invoice).selectinload(Invoice.member), selectinload(Payment.receiver))
        .order_by(Payment.payment_date, Payment.id)
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Receipt no", "Date (local)", "Member code", "Member name", "Invoice no",
                     "Amount", "Method", "Recording", "Reference", "Received by"])
    for p in payments:
        member = p.invoice.member
        writer.writerow([csv_safe(v) for v in (
            p.receipt_number, format_local(p.payment_date, tz, "%Y-%m-%d %H:%M"),
            member.member_code, member.full_name, p.invoice.invoice_number, p.amount,
            METHOD_LABELS.get(p.method, p.method),
            "manual" if p.verification_type == "manual" else "verified online",
            p.reference_no, p.receiver.full_name if p.receiver else "")])
    return "\ufeff" + buffer.getvalue()  # BOM so Excel reads non-English names correctly


# ================================================================== membership report
MAX_REPORT_ROWS = 20000


def _check_ranges(expires_from, expires_to, joined_from, joined_to) -> None:
    if expires_from and expires_to and expires_to < expires_from:
        raise BadRequestError("'expires_to' must not be before 'expires_from'")
    if joined_from and joined_to and joined_to < joined_from:
        raise BadRequestError("'joined_to' must not be before 'joined_from'")


def membership_report(db: Session, user, *, status, plan_id, expires_from, expires_to, joined_from,
                      joined_to, search, sort_by, order, page, page_size):
    from app.models import Member
    from app.services import member_filters, member_service, settings_service

    _check_ranges(expires_from, expires_to, joined_from, joined_to)
    items, total = member_service.list_members(
        db, user, search=search, status=status, expiring_soon=False, trainer_id=None, deleted=False,
        sort_by=sort_by, order=order, page=page, page_size=page_size, plan_id=plan_id,
        expires_from=expires_from, expires_to=expires_to, joined_from=joined_from, joined_to=joined_to)
    counts = member_filters.status_counts(
        db, gym_today(), settings_service.get_int(db, "expiry_alert_days", 7), [Member.is_deleted.is_(False)])
    return items, total, counts


def export_memberships_csv(db: Session, user, **filters) -> str:
    from app.services import member_service

    _check_ranges(filters["expires_from"], filters["expires_to"], filters["joined_from"], filters["joined_to"])
    members, page = [], 1
    while True:
        batch, total = member_service.list_members(db, user, expiring_soon=False, trainer_id=None, deleted=False,
                                                   page=page, page_size=500, **filters)
        if total > MAX_REPORT_ROWS:
            raise BadRequestError(f"More than {MAX_REPORT_ROWS} rows. Narrow the filters")
        members += batch
        if len(members) >= total or not batch:
            break
        page += 1

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Member code", "Name", "Phone", "Email", "Registered", "Member status", "Membership status",
                     "Plan", "Expires on", "Days left", "Trainer"])
    for m in members:
        writer.writerow([csv_safe(v) for v in (
            m.member_code, m.full_name, m.phone, m.email, m.registration_date, m.status, m.membership_status,
            m.plan_name, m.expires_on, m.days_left if m.days_left is not None else "",
            m.assigned_trainer.full_name if m.assigned_trainer else "")])
    return "\ufeff" + buffer.getvalue()
