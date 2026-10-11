"""Login, password change."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import BadRequestError, ForbiddenError, TooManyRequestsError, UnauthorizedError
from app.models import User
from app.models._common import utcnow
from app.security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.services import login_limiter
from app.services.audit_service import log_action


def authenticate(db: Session, email_raw: str, password: str, ip: str | None) -> User:
    email = (email_raw or "").strip().lower()

    wait = login_limiter.seconds_until_unblocked(email, ip)
    if wait > 0:
        raise TooManyRequestsError(
            "Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(select(User).where(User.email == email))
    stored_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    password_ok = verify_password(password, stored_hash)

    if user is None or not password_ok:
        login_limiter.record_failure(email, ip)
        log_action(
            db, user_id=user.id if user else None, action="auth.login_failed",
            entity_type="user", entity_id=user.id if user else None,
            new={"email": email[:150]}, ip=ip,
        )
        db.commit()
        # Same message for "unknown e-mail" and "wrong password".
        raise UnauthorizedError("Incorrect email or password")

    if not user.is_active:
        raise ForbiddenError("This account is disabled. Please contact an administrator.")

    login_limiter.reset(email, ip)
    user.last_login_at = utcnow()
    log_action(db, user_id=user.id, action="auth.login", entity_type="user",
               entity_id=user.id, ip=ip)
    db.commit()
    return user


def change_password(db: Session, user: User, current_password: str, new_password: str,
                    ip: str | None) -> None:
    if not verify_password(current_password, user.password_hash):
        # 400 (not 401) so the frontend does not log the user out by mistake.
        raise BadRequestError("Current password is incorrect")
    if verify_password(new_password, user.password_hash):
        raise BadRequestError("New password must be different from the current password")

    user.password_hash = hash_password(new_password)
    log_action(db, user_id=user.id, action="auth.password_change", entity_type="user",
               entity_id=user.id, ip=ip)
    db.commit()
