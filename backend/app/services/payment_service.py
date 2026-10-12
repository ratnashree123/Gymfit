"""Recording payments (manual entries by staff) and searching them.

Payments are never edited or deleted: they are financial records.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models import Invoice, Member, Payment, User
from app.models._common import utcnow
from app.schemas.billing import METHOD_LABELS, VERIFICATION_LABELS, MemberRef, PaymentCreate, PaymentOut
from app.services import settings_service
from app.services.audit_service import log_action
from app.services.money import invoice_status
from app.utils.dates import gym_tz
from app.utils.timezones import local_range_to_utc

DUPLICATE_WINDOW_SECONDS = 10


def payment_out(payment: Payment) -> PaymentOut:
    invoice = payment.invoice
    member = invoice.member
    return PaymentOut(
        id=payment.id, receipt_number=payment.receipt_number, invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        member=MemberRef(id=member.id, member_code=member.member_code, full_name=member.full_name),
        amount=payment.amount, method=payment.method,
        verification_type=payment.verification_type,
        verification_label=VERIFICATION_LABELS.get(payment.verification_type, payment.verification_type),
        reference_no=payment.reference_no, payment_date=payment.payment_date,
        received_by_name=payment.receiver.full_name if payment.receiver else None,
        notes=payment.notes,
    )


def _paid_total(db: Session, invoice_id: int) -> Decimal:
    return Decimal(db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.invoice_id == invoice_id)) or 0)


def record_payment(db: Session, invoice_id: int, data: PaymentCreate, actor: User,
                   ip: Optional[str]) -> Payment:
    # Lock the invoice row (SELECT ... FOR UPDATE). Two staff paying the same invoice at the
    # same moment are handled one after the other, so the balance check below is always true.
    invoice = db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    if invoice is None:
        raise NotFoundError("Invoice not found")
    if invoice.status == "cancelled":
        raise BadRequestError("This invoice is cancelled")
    if invoice.status == "paid":
        raise BadRequestError("This invoice is already fully paid")

    paid_before = _paid_total(db, invoice.id)
    balance = invoice.total_amount - paid_before
    if data.amount > balance:
        raise BadRequestError(f"The amount is more than the balance due ({balance})")
    if data.amount < balance and not settings_service.get_bool(db, "allow_partial_payments", True):
        raise BadRequestError(f"Partial payments are turned off. The full balance of {balance} must be paid")

    if data.reference_no:
        reused = db.scalar(select(Payment.id).where(
            Payment.method == data.method,
            func.lower(Payment.reference_no) == data.reference_no.lower()))
        if reused is not None:
            raise ConflictError("This reference number was already recorded for another payment")

    just_now = db.scalar(select(func.count(Payment.id)).where(
        Payment.invoice_id == invoice.id, Payment.amount == data.amount, Payment.method == data.method,
        Payment.created_at >= utcnow() - timedelta(seconds=DUPLICATE_WINDOW_SECONDS)))
    if just_now:
        raise ConflictError("An identical payment was recorded a moment ago. "
                            "If this is really a second payment, wait a few seconds and try again")

    payment = Payment(
        receipt_number=f"TMP-{uuid.uuid4().hex[:15]}",  # replaced below, once the id is known
        invoice_id=invoice.id, member_id=invoice.member_id, amount=data.amount, method=data.method,
        verification_type="manual",  # always: there is no payment gateway in this project
        reference_no=data.reference_no, payment_date=utcnow(), received_by=actor.id, notes=data.notes,
    )
    # One transaction: the payment, the new invoice status and the audit row are saved together.
    db.add(payment)
    db.flush()
    payment.receipt_number = f"RCP-{payment.id:06d}"
    old_status = invoice.status
    invoice.status = invoice_status(invoice.total_amount, paid_before + data.amount)
    log_action(db, user_id=actor.id, action="payment.record", entity_type="payment",
               entity_id=payment.id,
               old={"invoice_status": old_status},
               new={"receipt_number": payment.receipt_number, "invoice": invoice.invoice_number,
                    "amount": data.amount, "method": data.method, "reference_no": data.reference_no,
                    "invoice_status": invoice.status}, ip=ip)
    db.commit()
    return get_payment(db, payment.id)


def _loaders():
    return (selectinload(Payment.invoice).selectinload(Invoice.member),
            selectinload(Payment.invoice).selectinload(Invoice.membership),
            selectinload(Payment.receiver))


def get_payment(db: Session, payment_id: int) -> Payment:
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).options(*_loaders()))
    if payment is None:
        raise NotFoundError("Payment not found")
    return payment


def _filters(*, member_id, search, method, date_from, date_to) -> list:
    conditions = []
    if member_id is not None:
        conditions.append(Payment.member_id == member_id)
    if method:
        conditions.append(Payment.method == method)
    if search and search.strip():
        pattern = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(
            Payment.receipt_number.ilike(pattern, escape="\\")
            | Payment.reference_no.ilike(pattern, escape="\\")
            | Invoice.invoice_number.ilike(pattern, escape="\\")
            | Member.full_name.ilike(pattern, escape="\\")
            | Member.member_code.ilike(pattern, escape="\\")
            | Member.phone.ilike(pattern, escape="\\"))
    if date_from or date_to:
        start, end = local_range_to_utc(date_from or date(2000, 1, 1), date_to or date(2100, 1, 1), gym_tz())
        conditions += [Payment.payment_date >= start, Payment.payment_date < end]
    return conditions


def list_payments(db: Session, *, member_id: Optional[int], search: Optional[str], method: Optional[str],
                  date_from: Optional[date], date_to: Optional[date], page: int, page_size: int):
    conditions = _filters(member_id=member_id, search=search, method=method,
                          date_from=date_from, date_to=date_to)

    def joined(stmt):
        stmt = stmt.join(Invoice, Invoice.id == Payment.invoice_id).join(Member, Member.id == Payment.member_id)
        return stmt.where(*conditions) if conditions else stmt

    total = db.scalar(joined(select(func.count(Payment.id)))) or 0
    total_amount = Decimal(db.scalar(joined(select(func.coalesce(func.sum(Payment.amount), 0)))) or 0)
    stmt = (joined(select(Payment)).options(*_loaders())
            .order_by(Payment.payment_date.desc(), Payment.id.desc())
            .offset((page - 1) * page_size).limit(page_size))
    return list(db.scalars(stmt).all()), total, total_amount.quantize(Decimal("0.01"))
