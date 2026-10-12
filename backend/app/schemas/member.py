"""Member schemas."""
from datetime import date
from typing import Optional

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator, model_validator

from app.schemas.billing import DiscountFields
from app.schemas.common import (
    Gender, MemberStatus, Name, OptEmail, OptNotes, OptPhone, OptText120,
    OptText255, PhoneNumber, UTCDateTime,
)
from app.schemas.membership import MembershipOut
from app.utils.dates import gym_today


def _check_birth_date(value: date) -> date:
    if value > gym_today():
        raise ValueError("Date of birth cannot be in the future")
    if value < date(1900, 1, 1):
        raise ValueError("Date of birth is not realistic")
    return value


BirthDate = Optional[Annotated[date, AfterValidator(_check_birth_date)]]


class MemberCreate(DiscountFields):
    model_config = ConfigDict(extra="forbid")

    full_name: Name
    phone: PhoneNumber
    email: OptEmail = None
    gender: Optional[Gender] = None
    date_of_birth: BirthDate = None
    address: OptText255 = None
    emergency_contact_name: OptText120 = None
    emergency_contact_phone: OptPhone = None
    medical_notes: OptNotes = None
    assigned_trainer_id: Optional[int] = None
    registration_date: Optional[date] = None
    # Optional: give the new member a plan straight away (saved in the same transaction).
    plan_id: Optional[int] = None
    membership_start_date: Optional[date] = None


    @field_validator("registration_date")
    @classmethod
    def registration_not_in_future(cls, value):
        if value is not None and value > gym_today():
            raise ValueError("Registration date cannot be in the future")
        return value

    @model_validator(mode="after")
    def start_date_needs_plan(self):
        if self.plan_id is None and (
            self.membership_start_date is not None
            or self.discount_percent is not None
            or self.discount_amount is not None
        ):
            raise ValueError("membership_start_date and discounts need a plan_id")
        return self


class MemberUpdate(BaseModel):
    """Only the fields you send are changed."""

    model_config = ConfigDict(extra="forbid")

    full_name: Optional[Name] = None
    phone: Optional[PhoneNumber] = None
    email: OptEmail = None
    gender: Optional[Gender] = None
    date_of_birth: BirthDate = None
    address: OptText255 = None
    emergency_contact_name: OptText120 = None
    emergency_contact_phone: OptPhone = None
    medical_notes: OptNotes = None  # Admin only
    status: Optional[MemberStatus] = None
    assigned_trainer_id: Optional[int] = None



class TrainerRef(BaseModel):
    id: int
    full_name: str


class MemberListItem(BaseModel):
    id: int
    member_code: str
    full_name: str
    phone: str
    email: Optional[str] = None
    gender: Optional[str] = None
    status: str  # active | inactive
    registration_date: date
    membership_status: str  # active | upcoming | expired | no_membership | inactive
    plan_name: Optional[str] = None
    expires_on: Optional[date] = None
    days_left: Optional[int] = None
    expiring_soon: bool = False
    assigned_trainer: Optional[TrainerRef] = None
    has_photo: bool = False


class MemberDetailOut(MemberListItem):
    date_of_birth: Optional[date] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    photo_url: Optional[str] = None
    medical_notes: Optional[str] = None
    medical_notes_visible: bool = False  # False = your role may not see the notes
    current_membership: Optional[MembershipOut] = None
    is_deleted: bool = False
    created_at: UTCDateTime
    updated_at: UTCDateTime
