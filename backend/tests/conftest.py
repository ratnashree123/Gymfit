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
