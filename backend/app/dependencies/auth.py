"""'Who is calling?' and 'are they allowed?' checks, used with Depends(...)."""
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.constants import ROLE_ADMIN, ROLE_RECEPTIONIST, ROLE_TRAINER
from app.database import get_db
from app.models import User
from app.security import decode_access_token

# Tells Swagger UI where to log in (adds the green "Authorize" button).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Reads the token, then loads the user from the database on every request.

    The role is taken from the database (not from the token), so deactivating a user
    or changing their role takes effect immediately.
    """
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise _CREDENTIALS_ERROR

    subject = str(payload.get("sub", ""))
    if not subject.isdigit():
        raise _CREDENTIALS_ERROR

    user = db.get(User, int(subject))
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user


def require_roles(*allowed_roles: str):
    """Build a dependency that only lets the listed roles through (others get 403)."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role.name not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user

    return checker


require_admin = require_roles(ROLE_ADMIN)
require_front_desk = require_roles(ROLE_ADMIN, ROLE_RECEPTIONIST)  # money and member desk work
require_fitness_staff = require_roles(ROLE_ADMIN, ROLE_TRAINER)  # workout plans and body measurements
require_any_staff = require_roles(ROLE_ADMIN, ROLE_RECEPTIONIST, ROLE_TRAINER)
