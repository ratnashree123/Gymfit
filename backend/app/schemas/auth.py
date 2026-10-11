"""Login and current-user schemas."""
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.common import Password, UTCDateTime


class UserOut(BaseModel):
    id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    last_login_at: Optional[UTCDateTime] = None

    @classmethod
    def from_user(cls, user) -> "UserOut":
        return cls(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=user.role.name,
            is_active=user.is_active,
            last_login_at=user.last_login_at,
        )


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: Password


class MessageOut(BaseModel):
    message: str
