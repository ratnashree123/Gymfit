from decimal import Decimal

from tests.conftest import ADMIN_EMAIL, NEW_TRAINER


# ---------- access control ----------
def test_staff_endpoints_require_login(client):
    assert client.get("/api/staff").status_code == 401
    assert client.post("/api/staff", json=NEW_TRAINER).status_code == 401


def test_receptionist_cannot_manage_staff(client, make_user, login):
    make_user("Receptionist", "rec@gymfit.com", "RecPass123")
    headers = login("rec@gymfit.com", "RecPass123")
    assert client.get("/api/staff", headers=headers).status_code == 403
    assert client.post("/api/staff", headers=headers, json=NEW_TRAINER).status_code == 403


def test_trainer_cannot_manage_staff_or_list_trainers(client, make_user, login):
    make_user("Trainer", "trainer@gymfit.com", "TrainPass123")
    headers = login("trainer@gymfit.com", "TrainPass123")
    assert client.get("/api/staff", headers=headers).status_code == 403
    assert client.get("/api/staff/trainers", headers=headers).status_code == 403


# ---------- create ----------
def test_admin_creates_staff(client, admin_headers):
    response = client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ravi@gymfit.com"
    assert body["role"] == "Trainer"
    assert body["phone"] == "+919876543210"  # spaces and dashes removed
    assert Decimal(body["salary"]) == Decimal("30000")
    assert "password" not in response.text.lower()


def test_new_staff_can_log_in(client, admin_headers, login):
    client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER)
    assert login("ravi@gymfit.com", "TrainerPass1")


def test_duplicate_email_returns_409(client, admin_headers):
    assert client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER).status_code == 201
    duplicate = client.post("/api/staff", headers=admin_headers, json={**NEW_TRAINER, "email": "RAVI@gymfit.com"})
    assert duplicate.status_code == 409


def test_invalid_input_returns_422_without_echoing_password(client, admin_headers):
    bad = {**NEW_TRAINER, "password": "weak", "email": "not-an-email", "phone": "abc"}
    response = client.post("/api/staff", headers=admin_headers, json=bad)
    assert response.status_code == 422
    fields = {e["field"] for e in response.json()["errors"]}
    assert {"password", "email", "phone"} <= fields
    assert "weak" not in response.text


def test_unknown_fields_and_bad_role_are_rejected(client, admin_headers):
    assert client.post("/api/staff", headers=admin_headers,
                       json={**NEW_TRAINER, "is_superuser": True}).status_code == 422
    assert client.post("/api/staff", headers=admin_headers,
                       json={**NEW_TRAINER, "role": "Owner"}).status_code == 422


def test_negative_salary_is_rejected(client, admin_headers):
    response = client.post("/api/staff", headers=admin_headers, json={**NEW_TRAINER, "salary": "-5"})
    assert response.status_code == 422


# ---------- read / list ----------
def test_list_search_filter_and_pagination(client, admin_headers):
    for index in range(3):
        client.post("/api/staff", headers=admin_headers, json={
            **NEW_TRAINER, "email": f"trainer{index}@gymfit.com", "full_name": f"Trainer {index}"})
    client.post("/api/staff", headers=admin_headers, json={
        **NEW_TRAINER, "email": "desk@gymfit.com", "full_name": "Desk Person", "role": "Receptionist"})

    everyone = client.get("/api/staff", headers=admin_headers).json()
    assert everyone["total"] == 4

    page = client.get("/api/staff?page=1&page_size=2", headers=admin_headers).json()
    assert len(page["items"]) == 2 and page["pages"] == 2

    only_receptionists = client.get("/api/staff?role=Receptionist", headers=admin_headers).json()
    assert only_receptionists["total"] == 1

    found = client.get("/api/staff?search=desk", headers=admin_headers).json()
    assert found["total"] == 1 and found["items"][0]["full_name"] == "Desk Person"

    # SQL wildcards typed by a user are treated as plain text
    assert client.get("/api/staff?search=%25", headers=admin_headers).json()["total"] == 0


def test_get_missing_staff_returns_404(client, admin_headers):
    assert client.get("/api/staff/9999", headers=admin_headers).status_code == 404


def test_trainer_dropdown_hides_sensitive_data(client, admin_headers, make_user, login):
    client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER)
    make_user("Receptionist", "rec@gymfit.com", "RecPass123")
    headers = login("rec@gymfit.com", "RecPass123")
    response = client.get("/api/staff/trainers", headers=headers)
    assert response.status_code == 200
    trainers = response.json()
    assert len(trainers) == 1
    assert trainers[0]["full_name"] == "Ravi Kumar"
    assert "salary" not in trainers[0] and "email" not in trainers[0]


# ---------- update / deactivate ----------
def test_admin_updates_staff(client, admin_headers):
    staff_id = client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER).json()["id"]
    response = client.patch(f"/api/staff/{staff_id}", headers=admin_headers,
                            json={"salary": "35000", "specialization": "Yoga"})
    assert response.status_code == 200
    assert Decimal(response.json()["salary"]) == Decimal("35000")
    assert response.json()["specialization"] == "Yoga"
    assert response.json()["full_name"] == "Ravi Kumar"  # untouched


def test_required_field_cannot_be_nulled(client, admin_headers):
    staff_id = client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER).json()["id"]
    response = client.patch(f"/api/staff/{staff_id}", headers=admin_headers, json={"phone": None})
    assert response.status_code == 400


def test_deactivated_staff_cannot_log_in_and_old_token_stops_working(client, admin_headers, login):
    staff_id = client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER).json()["id"]
    trainer_headers = login("ravi@gymfit.com", "TrainerPass1")
    assert client.get("/api/auth/me", headers=trainer_headers).status_code == 200

    response = client.delete(f"/api/staff/{staff_id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "inactive"
    assert response.json()["is_active"] is False

    assert client.get("/api/auth/me", headers=trainer_headers).status_code == 401
    assert client.post("/api/auth/login",
                       data={"username": "ravi@gymfit.com", "password": "TrainerPass1"}).status_code == 403


def test_reactivating_restores_login(client, admin_headers):
    staff_id = client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER).json()["id"]
    client.delete(f"/api/staff/{staff_id}", headers=admin_headers)
    client.patch(f"/api/staff/{staff_id}", headers=admin_headers, json={"status": "active"})
    assert client.post("/api/auth/login",
                       data={"username": "ravi@gymfit.com", "password": "TrainerPass1"}).status_code == 200


def test_admin_cannot_lock_themselves_out(client, admin_headers, session_factory):
    # Give the admin a staff profile so it appears in the staff API.
    from app.models import StaffProfile, User
    with session_factory() as db:
        admin = db.query(User).filter_by(email=ADMIN_EMAIL).one()
        profile = StaffProfile(user_id=admin.id, phone="9999999999", status="active")
        db.add(profile)
        db.commit()
        profile_id = profile.id

    assert client.patch(f"/api/staff/{profile_id}", headers=admin_headers,
                        json={"status": "inactive"}).status_code == 400
    assert client.patch(f"/api/staff/{profile_id}", headers=admin_headers,
                        json={"role": "Trainer"}).status_code == 400


def test_admin_resets_staff_password(client, admin_headers):
    staff_id = client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER).json()["id"]
    response = client.post(f"/api/staff/{staff_id}/reset-password", headers=admin_headers,
                           json={"new_password": "ResetPass123"})
    assert response.status_code == 204
    assert client.post("/api/auth/login",
                       data={"username": "ravi@gymfit.com", "password": "ResetPass123"}).status_code == 200


# ---------- audit trail ----------
def test_staff_changes_are_audited_without_secrets(client, admin_headers, session_factory):
    staff_id = client.post("/api/staff", headers=admin_headers, json=NEW_TRAINER).json()["id"]
    client.patch(f"/api/staff/{staff_id}", headers=admin_headers, json={"salary": "40000"})
    client.post(f"/api/staff/{staff_id}/reset-password", headers=admin_headers,
                json={"new_password": "ResetPass123"})

    from app.models import AuditLog
    with session_factory() as db:
        logs = db.query(AuditLog).all()
        actions = [log.action for log in logs]
        assert "staff.create" in actions
        assert "staff.update" in actions
        assert "staff.password_reset" in actions
        dump = " ".join(str(log.old_values) + str(log.new_values) for log in logs).lower()
        assert "password" not in dump and "$2b$" not in dump
