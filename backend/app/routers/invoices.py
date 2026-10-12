"""/api/invoices: bills, balances and recording payments (Admin and Receptionist)."""
import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status as http
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_admin, require_front_desk
from app.dependencies.common import get_client_ip
from app.models import User
from app.schemas.billing import (
    InvoiceCreate, InvoiceDetailOut, InvoiceListItem, InvoiceStatus, InvoiceSummary,
    PaymentCreate, PaymentOut,
)
from app.schemas.common import Page
from app.services import invoice_service, payment_service
from app.utils.dates import gym_today

router = APIRouter(prefix="/invoices", tags=["Invoices and payments"])


@router.get("", response_model=Page[InvoiceListItem])
def list_invoices(
    member_id: Optional[int] = None,
    status: Optional[InvoiceStatus] = None,
    overdue: bool = Query(False, description="Only unpaid invoices past their due date"),
    search: Optional[str] = Query(None, max_length=100, description="Invoice no, member name, code or phone"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(require_front_desk),
):
    items, total = invoice_service.list_invoices(
        db, member_id=member_id, status=status, overdue=overdue, search=search,
        date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    today = gym_today()
    return Page[InvoiceListItem](
        items=[invoice_service.list_item(i, today) for i in items],
        total=total, page=page, page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0)


# NOTE: "/summary" must be declared BEFORE "/{invoice_id}".
@router.get("/summary", response_model=InvoiceSummary)
def invoice_summary(member_id: Optional[int] = None, db: Session = Depends(get_db),
                    _user: User = Depends(require_front_desk)):
    """Money still owed (pending and part-paid invoices), for one member or for everyone."""
    return invoice_service.summary(db, member_id)


@router.post("", response_model=InvoiceDetailOut, status_code=http.HTTP_201_CREATED)
def create_invoice(payload: InvoiceCreate, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_front_desk)):
    """Personal-training or other one-off bills. Membership bills are created automatically."""
    invoice = invoice_service.create_manual(db, payload, user, get_client_ip(request))
    return invoice_service.detail(invoice_service.get_invoice(db, invoice.id))


@router.get("/{invoice_id}", response_model=InvoiceDetailOut)
def read_invoice(invoice_id: int, db: Session = Depends(get_db), _user: User = Depends(require_front_desk)):
    return invoice_service.detail(invoice_service.get_invoice(db, invoice_id))


@router.post("/{invoice_id}/cancel", response_model=InvoiceDetailOut)
def cancel_invoice(invoice_id: int, request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    """Only for one-off invoices without payments (membership bills go with the membership)."""
    invoice = invoice_service.cancel_manual_invoice(db, invoice_id, admin, get_client_ip(request))
    return invoice_service.detail(invoice)


@router.post("/{invoice_id}/payments", response_model=PaymentOut, status_code=http.HTTP_201_CREATED)
def record_payment(invoice_id: int, payload: PaymentCreate, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(require_front_desk)):
    """Record money received. The invoice only becomes 'paid' when the payments add up to the total."""
    payment = payment_service.record_payment(db, invoice_id, payload, user, get_client_ip(request))
    return payment_service.payment_out(payment)
