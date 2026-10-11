"""members"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._common import utcnow


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_code: Mapped[str] = mapped_column(String(20), unique=True)  # e.g. GF-000001
    full_name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)  # blocks duplicates
    email: Mapped[Optional[str]] = mapped_column(String(150))
    gender: Mapped[Optional[str]] = mapped_column(
        Enum("male", "female", "other", name="member_gender", native_enum=False, length=10)
    )
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    address: Mapped[Optional[str]] = mapped_column(String(255))
    emergency_contact_name: Mapped[Optional[str]] = mapped_column(String(120))
    emergency_contact_phone: Mapped[Optional[str]] = mapped_column(String(20))
    photo_path: Mapped[Optional[str]] = mapped_column(String(255))
    medical_notes: Mapped[Optional[str]] = mapped_column(Text)  # sensitive: role restricted
    registration_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", name="member_status", native_enum=False, length=10),
        default="active",
    )
    assigned_trainer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("staff_profiles.id", ondelete="SET NULL"), index=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    assigned_trainer: Mapped[Optional["StaffProfile"]] = relationship(back_populates="members")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="member")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="member")
    attendance_records: Mapped[list["Attendance"]] = relationship(back_populates="member")
    workout_plans: Mapped[list["WorkoutPlan"]] = relationship(back_populates="member")
    progress_records: Mapped[list["MemberProgress"]] = relationship(back_populates="member")
