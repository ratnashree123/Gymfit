"""attendance"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Computed, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._common import BigIntPK


class Attendance(Base):
    __tablename__ = "attendance"
    # Same unique index as schema.sql: one open visit per member, enforced by the database.
    __table_args__ = (Index("uq_attendance_one_open", "open_member_id", unique=True),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    check_in_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    check_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        Enum("inside", "completed", "auto_closed", "corrected",
             name="attendance_status", native_enum=False, length=20),
        default="inside",
    )
    checked_in_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    checked_out_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[Optional[str]] = mapped_column(String(255))
    # Filled by the database itself. In MySQL (schema.sql) it has a UNIQUE index, so one
    # member can never have two open visits. The ORM never writes to this column.
    open_member_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        Computed("CASE WHEN check_out_at IS NULL THEN member_id ELSE NULL END", persisted=True),
    )

    member: Mapped["Member"] = relationship(back_populates="attendance_records")
    checked_in_user: Mapped[Optional["User"]] = relationship(foreign_keys="Attendance.checked_in_by")
    checked_out_user: Mapped[Optional["User"]] = relationship(foreign_keys="Attendance.checked_out_by")
