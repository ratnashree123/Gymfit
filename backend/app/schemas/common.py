"""Reusable validated field types and the pagination wrapper."""
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Generic, Literal, Optional, TypeVar

from pydantic import AfterValidator, BaseModel, Field, PlainSerializer, StringConstraints

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 150 or not _EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address")
    return value


def validate_password_strength(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password is too long (max 72 bytes)")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain at least one letter and one number")
    return value


def normalize_phone(value: str) -> str:
    cleaned = re.sub(r"[\s\-()]", "", value)
    if not _PHONE_RE.match(cleaned):
        raise ValueError("Enter a valid phone number (7 to 15 digits, optional leading +)")
    return cleaned


def _to_utc_iso(value: datetime) -> str:
    """Database times are UTC. Send them with a 'Z' so the browser converts correctly."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


EmailAddress = Annotated[str, AfterValidator(normalize_email)]
Password = Annotated[str, AfterValidator(validate_password_strength)]
PhoneNumber = Annotated[str, AfterValidator(normalize_phone)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Text120 = Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]]
Text255 = Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]]
Money = Optional[Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]]
UTCDateTime = Annotated[datetime, PlainSerializer(_to_utc_iso, return_type=str, when_used="json")]

RoleName = Literal["Admin", "Receptionist", "Trainer"]
StaffStatus = Literal["active", "on_leave", "inactive"]

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


# ---------- optional fields where "" (an empty form box) means "nothing" ----------
from pydantic import BeforeValidator  # noqa: E402


def _blank_to_none(value):
    if isinstance(value, str) and not value.strip():
        return None
    return value


blank_to_none = _blank_to_none

OptEmail = Annotated[Optional[EmailAddress], BeforeValidator(_blank_to_none)]
OptPhone = Annotated[Optional[PhoneNumber], BeforeValidator(_blank_to_none)]
OptText120 = Annotated[
    Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]],
    BeforeValidator(_blank_to_none),
]
OptText255 = Annotated[
    Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]],
    BeforeValidator(_blank_to_none),
]
OptNotes = Annotated[
    Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]],
    BeforeValidator(_blank_to_none),
]

Gender = Literal["male", "female", "other"]
MemberStatus = Literal["active", "inactive"]
PlanType = Literal["membership", "addon"]
