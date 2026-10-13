"""Equipment and maintenance schemas."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from app.schemas.common import (
    Money, OptNotes, OptText120, OptText255, Page, UTCDateTime, blank_to_none,
)
from app.utils.dates import gym_today

Condition = Literal["new", "good", "fair", "poor"]
EquipmentStatus = Literal["available", "damaged", "under_maintenance"]
SettableStatus = Literal["available", "damaged"]  # 'under_maintenance' only comes from a maintenance job
JobType = Literal["routine", "repair", "inspection"]
JobStatus = Literal["scheduled", "in_progress", "completed", "cancelled"]
Attention = Literal["urgent", "soon"]

SaneDate = Annotated[date, Field(ge=date(2000, 1, 1), le=date(2100, 12, 31))]
Quantity = Annotated[int, Field(ge=1, le=100000)]
Cost = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
ItemName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]
OptReason = Annotated[Optional[Reason], BeforeValidator(blank_to_none)]
OptLocation = Annotated[
    Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]],
    BeforeValidator(blank_to_none),
]


def _not_in_future(value: date) -> date:
    if value > gym_today():
        raise ValueError("This date cannot be in the future")
    return value


PastDate = Optional[Annotated[SaneDate, AfterValidator(_not_in_future)]]


# ----------------------------------------------------------------- equipment
class EquipmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ItemName
    category: Category
    brand_model: OptText120 = None
    quantity: Quantity = 1
    purchase_date: PastDate = None
    purchase_price: Money = None  # the price of ONE item
    condition_status: Condition = "good"
    location: OptLocation = None
    status: SettableStatus = "available"
    last_maintenance_date: PastDate = None
    next_maintenance_date: Optional[SaneDate] = None
    notes: OptNotes = None


class EquipmentUpdate(BaseModel):
    """Only the fields you send are changed."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[ItemName] = None
    category: Optional[Category] = None
    brand_model: OptText120 = None
    quantity: Optional[Quantity] = None
    purchase_date: PastDate = None
    purchase_price: Money = None
    condition_status: Optional[Condition] = None
    location: OptLocation = None
    status: Optional[SettableStatus] = None
    last_maintenance_date: PastDate = None
    next_maintenance_date: Optional[SaneDate] = None
    notes: OptNotes = None


class DamageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Reason


class EquipmentBrief(BaseModel):
    id: int
    equipment_code: str
    name: str
    category: str
    location: Optional[str] = None
    quantity: int
    status: str
    condition_status: str


class MaintenanceOut(BaseModel):
    id: int
    equipment: EquipmentBrief
    maintenance_type: str
    status: str
    scheduled_date: date
    performed_date: Optional[date] = None
    is_overdue: bool = False
    cost: Optional[Decimal] = None  # Admin only
    cost_visible: bool = False
    performed_by: Optional[str] = None
    description: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: UTCDateTime


class EquipmentOut(BaseModel):
    id: int
    equipment_code: str
    name: str
    category: str
    brand_model: Optional[str] = None
    quantity: int
    purchase_date: Optional[date] = None
    condition_status: str
    location: Optional[str] = None
    status: str
    last_maintenance_date: Optional[date] = None
    next_maintenance_date: Optional[date] = None
    notes: Optional[str] = None
    is_archived: bool
    attention_level: str  # urgent | soon | ok
    attention_code: str
    attention_message: str
    due_date: Optional[date] = None
    purchase_price: Optional[Decimal] = None  # Admin only
    total_value: Optional[Decimal] = None  # Admin only (price x quantity)
    financials_visible: bool = False
    created_at: UTCDateTime
    updated_at: UTCDateTime


class EquipmentDetailOut(EquipmentOut):
    open_jobs: int = 0
    maintenance_cost_total: Optional[Decimal] = None  # Admin only
    repair_cost_total: Optional[Decimal] = None  # Admin only
    recent_maintenance: list[MaintenanceOut] = []


class EquipmentPage(Page[EquipmentOut]):
    pass


# ----------------------------------------------------------------- maintenance jobs
class MaintenanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maintenance_type: JobType
    scheduled_date: SaneDate
    description: OptNotes = None
    performed_by: OptText120 = None  # technician or company


class MaintenanceUpdate(BaseModel):
    """Only scheduled or in-progress jobs can be edited. Finished jobs are history."""

    model_config = ConfigDict(extra="forbid")

    maintenance_type: Optional[JobType] = None
    scheduled_date: Optional[SaneDate] = None
    description: OptNotes = None
    performed_by: OptText120 = None


class MaintenanceStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    performed_by: OptText120 = None


class MaintenanceComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    performed_date: PastDate = None  # default: today
    cost: Cost = Decimal("0.00")
    performed_by: OptText120 = None
    notes: OptNotes = None  # what was done; added to the description
    next_maintenance_date: Optional[SaneDate] = None  # send null to clear the schedule
    condition_after: Optional[Condition] = None


class MaintenanceCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: OptReason = None


class MaintenancePage(Page[MaintenanceOut]):
    total_cost: Optional[Decimal] = None  # Admin only: completed jobs matching the filters


# ----------------------------------------------------------------- reminders and reports
class ReminderItem(BaseModel):
    equipment: EquipmentBrief
    level: str
    code: str
    message: str
    due_date: Optional[date] = None


class RemindersOut(BaseModel):
    alert_days: int
    urgent_count: int
    soon_count: int
    urgent: list[ReminderItem]
    soon: list[ReminderItem]


class CountRow(BaseModel):
    name: str
    records: int
    quantity: int


class InventoryReport(BaseModel):
    records: int
    total_quantity: int
    archived_records: int
    total_value: Decimal
    by_status: list[CountRow]
    by_condition: list[CountRow]
    by_category: list[CountRow]
    urgent_count: int
    soon_count: int
    open_jobs: int
    overdue_jobs: int
    maintenance_cost_total: Decimal
    repair_cost_total: Decimal
