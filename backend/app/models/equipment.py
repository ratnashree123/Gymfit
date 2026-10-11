"""equipment, equipment_maintenance"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._common import utcnow


class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_code: Mapped[str] = mapped_column(String(20), unique=True)  # e.g. EQ-0001
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    brand_model: Mapped[Optional[str]] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    purchase_date: Mapped[Optional[date]] = mapped_column(Date)
    purchase_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    condition_status: Mapped[str] = mapped_column(
        Enum("new", "good", "fair", "poor", name="equipment_condition", native_enum=False, length=10),
        default="good",
    )
    location: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        Enum("available", "damaged", "under_maintenance",
             name="equipment_status", native_enum=False, length=20),
        default="available",
    )
    last_maintenance_date: Mapped[Optional[date]] = mapped_column(Date)
    next_maintenance_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    maintenance_records: Mapped[list["EquipmentMaintenance"]] = relationship(back_populates="equipment")


class EquipmentMaintenance(Base):
    """Maintenance history. Never deleted."""

    __tablename__ = "equipment_maintenance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), index=True)
    maintenance_type: Mapped[str] = mapped_column(
        Enum("routine", "repair", "inspection", name="maintenance_type", native_enum=False, length=20),
        default="routine",
    )
    status: Mapped[str] = mapped_column(
        Enum("scheduled", "in_progress", "completed", "cancelled",
             name="maintenance_status", native_enum=False, length=20),
        default="scheduled",
    )
    scheduled_date: Mapped[date] = mapped_column(Date)
    performed_date: Mapped[Optional[date]] = mapped_column(Date)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    performed_by: Mapped[Optional[str]] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    equipment: Mapped["Equipment"] = relationship(back_populates="maintenance_records")
