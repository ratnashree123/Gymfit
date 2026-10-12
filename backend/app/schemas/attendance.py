"""Attendance schemas."""
from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.schemas.billing import MemberRef
from app.schemas.common import Page, UTCDateTime

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)]
AttendanceStatus = Literal["inside", "completed", "auto_closed", "corrected"]
AttendancePeriod = Literal["day", "week", "month"]


class AccessOut(BaseModel):
    allowed: bool
    code: str
    message: str
    expires_on: Optional[date] = None
    in_grace: bool = False


class CheckInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: int
    override_reason: Optional[Reason] = None  # Admin only, when access is denied


class CheckOutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: int


class AttendanceOut(BaseModel):
    id: int
    member: MemberRef
    check_in_at: UTCDateTime
    check_in_local: str
    check_out_at: Optional[UTCDateTime] = None
    check_out_local: Optional[str] = None
    duration_minutes: Optional[int] = None
    minutes_inside: Optional[int] = None  # only while the member is still inside
    status: str
    is_stale: bool = False  # inside for longer than the auto-checkout limit: probably forgot to check out
    checked_in_by_name: Optional[str] = None
    checked_out_by_name: Optional[str] = None
    notes: Optional[str] = None


class InsideOut(BaseModel):
    count: int
    stale_count: int
    items: list[AttendanceOut]


class LookupItem(BaseModel):
    member: MemberRef
    phone: str
    status: str
    inside: bool
    inside_since_local: Optional[str] = None
    access: AccessOut


class AttendanceCorrection(BaseModel):
    """Admin fix. A time without an offset (10:00) is read as the gym's local time."""

    model_config = ConfigDict(extra="forbid")

    check_in_at: Optional[datetime] = None
    check_out_at: Optional[datetime] = None
    reason: Reason

    @model_validator(mode="after")
    def at_least_one_time(self):
        if self.check_in_at is None and self.check_out_at is None:
            raise ValueError("Send check_in_at and/or check_out_at")
        return self


class RemoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class CloseStaleOut(BaseModel):
    closed: int


class SeriesPoint(BaseModel):
    label: str
    visits: int
    unique_members: int


class AttendanceReport(BaseModel):
    period: str
    date_from: date
    date_to: date
    visits: int
    unique_members: int
    avg_duration_minutes: Optional[float] = None  # completed visits only (auto-closed ones are guesses)
    auto_closed_count: int
    corrected_count: int
    still_inside: int
    peak_label: Optional[str] = None  # busiest hour (day) or busiest date (week / month)
    peak_visits: int
    series: list[SeriesPoint]


class AttendancePage(Page[AttendanceOut]):
    pass
