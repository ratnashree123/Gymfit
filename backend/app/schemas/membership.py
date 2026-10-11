"""Membership (a member's plan period) schemas."""
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.common import UTCDateTime


class AssignMembershipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: int
    start_date: Optional[date] = None  # default: today, or the day after the current one ends


class RenewMembershipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: Optional[int] = None  # default: the same plan as last time
    start_date: Optional[date] = None


class MembershipOut(BaseModel):
    id: int
    member_id: int
    plan_id: int
    plan_name: str
    start_date: date
    end_date: date
    price_at_purchase: Decimal
    is_renewal: bool
    state: str  # upcoming | active | expired | cancelled
    created_at: UTCDateTime
