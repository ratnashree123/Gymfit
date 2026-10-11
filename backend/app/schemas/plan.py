"""Membership plan schemas."""
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import OptNotes, OptText255, PlanType, UTCDateTime

PlanName = Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
Price = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
DurationDays = Annotated[int, Field(ge=1, le=3650)]


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: PlanName
    plan_type: PlanType = "membership"
    duration_days: DurationDays
    price: Price
    description: OptText255 = None
    benefits: OptNotes = None
    is_active: bool = True


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Optional[PlanName] = None
    duration_days: Optional[DurationDays] = None
    price: Optional[Price] = None
    description: OptText255 = None
    benefits: OptNotes = None
    is_active: Optional[bool] = None


class PlanOut(BaseModel):
    id: int
    name: str
    plan_type: str
    duration_days: int
    price: Decimal
    description: Optional[str] = None
    benefits: Optional[str] = None
    is_active: bool
    created_at: UTCDateTime

    @classmethod
    def from_plan(cls, plan) -> "PlanOut":
        return cls(
            id=plan.id, name=plan.name, plan_type=plan.plan_type,
            duration_days=plan.duration_days, price=plan.price,
            description=plan.description, benefits=plan.benefits,
            is_active=plan.is_active, created_at=plan.created_at,
        )
