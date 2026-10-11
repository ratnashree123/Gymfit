"""Creates the first Admin account from the FIRST_ADMIN_* values in .env.

Run from the backend folder (venv active):
    python -m app.scripts.create_admin

Safe to run again: it does nothing if an Admin already exists.
"""
import sys

from sqlalchemy import select

from app import models  # noqa: F401
from app.config import get_settings
from app.constants import ROLE_ADMIN
from app.database import SessionLocal
from app.models import Role, User
from app.schemas.common import normalize_email, validate_password_strength
from app.security import hash_password
from app.services.audit_service import log_action


def main() -> int:
    settings = get_settings()

    if not settings.first_admin_email or not settings.first_admin_password:
        print("Add FIRST_ADMIN_EMAIL and FIRST_ADMIN_PASSWORD to backend/.env first.")
        return 1

    try:
        email = normalize_email(settings.first_admin_email)
        validate_password_strength(settings.first_admin_password)
    except ValueError as error:
        print(f"Invalid FIRST_ADMIN value: {error}")
        return 1

    with SessionLocal() as db:
        admin_role = db.scalar(select(Role).where(Role.name == ROLE_ADMIN))
        if admin_role is None:
            print("The roles table is empty. Run database/schema.sql in MySQL first.")
            return 1

        existing_admin = db.scalar(select(User).where(User.role_id == admin_role.id).limit(1))
        if existing_admin is not None:
            print(f"An Admin already exists ({existing_admin.email}). Nothing to do.")
            return 0

        user = User(
            role_id=admin_role.id,
            full_name=settings.first_admin_name.strip() or "Gym Admin",
            email=email,
            password_hash=hash_password(settings.first_admin_password),
            is_active=True,
        )
        db.add(user)
        db.flush()
        log_action(db, user_id=None, action="admin.bootstrap", entity_type="user",
                   entity_id=user.id, new={"email": email})
        db.commit()

    print(f"Admin created: {email}")
    print("Log in at http://127.0.0.1:8000/docs. You may now remove FIRST_ADMIN_PASSWORD from .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
