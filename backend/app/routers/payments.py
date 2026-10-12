"""/api/payments: payment history, receipts, CSV export."""
import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_admin, require_front_desk
from app.models import User
from app.schemas.billing import PaymentMethod, PaymentOut, PaymentPage, ReceiptOut
from app.services import payment_service, receipt_service, report_service

router = APIRouter(prefix="/payments", tags=["Invoices and payments"])


@router.get("", response_model=PaymentPage)
def list_payments(
    member_id: Optional[int] = None,
    search: Optional[str] = Query(None, max_length=100,
                                  description="Receipt no, reference / transaction id, invoice no, member name, code or phone"),
    method: Optional[PaymentMethod] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(require_front_desk),
):
    items, total, total_amount = payment_service.list_payments(
        db, member_id=member_id, search=search, method=method, date_from=date_from,
        date_to=date_to, page=page, page_size=page_size)
    return PaymentPage(
        items=[payment_service.payment_out(p) for p in items], total=total, page=page,
        page_size=page_size, pages=math.ceil(total / page_size) if total else 0,
        total_amount=total_amount)


# NOTE: "/export.csv" must be declared BEFORE "/{payment_id}".
@router.get("/export.csv")
def export_payments_csv(date_from: date, date_to: date, db: Session = Depends(get_db),
                        _admin: User = Depends(require_admin)):
    """Download payments between two dates (Admin only)."""
    content = report_service.export_csv(db, date_from, date_to)
    filename = f"payments_{date_from.isoformat()}_{date_to.isoformat()}.csv"
    return Response(content=content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"',
                             "Cache-Control": "no-store"})


@router.get("/{payment_id}", response_model=PaymentOut)
def read_payment(payment_id: int, db: Session = Depends(get_db), _user: User = Depends(require_front_desk)):
    return payment_service.payment_out(payment_service.get_payment(db, payment_id))


@router.get("/{payment_id}/receipt", response_model=ReceiptOut)
def receipt_data(payment_id: int, db: Session = Depends(get_db), _user: User = Depends(require_front_desk)):
    return receipt_service.build_receipt(db, payment_id)


@router.get("/{payment_id}/receipt.html", response_class=HTMLResponse)
def receipt_page(payment_id: int, db: Session = Depends(get_db), _user: User = Depends(require_front_desk)):
    """A printable receipt page. Open it from the app (it needs your login token)."""
    html = receipt_service.render_html(receipt_service.build_receipt(db, payment_id))
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
