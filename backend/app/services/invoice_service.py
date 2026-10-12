"""Invoices (bills). An invoice is created with every membership and for extras.

Rules that matter:
  * the status comes only from recorded payments (see money.invoice_status);
  * a 0.00 bill is not created at all (nothing to collect);
  * money is Decimal everywhere.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.constants import ROLE_ADMIN, ROLE_RECEPTIONIST
from app.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.models import Invoice, Member, Membership, MembershipPlan, Payment, User
from app.schemas.billing import (
    InvoiceBrief, InvoiceCreate, InvoiceDetailOut, InvoiceListItem, InvoiceSummary, MemberRef,
)
from app.services import payment_service, settings_service
from app.services.audit_service import log_action
from app.services.money import MoneyError, calculate_invoice, discount_exceeds_percent
from app.utils.dates import gym_tz, gym_today
from app.utils.timezones import local_range_to_utc

UNPAID = ("pending", "partial")


# ------------------------------------------------------------------ output
def amount_paid(invoice: Invoice) -> Decimal:
    return sum((p.amount for p in invoice.payments), Decimal("0.00"))


def is_overdue(invoice: Invoice, today: date) -> bool:
    return invoice.status in UNPAID and invoice.due_date is not None and invoice.due_date < today


def brief(invoice: Invoice, today: Optional[date] = None) -> InvoiceBrief:
    today = today or gym_today()
    paid = amount_paid(invoice)
    return InvoiceBrief(
        id=invoice.id, invoice_number=invoice.invoice_number, invoice_type=invoice.invoice_type,
        total_amount=invoice.total_amount, amount_paid=paid,
        balance=max(invoice.total_amount - paid, Decimal("0.00")) if invoice.status != "cancelled" else Decimal("0.00"),
        status=invoice.status, due_date=invoice.due_date, is_overdue=is_overdue(invoice, today),
    )


def list_item(invoice: Invoice, today: Optional[date] = None) -> InvoiceListItem:
    member = invoice.member
    return InvoiceListItem(
        **brief(invoice, today).model_dump(),
        member=MemberRef(id=member.id, member_code=member.member_code, full_name=member.full_name),
        subtotal=invoice.subtotal, discount_amount=invoice.discount_amount,
        tax_amount=invoice.tax_amount, issued_at=invoice.issued_at,
    )


def detail(invoice: Invoice) -> InvoiceDetailOut:
    payments = sorted(invoice.payments, key=lambda p: p.id)
    plan_name = invoice.membership.plan.name if invoice.membership is not None else None
    return InvoiceDetailOut(
        **list_item(invoice).model_dump(),
        membership_id=invoice.membership_id, plan_name=plan_name, notes=invoice.notes,
        payments=[payment_service.payment_out(p) for p in payments],
    )


# ------------------------------------------------------------------ creating
def _amounts_for(db: Session, subtotal: Decimal, discount_amount, discount_percent, actor: User):
    tax_percent = settings_service.get_decimal(db, "tax_percent", 0)
    try:
        amounts = calculate_invoice(subtotal, discount_amount=discount_amount,
                                    discount_percent=discount_percent, tax_percent=tax_percent)
    except MoneyError as error:
        raise BadRequestError(str(error))

    if actor.role.name == ROLE_RECEPTIONIST and amounts.discount > 0:
        cap = settings_service.get_decimal(db, "max_receptionist_discount_percent", 10)
        if discount_exceeds_percent(amounts.subtotal, amounts.discount, cap):
            raise ForbiddenError(f"Receptionists can give at most {cap.normalize():f}% discount. Ask an Admin.")
    return amounts


def _new_invoice(db: Session, *, member_id: int, membership_id: Optional[int], invoice_type: str,
                 amounts, due_date: Optional[date], notes: Optional[str], actor: User,
                 ip: Optional[str]) -> Invoice:
    invoice = Invoice(
        invoice_number=f"TMP-{uuid.uuid4().hex[:15]}",  # replaced below, once the id is known
        member_id=member_id, membership_id=membership_id, invoice_type=invoice_type,
        subtotal=amounts.subtotal, discount_amount=amounts.discount, tax_amount=amounts.tax,
        total_amount=amounts.total, status="pending", due_date=due_date, notes=notes,
        created_by=actor.id,
    )
    db.add(invoice)
    db.flush()
    invoice.invoice_number = f"INV-{invoice.id:06d}"
    log_action(db, user_id=actor.id, action="invoice.create", entity_type="invoice",
               entity_id=invoice.id,
               new={"invoice_number": invoice.invoice_number, "member_id": member_id,
                    "type": invoice_type, "subtotal": amounts.subtotal, "discount": amounts.discount,
                    "tax": amounts.tax, "total": amounts.total}, ip=ip)
    return invoice


def _default_due_date(db: Session) -> date:
    return gym_today() + timedelta(days=settings_service.get_int(db, "invoice_due_days", 7))


def create_for_membership(db: Session, member: Member, membership: Membership, plan: MembershipPlan,
                          discount_amount, discount_percent, actor: User, ip: Optional[str]) -> Optional[Invoice]:
    """Called inside the membership transaction. Returns None for a free (0.00) membership."""
    amounts = _amounts_for(db, plan.price, discount_amount, discount_percent, actor)
    if amounts.total <= 0:
        return None
    return _new_invoice(
        db, member_id=member.id, membership_id=membership.id,
        invoice_type="renewal" if membership.is_renewal else "membership",
        amounts=amounts, due_date=_default_due_date(db), notes=None, actor=actor, ip=ip,
    )


def create_manual(db: Session, data: InvoiceCreate, actor: User, ip: Optional[str]) -> Invoice:
    member = db.get(Member, data.member_id)
    if member is None or member.is_deleted:
        raise NotFoundError("Member not found")

    if data.plan_id is not None:
        plan = db.get(MembershipPlan, data.plan_id)
        if plan is None:
            raise NotFoundError("Plan not found")
        if plan.plan_type != "addon" or not plan.is_active:
            raise BadRequestError("Choose an active add-on plan (membership plans are assigned to the member instead)")
        subtotal, notes = plan.price, data.notes or plan.name
    else:
        subtotal, notes = data.amount, data.notes

    amounts = _amounts_for(db, subtotal, data.discount_amount, data.discount_percent, actor)
    if amounts.total <= 0:
        raise BadRequestError("The invoice total must be greater than zero")

    invoice = _new_invoice(
        db, member_id=member.id, membership_id=None, invoice_type=data.invoice_type,
        amounts=amounts, due_date=data.due_date or _default_due_date(db), notes=notes,
        actor=actor, ip=ip,
    )
    db.commit()
    db.refresh(invoice)
    return invoice


# ------------------------------------------------------------------ reading
def get_invoice(db: Session, invoice_id: int) -> Invoice:
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == invoice_id)
        .options(selectinload(Invoice.payments).selectinload(Payment.receiver),
                 selectinload(Invoice.member), selectinload(Invoice.membership))
    )
    if invoice is None:
        raise NotFoundError("Invoice not found")
    return invoice


def _paid_expr():
    return (select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.invoice_id == Invoice.id).scalar_subquery())


def list_invoices(db: Session, *, member_id: Optional[int], status: Optional[str], overdue: bool,
                  search: Optional[str], date_from: Optional[date], date_to: Optional[date],
                  page: int, page_size: int) -> tuple[list[Invoice], int]:
    today = gym_today()
    conditions = []
    if member_id is not None:
        conditions.append(Invoice.member_id == member_id)
    if status:
        conditions.append(Invoice.status == status)
    if overdue:
        conditions += [Invoice.status.in_(UNPAID), Invoice.due_date.is_not(None), Invoice.due_date < today]
    if search and search.strip():
        pattern = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(
            Invoice.invoice_number.ilike(pattern, escape="\\")
            | Invoice.member_id.in_(
                select(Member.id).where(
                    Member.full_name.ilike(pattern, escape="\\")
                    | Member.member_code.ilike(pattern, escape="\\")
                    | Member.phone.ilike(pattern, escape="\\"))))
    if date_from or date_to:
        start, end = local_range_to_utc(date_from or date(2000, 1, 1), date_to or date(2100, 1, 1), gym_tz())
        conditions += [Invoice.issued_at >= start, Invoice.issued_at < end]

    count_stmt = select(func.count(Invoice.id))
    stmt = select(Invoice).options(selectinload(Invoice.member), selectinload(Invoice.payments))
    if conditions:
        count_stmt = count_stmt.where(*conditions)
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(Invoice.id.desc()).offset((page - 1) * page_size).limit(page_size)
    return list(db.scalars(stmt).all()), db.scalar(count_stmt) or 0


def summary(db: Session, member_id: Optional[int]) -> InvoiceSummary:
    """How much money is still owed (pending + partial invoices, minus what was paid on them)."""
    today = gym_today()

    def totals(extra_conditions):
        base = [Invoice.status.in_(UNPAID), *extra_conditions]
        if member_id is not None:
            base.append(Invoice.member_id == member_id)
        count, billed = db.execute(
            select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total_amount), 0)).where(*base)
        ).one()
        paid = db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.invoice_id.in_(select(Invoice.id).where(*base)))
        ) or 0
        return int(count), Decimal(billed) - Decimal(paid)

    pending_count, outstanding = totals([])
    overdue_count, overdue_total = totals([Invoice.due_date.is_not(None), Invoice.due_date < today])
    return InvoiceSummary(
        pending_count=pending_count, overdue_count=overdue_count,
        outstanding_total=outstanding.quantize(Decimal("0.01")),
        overdue_total=overdue_total.quantize(Decimal("0.01")),
    )


# ------------------------------------------------------------------ cancelling
def cancel_manual_invoice(db: Session, invoice_id: int, actor: User, ip: Optional[str]) -> Invoice:
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if invoice is None:
        raise NotFoundError("Invoice not found")
    if invoice.membership_id is not None:
        raise BadRequestError("This invoice belongs to a membership. Cancel the membership instead")
    if invoice.status == "cancelled":
        raise BadRequestError("This invoice is already cancelled")
    if db.scalar(select(func.count(Payment.id)).where(Payment.invoice_id == invoice.id)):
        raise BadRequestError("Payments exist for this invoice. Refunds are not supported yet, so it cannot be cancelled")
    old = invoice.status
    invoice.status = "cancelled"
    log_action(db, user_id=actor.id, action="invoice.cancel", entity_type="invoice",
               entity_id=invoice.id, old={"status": old}, new={"status": "cancelled"}, ip=ip)
    db.commit()
    return get_invoice(db, invoice.id)


def cancel_for_membership(db: Session, membership: Membership, actor: User, ip: Optional[str]) -> None:
    """Used when a membership is cancelled. Blocks if money was already taken."""
    for invoice in db.scalars(select(Invoice).where(
            Invoice.membership_id == membership.id, Invoice.status != "cancelled")).all():
        if db.scalar(select(func.count(Payment.id)).where(Payment.invoice_id == invoice.id)):
            raise BadRequestError(
                "Payments were recorded for this membership. Refunds are not supported yet, "
                "so it cannot be cancelled")
        invoice.status = "cancelled"
        log_action(db, user_id=actor.id, action="invoice.cancel", entity_type="invoice",
                   entity_id=invoice.id, old={"status": "pending"}, new={"status": "cancelled"}, ip=ip)

