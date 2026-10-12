"""Invoices, payments, receipts and reports."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.common import OptText255, Page, UTCDateTime, blank_to_none

Amount = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
DiscountPercent = Optional[Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]]
DiscountAmount = Optional[Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]]
Reference = Annotated[
    Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]],
    BeforeValidator(blank_to_none),
]
PaymentMethod = Literal["cash", "upi", "card", "bank_transfer"]
InvoiceStatus = Literal["pending", "partial", "paid", "cancelled"]

METHOD_LABELS = {"cash": "Cash", "upi": "UPI", "card": "Card", "bank_transfer": "Bank transfer"}
VERIFICATION_LABELS = {
    "manual": "Manually recorded by staff (not verified online)",
    "verified_online": "Verified online transaction",
}


class DiscountFields(BaseModel):
    """Optional discount: a percent OR a fixed amount, never both."""

    discount_percent: DiscountPercent = None
    discount_amount: DiscountAmount = None

    @model_validator(mode="after")
    def only_one_discount(self):
        if self.discount_percent is not None and self.discount_amount is not None:
            raise ValueError("Use either discount_percent or discount_amount, not both")
        return self


class MemberRef(BaseModel):
    id: int
    member_code: str
    full_name: str


class InvoiceBrief(BaseModel):
    id: int
    invoice_number: str
    invoice_type: str
    total_amount: Decimal
    amount_paid: Decimal
    balance: Decimal
    status: str
    due_date: Optional[date] = None
    is_overdue: bool = False


class InvoiceListItem(InvoiceBrief):
    member: MemberRef
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    issued_at: UTCDateTime


class PaymentOut(BaseModel):
    id: int
    receipt_number: str
    invoice_id: int
    invoice_number: str
    member: MemberRef
    amount: Decimal
    method: str
    verification_type: str
    verification_label: str
    reference_no: Optional[str] = None
    payment_date: UTCDateTime
    received_by_name: Optional[str] = None
    notes: Optional[str] = None


class InvoiceDetailOut(InvoiceListItem):
    membership_id: Optional[int] = None
    plan_name: Optional[str] = None
    notes: Optional[str] = None
    payments: list[PaymentOut]


class PaymentCreate(BaseModel):
    # extra="forbid": a client cannot claim a payment is 'verified_online'.
    model_config = ConfigDict(extra="forbid")

    amount: Amount
    method: PaymentMethod
    reference_no: Reference = None
    notes: OptText255 = None

    @model_validator(mode="after")
    def reference_needed_for_non_cash(self):
        if self.method != "cash" and not self.reference_no:
            raise ValueError("A reference number is required for UPI, card and bank transfer payments")
        return self


class InvoiceCreate(DiscountFields):
    """Bills that are not a membership period: personal training, merchandise, fines..."""

    model_config = ConfigDict(extra="forbid")

    member_id: int
    invoice_type: Literal["personal_training", "other"]
    plan_id: Optional[int] = None   # an add-on plan: its price is used
    amount: Optional[Amount] = None  # or type the price yourself
    notes: OptText255 = None
    due_date: Optional[date] = None

    @model_validator(mode="after")
    def price_source(self):
        if self.plan_id is not None and self.amount is not None:
            raise ValueError("Send either plan_id or amount, not both")
        if self.plan_id is None and self.amount is None:
            raise ValueError("Send plan_id (an add-on plan) or amount")
        return self


class InvoiceSummary(BaseModel):
    pending_count: int
    overdue_count: int
    outstanding_total: Decimal
    overdue_total: Decimal


class PaymentPage(Page[PaymentOut]):
    total_amount: Decimal  # sum of ALL payments matching the filters, not just this page


class RevenuePoint(BaseModel):
    label: str
    amount: Decimal
    count: int


class RevenueReport(BaseModel):
    period: str
    date_from: date
    date_to: date
    total: Decimal
    payment_count: int
    by_method: dict[str, Decimal]
    series: list[RevenuePoint]


class ReceiptLine(BaseModel):
    label: str
    amount: Decimal


class ReceiptOut(BaseModel):
    gym_name: str
    currency: str
    receipt_number: str
    issued_at: UTCDateTime
    issued_local: str
    member: MemberRef
    invoice_number: str
    description: Optional[str] = None
    lines: list[ReceiptLine]
    payment_amount: Decimal
    paid_so_far: Decimal
    balance_due: Decimal
    method: str
    method_label: str
    reference_no: Optional[str] = None
    received_by: str
    verification_type: str
    verification_label: str
