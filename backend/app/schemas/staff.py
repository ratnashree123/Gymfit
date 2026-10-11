"""Staff (trainer / receptionist / admin) schemas."""
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.common import (
    EmailAddress, Money, Name, Password, PhoneNumber, RoleName,
    StaffStatus, Text120, Text255, UTCDateTime,
)


class StaffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields are rejected

    full_name: Name
    email: EmailAddress
    password: Password
    role: RoleName
    phone: PhoneNumber
    address: Text255 = None
    specialization: Text120 = None
    working_schedule: Text255 = None
    hire_date: Optional[date] = None
    salary: Money = None


class StaffUpdate(BaseModel):
    """Every field is optional: only the fields you send are changed."""

    model_config = ConfigDict(extra="forbid")

    full_name: Optional[Name] = None
    role: Optional[RoleName] = None
    phone: Optional[PhoneNumber] = None
    address: Text255 = None
    specialization: Text120 = None
    working_schedule: Text255 = None
    hire_date: Optional[date] = None
    salary: Money = None
    status: Optional[StaffStatus] = None


class PasswordResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: Password


class StaffAdminOut(BaseModel):
    """Full view, including salary. Only Admins ever receive this."""

    id: int
    user_id: int
    full_name: str
    email: str
    role: str
    phone: str
    address: Optional[str] = None
    specialization: Optional[str] = None
    working_schedule: Optional[str] = None
    hire_date: Optional[date] = None
    salary: Optional[Decimal] = None
    status: str
    is_active: bool
    created_at: UTCDateTime

    @classmethod
    def from_profile(cls, profile) -> "StaffAdminOut":
        user = profile.user
        return cls(
            id=profile.id,
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=user.role.name,
            phone=profile.phone,
            address=profile.address,
            specialization=profile.specialization,
            working_schedule=profile.working_schedule,
            hire_date=profile.hire_date,
            salary=profile.salary,
            status=profile.status,
            is_active=user.is_active,
            created_at=profile.created_at,
        )


class StaffPublicOut(BaseModel):
    """Safe view (no salary, no email, no address) for dropdowns such as 'assign trainer'."""

    id: int
    full_name: str
    specialization: Optional[str] = None
    working_schedule: Optional[str] = None
    status: str

    @classmethod
    def from_profile(cls, profile) -> "StaffPublicOut":
        return cls(
            id=profile.id,
            full_name=profile.user.full_name,
            specialization=profile.specialization,
            working_schedule=profile.working_schedule,
            status=profile.status,
        )
