"""Membership (a member's plan period) schemas."""
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.billing import DiscountFields, InvoiceBrief
from app.schemas.common import UTCDateTime


class AssignMembershipIn(DiscountFields):
    model_config = ConfigDict(extra="forbid")

    plan_id: int
    start_date: Optional[date] = None  # default: today, or the day after the current one ends


class RenewMembershipIn(DiscountFields):
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
    invoice: Optional[InvoiceBrief] = None  # None for a free (0.00) membership
    created_at: UTCDateTime
