"""Password hashing (bcrypt) and login tokens (JWT)."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import get_settings

ALGORITHM = "HS256"
MAX_PASSWORD_BYTES = 72  # bcrypt cannot use more than 72 bytes


def hash_password(plain: str) -> str:
    """Turn a password into a salted bcrypt hash. The plain password is never stored."""
    raw = plain.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long (max 72 bytes)")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    raw = plain.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, hashed.encode("ascii"))
    except ValueError:
        return False


# Used when the e-mail does not exist, so the response time is the same as for a
# wrong password. This stops attackers from discovering which e-mails are registered.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-password-1")


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    """Return (token, seconds_until_expiry)."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + lifetime}
    token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError if the token is invalid, tampered with, or expired."""
    return jwt.decode(
        token,
        get_settings().secret_key,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
