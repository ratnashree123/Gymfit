"""membership_plans, memberships, invoices, payments"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._common import utcnow


class MembershipPlan(Base):
    __tablename__ = "membership_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    plan_type: Mapped[str] = mapped_column(
        Enum("membership", "addon", name="plan_type", native_enum=False, length=20),
        default="membership",
    )
    duration_days: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    description: Mapped[Optional[str]] = mapped_column(String(255))
    benefits: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="plan")


class Membership(Base):
    """One period of membership for one member (history + renewals)."""

    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("membership_plans.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    price_at_purchase: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    is_renewal: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        Enum("active", "expired", "cancelled", name="membership_status", native_enum=False, length=20),
        default="active",
    )
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    member: Mapped["Member"] = relationship(back_populates="memberships")
    plan: Mapped["MembershipPlan"] = relationship(back_populates="memberships")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="membership")


class Invoice(Base):
    """A bill. Its paid amount is SUM(payments.amount); status is kept for fast filtering."""

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(30), unique=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    membership_id: Mapped[Optional[int]] = mapped_column(ForeignKey("memberships.id"))
    invoice_type: Mapped[str] = mapped_column(
        Enum("membership", "renewal", "personal_training", "other",
             name="invoice_type", native_enum=False, length=30)
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(
        Enum("pending", "partial", "paid", "cancelled",
             name="invoice_status", native_enum=False, length=20),
        default="pending",
    )
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[Optional[str]] = mapped_column(String(255))

    member: Mapped["Member"] = relationship(back_populates="invoices")
    membership: Mapped[Optional["Membership"]] = relationship(back_populates="invoices")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")


class Payment(Base):
    """Money received against an invoice (manually recorded, no gateway)."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_number: Mapped[str] = mapped_column(String(30), unique=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    method: Mapped[str] = mapped_column(
        Enum("cash", "upi", "card", "bank_transfer", name="payment_method", native_enum=False, length=20)
    )
    verification_type: Mapped[str] = mapped_column(
        Enum("manual", "verified_online", name="verification_type", native_enum=False, length=20),
        default="manual",
    )
    reference_no: Mapped[Optional[str]] = mapped_column(String(100))
    payment_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    received_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    invoice: Mapped["Invoice"] = relationship(back_populates="payments")
    receiver: Mapped[Optional["User"]] = relationship(foreign_keys="Payment.received_by")
