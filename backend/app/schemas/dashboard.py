"""Dashboard, notification and membership-report schemas."""
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.attendance import AttendanceOut
from app.schemas.billing import RevenueReport
from app.schemas.common import Page, UTCDateTime
from app.schemas.member import MemberListItem

NotificationType = Literal["membership_expiring", "membership_expired", "payment_pending",
                           "maintenance_due", "system"]


# ------------------------------------------------------------------ dashboard
class DashboardMembers(BaseModel):
    total: int
    active: int
    inactive: int
    joined_this_month: int


class DashboardMemberships(BaseModel):
    active: int
    expiring_soon: int
    expired: int
    upcoming: int
    no_membership: int
    inactive: int
    alert_days: int


class DashboardAttendance(BaseModel):
    visits_today: int
    inside_now: int
    stale_inside: int  # inside for longer than the auto-checkout limit


class DashboardMoney(BaseModel):
    collected_today: Decimal
    payments_today: int
    collected_this_month: Decimal
    pending_count: int
    overdue_count: int
    outstanding_total: Decimal
    overdue_total: Decimal


class DashboardEquipment(BaseModel):
    records: int
    total_quantity: int
    damaged: int
    under_maintenance: int
    urgent: int
    soon: int


class DistributionSlice(BaseModel):
    label: str
    members: int


class DashboardOut(BaseModel):
    role: str
    scope: str  # "all" or "own_members" (a Trainer sees only their own members)
    generated_at: UTCDateTime
    members: DashboardMembers
    memberships: DashboardMemberships
    attendance: DashboardAttendance
    money: Optional[DashboardMoney] = None  # not for Trainers
    trainers_total: Optional[int] = None  # not for Trainers
    equipment: DashboardEquipment
    revenue_chart: Optional[RevenueReport] = None  # Admin only: last 6 months
    membership_distribution: list[DistributionSlice]
    recent_members: list[MemberListItem]
    recent_attendance: list[AttendanceOut]
    unread_notifications: int


# ------------------------------------------------------------------ notifications
class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    message: str
    related_type: Optional[str] = None  # member | invoice | equipment_urgent | equipment_soon
    related_id: Optional[int] = None
    is_read: bool
    created_at: UTCDateTime


class NotificationPage(Page[NotificationOut]):
    unread_count: int


class UnreadCount(BaseModel):
    unread: int


class SyncOut(BaseModel):
    skipped: bool  # True when a refresh ran very recently
    created: int = 0
    updated: int = 0
    removed: int = 0


class MarkedOut(BaseModel):
    marked: int


# ------------------------------------------------------------------ membership report
class StatusCounts(BaseModel):
    total: int
    active: int
    expiring_soon: int
    upcoming: int
    expired: int
    no_membership: int
    inactive: int


class MembershipReportPage(Page[MemberListItem]):
    summary: StatusCounts  # the whole gym, not only the filtered rows
