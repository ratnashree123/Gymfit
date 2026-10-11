"""roles, users, staff_profiles"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._common import utcnow


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))


class User(Base):
    """A login account (Admin / Receptionist / Trainer)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    role: Mapped["Role"] = relationship(lazy="joined")
    staff_profile: Mapped[Optional["StaffProfile"]] = relationship(
        back_populates="user", uselist=False
    )


class StaffProfile(Base):
    """Extra details for staff (trainers and receptionists). One per user."""

    __tablename__ = "staff_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    phone: Mapped[str] = mapped_column(String(20))
    address: Mapped[Optional[str]] = mapped_column(String(255))
    specialization: Mapped[Optional[str]] = mapped_column(String(120))
    working_schedule: Mapped[Optional[str]] = mapped_column(String(255))
    hire_date: Mapped[Optional[date]] = mapped_column(Date)
    salary: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(
        Enum("active", "on_leave", "inactive", name="staff_status", native_enum=False, length=20),
        default="active",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="staff_profile", lazy="joined")
    members: Mapped[list["Member"]] = relationship(back_populates="assigned_trainer")
