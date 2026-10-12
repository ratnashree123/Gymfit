"""Shared test setup. Tests use an in-memory SQLite database, so your real MySQL
data is never touched and no .env file is needed."""
import os

# Must be set BEFORE the app is imported (settings are read at import time).
os.environ["DB_USER"] = "test_user"
os.environ["DB_PASSWORD"] = "test_password"
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-only-1234567890"
os.environ["APP_ENV"] = "testing"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, StaffProfile, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import login_limiter, photo_service  # noqa: E402

ADMIN_EMAIL = "admin@gymfit.com"
ADMIN_PASSWORD = "AdminPass123"


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add_all([
            Role(id=1, name="Admin"),
            Role(id=2, name="Receptionist"),
            Role(id=3, name="Trainer"),
        ])
        db.commit()
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    login_limiter.clear_all()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def make_user(session_factory):
    """make_user("Trainer", "t@gymfit.com") -> user id"""

    def _make(role_name, email, password="Password123", full_name="Test User",
              active=True, with_profile=False):
        with session_factory() as db:
            role = db.query(Role).filter_by(name=role_name).one()
            user = User(role_id=role.id, full_name=full_name, email=email,
                        password_hash=hash_password(password), is_active=active)
            db.add(user)
            db.flush()
            if with_profile:
                db.add(StaffProfile(user_id=user.id, phone="9876543210", status="active"))
            db.commit()
            return user.id

    return _make


@pytest.fixture()
def login(client):
    """login(email, password) -> Authorization header dict"""

    def _login(email, password):
        response = client.post("/api/auth/login", data={"username": email, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login


@pytest.fixture()
def admin_headers(make_user, login):
    make_user("Admin", ADMIN_EMAIL, ADMIN_PASSWORD, full_name="Main Admin")
    return login(ADMIN_EMAIL, ADMIN_PASSWORD)


NEW_TRAINER = {
    "full_name": "Ravi Kumar",
    "email": "ravi@gymfit.com",
    "password": "TrainerPass1",
    "role": "Trainer",
    "phone": "+91 98765-43210",
    "specialization": "Strength training",
    "salary": "30000.00",
}


NEW_MEMBER = {
    "full_name": "Anita Sharma",
    "phone": "9811122233",
    "email": "anita@example.com",
    "gender": "female",
}


@pytest.fixture(autouse=True)
def isolated_upload_dir(tmp_path, monkeypatch):
    """Photos written by tests go to a temporary folder that is deleted afterwards."""
    monkeypatch.setattr(photo_service, "UPLOAD_ROOT", tmp_path / "uploads")


@pytest.fixture()
def reception_headers(make_user, login):
    make_user("Receptionist", "desk@gymfit.com", "DeskPass123", full_name="Front Desk")
    return login("desk@gymfit.com", "DeskPass123")


@pytest.fixture()
def trainer(client, admin_headers, login):
    """Creates a trainer through the API. Returns (staff_profile_id, auth_headers)."""
    response = client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER)
    assert response.status_code == 201, response.text
    return response.json()["id"], login(NEW_TRAINER["email"], NEW_TRAINER["password"])


@pytest.fixture()
def make_plan(client, admin_headers):
    """make_plan("Monthly", 30, "1500") -> plan dict"""

    def _make(name="Monthly", days=30, price="1500", **extra):
        response = client.post("/api/plans", headers=admin_headers,
                               json={"name": name, "duration_days": days, "price": price, **extra})
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture()
def make_member(client, admin_headers):
    """make_member(phone="9000000001", name="X", **extra) -> member dict"""
    counter = {"n": 0}

    def _make(headers=None, **fields):
        counter["n"] += 1
        payload = {**NEW_MEMBER, "phone": f"98000{counter['n']:05d}",
                   "full_name": f"Member {counter['n']}", "email": None, **fields}
        response = client.post("/api/members", headers=headers or admin_headers, json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture()
def set_setting(session_factory):
    """set_setting("tax_percent", "18") changes a gym setting for one test."""
    from app.models import GymSetting

    def _set(key, value):
        with session_factory() as db:
            row = db.get(GymSetting, key)
            if row is not None:
                row.setting_value = value
            else:
                db.add(GymSetting(setting_key=key, setting_value=value))
            db.commit()

    return _set


@pytest.fixture()
def backdate_invoice(session_factory):
    """backdate_invoice(invoice_id, days) moves the due date into the past."""
    from datetime import timedelta
    from app.models import Invoice
    from app.utils.dates import gym_today

    def _backdate(invoice_id, days=3):
        with session_factory() as db:
            db.get(Invoice, invoice_id).due_date = gym_today() - timedelta(days=days)
            db.commit()

    return _backdate


@pytest.fixture()
def billed_member(client, admin_headers, make_plan, make_member):
    """A member with a 1500.00 monthly membership. Returns (member, invoice_id)."""

    def _make(price="1500", **member_fields):
        plan = make_plan(f"Plan {price} {len(client.get('/api/plans', headers=admin_headers).json())}", 30, price)
        member = make_member(plan_id=plan["id"], **member_fields)
        invoice_id = member["current_membership"]["invoice"]["id"]
        return member, invoice_id

    return _make


@pytest.fixture()
def paid_member(client, admin_headers, make_plan, make_member):
    """A member whose membership fee is fully paid, so the front desk may let them in."""

    def _make(days=30, **fields):
        number = len(client.get("/api/plans", headers=admin_headers).json())
        plan = make_plan(f"Paid plan {number}", days, "1000")
        member = make_member(plan_id=plan["id"], **fields)
        invoice_id = member["current_membership"]["invoice"]["id"]
        response = client.post(f"/api/invoices/{invoice_id}/payments", headers=admin_headers,
                               json={"amount": "1000", "method": "cash"})
        assert response.status_code == 201, response.text
        return member

    return _make


@pytest.fixture()
def add_visit(session_factory):
    """add_visit(member_id, check_in_utc, check_out_utc=None, status=None, minutes=None) -> id
    Writes an attendance row directly, with exact UTC times."""
    from app.models import Attendance
    from app.services.attendance_rules import visit_minutes

    def _add(member_id, check_in, check_out=None, status=None, minutes=None):
        with session_factory() as db:
            visit = Attendance(
                member_id=member_id, check_in_at=check_in, check_out_at=check_out,
                status=status or ("inside" if check_out is None else "completed"),
                duration_minutes=minutes if minutes is not None
                else (visit_minutes(check_in, check_out) if check_out else None))
            db.add(visit)
            db.commit()
            return visit.id

    return _add


@pytest.fixture()
def shift_visit(session_factory):
    """shift_visit(attendance_id, hours=0, minutes=0) pretends the member checked in that long ago."""
    from datetime import timedelta
    from app.models import Attendance
    from app.models._common import utcnow

    def _shift(attendance_id, hours=0, minutes=0):
        with session_factory() as db:
            db.get(Attendance, attendance_id).check_in_at = utcnow() - timedelta(hours=hours, minutes=minutes)
            db.commit()

    return _shift
