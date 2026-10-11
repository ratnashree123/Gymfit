from datetime import timedelta

from app.utils.dates import gym_today
from tests.conftest import NEW_MEMBER


# ---------- create ----------
def test_register_member(client, admin_headers):
    response = client.post("/api/members", headers=admin_headers, json=NEW_MEMBER)
    assert response.status_code == 201
    body = response.json()
    assert body["member_code"] == f"GF-{body['id']:06d}"
    assert body["full_name"] == "Anita Sharma"
    assert body["status"] == "active"
    assert body["membership_status"] == "no_membership"
    assert body["registration_date"] == gym_today().isoformat()


def test_member_codes_are_unique_and_sequential(client, make_member):
    first, second = make_member(), make_member()
    assert first["member_code"] == "GF-000001"
    assert second["member_code"] == "GF-000002"


def test_receptionist_can_register_members(client, reception_headers):
    assert client.post("/api/members", headers=reception_headers, json=NEW_MEMBER).status_code == 201


def test_trainer_cannot_register_members(client, trainer):
    _, headers = trainer
    assert client.post("/api/members", headers=headers, json=NEW_MEMBER).status_code == 403


def test_members_require_login(client):
    assert client.get("/api/members").status_code == 401
    assert client.post("/api/members", json=NEW_MEMBER).status_code == 401


def test_duplicate_phone_is_blocked_in_any_format(client, admin_headers):
    assert client.post("/api/members", headers=admin_headers, json=NEW_MEMBER).status_code == 201
    again = client.post("/api/members", headers=admin_headers,
                        json={**NEW_MEMBER, "phone": "98111 22233", "full_name": "Someone Else"})
    assert again.status_code == 409
    assert "GF-" in again.json()["detail"]


def test_invalid_member_input_returns_422(client, admin_headers):
    tomorrow = (gym_today() + timedelta(days=1)).isoformat()
    cases = [
        {"phone": "abc"}, {"phone": "123"}, {"full_name": "  "}, {"email": "nope"},
        {"gender": "robot"}, {"date_of_birth": tomorrow}, {"date_of_birth": "1800-01-01"},
        {"registration_date": tomorrow}, {"emergency_contact_phone": "xx"},
        {"membership_start_date": gym_today().isoformat()},  # needs a plan_id
        {"is_admin": True},
    ]
    for bad in cases:
        response = client.post("/api/members", headers=admin_headers, json={**NEW_MEMBER, **bad})
        assert response.status_code == 422, bad


def test_blank_optional_fields_become_null(client, admin_headers):
    response = client.post("/api/members", headers=admin_headers,
                           json={**NEW_MEMBER, "email": "", "address": "   ", "emergency_contact_phone": ""})
    assert response.status_code == 201
    assert response.json()["email"] is None


def test_unknown_or_invalid_trainer_is_rejected(client, admin_headers, reception_headers):
    assert client.post("/api/members", headers=admin_headers,
                       json={**NEW_MEMBER, "assigned_trainer_id": 999}).status_code == 400
    # a receptionist's staff profile is not a trainer
    desk = client.post("/api/staff", headers=admin_headers, json={
        "full_name": "Desk Two", "email": "desk2@gymfit.com", "password": "DeskPass123",
        "role": "Receptionist", "phone": "9000000099"}).json()
    assert client.post("/api/members", headers=admin_headers,
                       json={**NEW_MEMBER, "assigned_trainer_id": desk["id"]}).status_code == 400


# ---------- read / search / pagination ----------
def test_get_member_and_404(client, admin_headers, make_member):
    member = make_member()
    assert client.get(f"/api/members/{member['id']}", headers=admin_headers).status_code == 200
    assert client.get("/api/members/9999", headers=admin_headers).status_code == 404


def test_search_by_name_phone_and_code(client, admin_headers, make_member):
    a = make_member(full_name="Ravi Patel", phone="9111111111")
    make_member(full_name="Meena Iyer", phone="9222222222")

    def names(query):
        return [m["full_name"] for m in client.get(f"/api/members?search={query}", headers=admin_headers).json()["items"]]

    assert names("ravi") == ["Ravi Patel"]
    assert names("9222") == ["Meena Iyer"]
    assert names(a["member_code"]) == ["Ravi Patel"]
    assert names("zzz") == []
    assert client.get("/api/members?search=%25", headers=admin_headers).json()["total"] == 0  # '%' is plain text


def test_pagination_and_sorting(client, admin_headers, make_member):
    for name in ("Cara", "Anil", "Bela"):
        make_member(full_name=name)
    page1 = client.get("/api/members?page=1&page_size=2", headers=admin_headers).json()
    assert [m["full_name"] for m in page1["items"]] == ["Anil", "Bela"]
    assert page1["total"] == 3 and page1["pages"] == 2
    page2 = client.get("/api/members?page=2&page_size=2", headers=admin_headers).json()
    assert [m["full_name"] for m in page2["items"]] == ["Cara"]
    desc = client.get("/api/members?order=desc", headers=admin_headers).json()
    assert [m["full_name"] for m in desc["items"]] == ["Cara", "Bela", "Anil"]
    assert client.get("/api/members?page=0", headers=admin_headers).status_code == 422
    assert client.get("/api/members?page_size=1000", headers=admin_headers).status_code == 422


# ---------- update ----------
def test_update_member(client, admin_headers, make_member):
    member = make_member()
    response = client.patch(f"/api/members/{member['id']}", headers=admin_headers,
                            json={"address": "12 MG Road", "email": "NEW@Example.com"})
    assert response.status_code == 200
    assert response.json()["address"] == "12 MG Road"
    assert response.json()["email"] == "new@example.com"
    assert response.json()["full_name"] == member["full_name"]  # untouched


def test_update_cannot_null_required_fields_or_steal_a_phone(client, admin_headers, make_member):
    first, second = make_member(), make_member()
    assert client.patch(f"/api/members/{first['id']}", headers=admin_headers, json={"phone": None}).status_code == 400
    assert client.patch(f"/api/members/{first['id']}", headers=admin_headers,
                        json={"phone": second["phone"]}).status_code == 409
    # keeping your own phone number is fine
    assert client.patch(f"/api/members/{first['id']}", headers=admin_headers,
                        json={"phone": first["phone"]}).status_code == 200


def test_deactivate_and_reactivate_member(client, admin_headers, make_member):
    member = make_member()
    response = client.patch(f"/api/members/{member['id']}", headers=admin_headers, json={"status": "inactive"})
    assert response.json()["status"] == "inactive"
    assert response.json()["membership_status"] == "inactive"
    assert client.get("/api/members?status=inactive", headers=admin_headers).json()["total"] == 1
    client.patch(f"/api/members/{member['id']}", headers=admin_headers, json={"status": "active"})
    assert client.get("/api/members?status=inactive", headers=admin_headers).json()["total"] == 0


# ---------- delete / restore ----------
def test_soft_delete_hides_member_and_admin_can_restore(client, admin_headers, make_member):
    member = make_member()
    assert client.delete(f"/api/members/{member['id']}", headers=admin_headers).status_code == 200
    assert client.get(f"/api/members/{member['id']}", headers=admin_headers).status_code == 404
    assert client.get("/api/members", headers=admin_headers).json()["total"] == 0
    deleted = client.get("/api/members?deleted=true", headers=admin_headers).json()
    assert deleted["total"] == 1

    restored = client.post(f"/api/members/{member['id']}/restore", headers=admin_headers)
    assert restored.status_code == 200 and restored.json()["is_deleted"] is False
    assert client.post(f"/api/members/{member['id']}/restore", headers=admin_headers).status_code == 400
    assert client.get("/api/members", headers=admin_headers).json()["total"] == 1


def test_deleted_members_phone_stays_reserved(client, admin_headers, make_member):
    member = make_member()
    client.delete(f"/api/members/{member['id']}", headers=admin_headers)
    again = client.post("/api/members", headers=admin_headers,
                        json={**NEW_MEMBER, "phone": member["phone"]})
    assert again.status_code == 409
    assert "restore" in again.json()["detail"].lower()


def test_only_admin_can_delete_restore_or_view_deleted(client, admin_headers, reception_headers, make_member):
    member = make_member()
    assert client.delete(f"/api/members/{member['id']}", headers=reception_headers).status_code == 403
    client.delete(f"/api/members/{member['id']}", headers=admin_headers)
    assert client.post(f"/api/members/{member['id']}/restore", headers=reception_headers).status_code == 403
    assert client.get("/api/members?deleted=true", headers=reception_headers).status_code == 403


# ---------- role-based visibility ----------
def test_medical_notes_visibility_by_role(client, admin_headers, reception_headers, trainer, make_member):
    trainer_id, trainer_headers = trainer
    member = make_member(medical_notes="Knee surgery 2024", assigned_trainer_id=trainer_id)
    url = f"/api/members/{member['id']}"

    as_admin = client.get(url, headers=admin_headers).json()
    assert as_admin["medical_notes"] == "Knee surgery 2024" and as_admin["medical_notes_visible"] is True

    as_trainer = client.get(url, headers=trainer_headers).json()
    assert as_trainer["medical_notes"] == "Knee surgery 2024"

    as_desk = client.get(url, headers=reception_headers).json()
    assert as_desk["medical_notes"] is None and as_desk["medical_notes_visible"] is False
    assert "Knee" not in client.get(url, headers=reception_headers).text


def test_receptionist_can_record_notes_at_registration_but_not_change_them_later(
        client, admin_headers, reception_headers):
    created = client.post("/api/members", headers=reception_headers,
                          json={**NEW_MEMBER, "medical_notes": "Asthma"})
    assert created.status_code == 201
    member_id = created.json()["id"]
    assert client.get(f"/api/members/{member_id}", headers=admin_headers).json()["medical_notes"] == "Asthma"
    assert client.patch(f"/api/members/{member_id}", headers=reception_headers,
                        json={"medical_notes": "overwritten"}).status_code == 403
    assert client.patch(f"/api/members/{member_id}", headers=admin_headers,
                        json={"medical_notes": "Asthma, inhaler"}).status_code == 200


def test_trainer_sees_only_assigned_members(client, trainer, make_member):
    trainer_id, trainer_headers = trainer
    mine = make_member(assigned_trainer_id=trainer_id)
    other = make_member()

    listing = client.get("/api/members", headers=trainer_headers).json()
    assert [m["id"] for m in listing["items"]] == [mine["id"]]
    assert client.get(f"/api/members/{mine['id']}", headers=trainer_headers).status_code == 200
    # 404, not 403: the trainer is not told that this member exists
    assert client.get(f"/api/members/{other['id']}", headers=trainer_headers).status_code == 404
    # asking for another trainer's list does not widen access: still only their own members
    forced = client.get("/api/members?trainer_id=999", headers=trainer_headers).json()
    assert [m["id"] for m in forced["items"]] == [mine["id"]]
    assert client.patch(f"/api/members/{mine['id']}", headers=trainer_headers,
                        json={"address": "x"}).status_code == 403
    assert client.get(f"/api/members/{mine['id']}/memberships", headers=trainer_headers).status_code == 403


def test_filter_by_trainer(client, admin_headers, trainer, make_member):
    trainer_id, _ = trainer
    make_member(assigned_trainer_id=trainer_id)
    make_member()
    assert client.get(f"/api/members?trainer_id={trainer_id}", headers=admin_headers).json()["total"] == 1
    listing = client.get("/api/members", headers=admin_headers).json()["items"]
    assigned = [m for m in listing if m["assigned_trainer"]]
    assert assigned[0]["assigned_trainer"]["full_name"] == "Ravi Kumar"


def test_member_changes_are_audited_without_medical_notes(client, admin_headers, make_member, session_factory):
    member = make_member(medical_notes="Secret condition")
    client.patch(f"/api/members/{member['id']}", headers=admin_headers, json={"medical_notes": "Other secret"})
    from app.models import AuditLog
    with session_factory() as db:
        logs = [log for log in db.query(AuditLog).all() if log.entity_type == "member"]
        assert {"member.create", "member.update"} <= {log.action for log in logs}
        dump = " ".join(str(log.old_values) + str(log.new_values) for log in logs)
        assert "secret" not in dump.lower()
