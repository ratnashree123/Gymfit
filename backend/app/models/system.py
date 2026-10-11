"""notifications, audit_logs, gym_settings"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models._common import BigIntPK, utcnow


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(
        Enum("membership_expiring", "membership_expired", "payment_pending",
             "maintenance_due", "system", name="notification_type", native_enum=False, length=30)
    )
    title: Mapped[str] = mapped_column(String(150))
    message: Mapped[str] = mapped_column(String(255))
    related_type: Mapped[Optional[str]] = mapped_column(String(40))
    related_id: Mapped[Optional[int]] = mapped_column(Integer)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """Who changed what, and when. Never store passwords or password hashes here."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    old_values: Mapped[Optional[dict]] = mapped_column(JSON)
    new_values: Mapped[Optional[dict]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GymSetting(Base):
    __tablename__ = "gym_settings"

    setting_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    setting_value: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(255))
