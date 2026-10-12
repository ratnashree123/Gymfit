"""Builds a receipt (data + printable HTML) for one payment."""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Payment
from app.schemas.billing import METHOD_LABELS, VERIFICATION_LABELS, MemberRef, ReceiptLine, ReceiptOut
from app.services import payment_service, settings_service
from app.services.receipt_html import render_receipt_html
from app.utils.dates import gym_tz
from app.utils.timezones import format_local


def build_receipt(db: Session, payment_id: int) -> ReceiptOut:
    payment = payment_service.get_payment(db, payment_id)
    invoice = payment.invoice
    member = invoice.member

    # "Paid so far" is counted up to THIS payment, so an old receipt never changes later.
    paid_so_far = Decimal(db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.invoice_id == invoice.id, Payment.id <= payment.id)) or 0)

    lines = [ReceiptLine(label="Price", amount=invoice.subtotal)]
    if invoice.discount_amount > 0:
        lines.append(ReceiptLine(label="Discount", amount=-invoice.discount_amount))
    if invoice.tax_amount > 0:
        lines.append(ReceiptLine(label="Tax", amount=invoice.tax_amount))
    lines.append(ReceiptLine(label="Invoice total", amount=invoice.total_amount))

    description = invoice.notes
    if invoice.membership is not None:
        description = invoice.membership.plan.name
    elif not description:
        description = invoice.invoice_type.replace("_", " ").title()

    return ReceiptOut(
        gym_name=settings_service.get_str(db, "gym_name", "GymFit"),
        currency=settings_service.get_str(db, "currency_symbol", "\u20b9"),
        receipt_number=payment.receipt_number, issued_at=payment.payment_date,
        issued_local=format_local(payment.payment_date, gym_tz()),
        member=MemberRef(id=member.id, member_code=member.member_code, full_name=member.full_name),
        invoice_number=invoice.invoice_number, description=description, lines=lines,
        payment_amount=payment.amount, paid_so_far=paid_so_far,
        balance_due=max(invoice.total_amount - paid_so_far, Decimal("0.00")),
        method=payment.method, method_label=METHOD_LABELS.get(payment.method, payment.method),
        reference_no=payment.reference_no,
        received_by=payment.receiver.full_name if payment.receiver else "-",
        verification_type=payment.verification_type,
        verification_label=VERIFICATION_LABELS.get(payment.verification_type, payment.verification_type),
    )


def _money(currency: str, value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{currency}{abs(value):,.2f}"


def render_html(receipt: ReceiptOut) -> str:
    c = receipt.currency
    return render_receipt_html({
        "gym_name": receipt.gym_name, "receipt_number": receipt.receipt_number,
        "issued_local": receipt.issued_local, "member_name": receipt.member.full_name,
        "member_code": receipt.member.member_code, "invoice_number": receipt.invoice_number,
        "description": receipt.description,
        "lines": [(line.label, _money(c, line.amount)) for line in receipt.lines],
        "payment_amount": _money(c, receipt.payment_amount),
        "paid_so_far": _money(c, receipt.paid_so_far), "balance_due": _money(c, receipt.balance_due),
        "method_label": receipt.method_label, "reference_no": receipt.reference_no,
        "received_by": receipt.received_by, "verification_label": receipt.verification_label,
    })
