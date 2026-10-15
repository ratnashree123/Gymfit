from datetime import timedelta
from decimal import Decimal

from app.models import AuditLog
from app.utils.dates import gym_today

TODAY = gym_today()
D = Decimal


def iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


def money(value):
    return D(str(value))


def record(client, headers, member_id, **fields):
    return client.post("/api/progress", headers=headers, json={"member_id": member_id, **fields})


def made(client, headers, member_id, **fields):
    response = record(client, headers, member_id, **fields)
    assert response.status_code == 201, response.text
    return response.json()


# ================================================================ recording
def test_trainer_records_measurements_for_an_assigned_member(client, trainer, make_member):
    member = make_member(assigned_trainer_id=trainer[0])
    response = record(client, trainer[1], member["id"], weight_kg="82.5", height_cm="178", body_fat_pct="21.5",
                      chest_cm="101", waist_cm="88.5", hips_cm="99", goal="Lose 5 kg", notes="First weigh-in")
    assert response.status_code == 201
    body = response.json()
    assert body["recorded_on"] == TODAY.isoformat() and body["member"]["id"] == member["id"]
    assert money(body["weight_kg"]) == D("82.5") and money(body["height_cm"]) == D("178")
    assert money(body["body_fat_pct"]) == D("21.5") and money(body["waist_cm"]) == D("88.5")
    assert body["goal"] == "Lose 5 kg" and body["notes"] == "First weigh-in"
    assert body["recorded_by_name"] == "Ravi Kumar" and body["created_at"].endswith("Z")


def test_every_measurement_is_optional_but_a_record_cannot_be_empty(client, admin_headers, make_member):
    member = make_member()
    assert made(client, admin_headers, member["id"], recorded_on=iso(-3), weight_kg="80")["height_cm"] is None
    assert made(client, admin_headers, member["id"], recorded_on=iso(-2), goal="Run 5 km")["weight_kg"] is None
    assert made(client, admin_headers, member["id"], recorded_on=iso(-1), notes="Felt strong")["goal"] is None
    assert record(client, admin_headers, member["id"]).status_code == 422
    assert record(client, admin_headers, member["id"], goal="", notes="  ").status_code == 422


def test_unrealistic_or_malformed_values_are_rejected(client, admin_headers, make_member):
    member = make_member()
    for bad in (
        {"weight_kg": "10"}, {"weight_kg": "500"}, {"weight_kg": "82.555"}, {"weight_kg": "abc"},
        {"height_cm": "40"}, {"height_cm": "300"}, {"body_fat_pct": "1"}, {"body_fat_pct": "80"},
        {"chest_cm": "10"}, {"waist_cm": "300"}, {"hips_cm": "-5"}, {"recorded_on": iso(1)},
        {"recorded_on": "1999-01-01"}, {"recorded_by": 1}, {"bmi": "22"},
    ):
        assert record(client, admin_headers, member["id"], **{"weight_kg": "80", **bad}).status_code == 422, bad
    assert client.get(f"/api/progress?member_id={member['id']}", headers=admin_headers).json()["total"] == 0


def test_one_record_per_member_per_day(client, admin_headers, make_member):
    member = make_member()
    made(client, admin_headers, member["id"], weight_kg="80")
    again = record(client, admin_headers, member["id"], weight_kg="79")
    assert again.status_code == 409 and "already a record" in again.json()["detail"]
    assert record(client, admin_headers, member["id"], weight_kg="79", recorded_on=iso(-1)).status_code == 201
    assert record(client, admin_headers, make_member()["id"], weight_kg="79").status_code == 201    # another member: fine


def test_editing_a_record(client, admin_headers, make_member):
    member = make_member()
    first = made(client, admin_headers, member["id"], weight_kg="80", waist_cm="90", recorded_on=iso(-5))
    second = made(client, admin_headers, member["id"], weight_kg="79", recorded_on=iso(-3))
    url = f"/api/progress/{first['id']}"

    edited = client.patch(url, headers=admin_headers, json={"weight_kg": "79.5", "notes": "Re-weighed"})
    assert edited.status_code == 200 and money(edited.json()["weight_kg"]) == D("79.5")
    assert edited.json()["waist_cm"] is not None and edited.json()["notes"] == "Re-weighed"      # untouched
    assert client.patch(url, headers=admin_headers, json={"waist_cm": None}).json()["waist_cm"] is None
    assert client.patch(url, headers=admin_headers, json={"recorded_on": iso(-4)}).json()["recorded_on"] == iso(-4)

    assert client.patch(url, headers=admin_headers, json={"recorded_on": second["recorded_on"]}).status_code == 409
    assert client.patch(url, headers=admin_headers, json={"recorded_on": None}).status_code == 400
    assert client.patch(url, headers=admin_headers, json={}).status_code == 422
    assert client.patch(url, headers=admin_headers, json={"weight_kg": "5"}).status_code == 422
    assert client.patch(url, headers=admin_headers, json={"member_id": 5}).status_code == 422
    assert client.patch("/api/progress/9999", headers=admin_headers, json={"notes": "x"}).status_code == 404


def test_a_record_cannot_be_edited_into_an_empty_one(client, admin_headers, make_member):
    rec = made(client, admin_headers, make_member()["id"], weight_kg="80")
    url = f"/api/progress/{rec['id']}"
    response = client.patch(url, headers=admin_headers, json={"weight_kg": None})
    assert response.status_code == 400 and "Delete it instead" in response.json()["detail"]
    assert money(client.get(url, headers=admin_headers).json()["weight_kg"]) == D("80")          # unchanged


# ================================================================ reading
def test_list_filters_order_and_pages(client, admin_headers, make_member):
    member = make_member()
    for days, weight in ((-30, "80"), (-20, "78"), (-10, "76"), (-1, "75")):
        made(client, admin_headers, member["id"], weight_kg=weight, recorded_on=iso(days))

    def dates(query=""):
        return [r["recorded_on"] for r in client.get(f"/api/progress?member_id={member['id']}&{query}",
                                                      headers=admin_headers).json()["items"]]

    assert dates() == [iso(-1), iso(-10), iso(-20), iso(-30)]                            # newest first
    assert dates("order=asc") == [iso(-30), iso(-20), iso(-10), iso(-1)]
    assert dates(f"date_from={iso(-20)}&date_to={iso(-10)}") == [iso(-10), iso(-20)]
    page = client.get(f"/api/progress?member_id={member['id']}&page=2&page_size=3", headers=admin_headers).json()
    assert page["total"] == 4 and page["pages"] == 2 and len(page["items"]) == 1
    assert client.get(f"/api/progress?member_id={member['id']}&date_from={iso(0)}&date_to={iso(-5)}",
                      headers=admin_headers).status_code == 400
    assert client.get("/api/progress", headers=admin_headers).status_code == 422             # member_id is required
    assert client.get("/api/progress?member_id=9999", headers=admin_headers).status_code == 404


def test_get_one_record(client, admin_headers, make_member):
    rec = made(client, admin_headers, make_member()["id"], weight_kg="80")
    assert client.get(f"/api/progress/{rec['id']}", headers=admin_headers).json()["id"] == rec["id"]
    assert client.get("/api/progress/9999", headers=admin_headers).status_code == 404


def test_the_series_is_chart_ready_with_bmi(client, admin_headers, make_member):
    member = make_member()
    # saved out of order on purpose
    made(client, admin_headers, member["id"], recorded_on=iso(-10), weight_kg="76", body_fat_pct="20")
    made(client, admin_headers, member["id"], recorded_on=iso(-30), weight_kg="80", height_cm="180", waist_cm="90")
    made(client, admin_headers, member["id"], recorded_on=iso(-20), weight_kg="78")

    series = client.get(f"/api/progress/members/{member['id']}/series", headers=admin_headers).json()
    assert series["member"]["id"] == member["id"]
    points = series["points"]
    assert [p["recorded_on"] for p in points] == [iso(-30), iso(-20), iso(-10)]            # oldest first
    assert [money(p["bmi"]) for p in points] == [D("24.7"), D("24.1"), D("23.5")]          # height remembered from the 1st
    assert points[2]["body_fat_pct"] is not None and points[0]["body_fat_pct"] is None

    changes = {c["metric"]: c for c in series["changes"]}
    assert money(changes["weight_kg"]["first_value"]) == D("80") and money(changes["weight_kg"]["latest_value"]) == D("76")
    assert money(changes["weight_kg"]["change"]) == D("-4") and changes["weight_kg"]["measurements"] == 3
    assert changes["weight_kg"]["first_date"] == iso(-30) and changes["weight_kg"]["latest_date"] == iso(-10)
    assert changes["body_fat_pct"]["change"] is None and changes["body_fat_pct"]["measurements"] == 1   # measured once
    assert "hips_cm" not in changes                                                       # never measured

    window = client.get(f"/api/progress/members/{member['id']}/series?date_from={iso(-20)}", headers=admin_headers).json()
    assert [p["recorded_on"] for p in window["points"]] == [iso(-20), iso(-10)]
    assert [money(p["bmi"]) for p in window["points"]] == [D("24.1"), D("23.5")]          # height 180 was measured earlier
    window_changes = {c["metric"]: c for c in window["changes"]}
    assert money(window_changes["weight_kg"]["change"]) == D("-2") and "waist_cm" not in window_changes   # window only
    assert client.get(f"/api/progress/members/{member['id']}/series?date_from={iso(0)}&date_to={iso(-5)}",
                      headers=admin_headers).status_code == 400


def test_the_summary(client, admin_headers, make_member):
    member = make_member()
    empty = client.get(f"/api/progress/members/{member['id']}/summary", headers=admin_headers).json()
    assert empty["records"] == 0 and empty["latest"] is None and empty["first"] is None
    assert empty["bmi"] is None and empty["changes"] == [] and empty["current_goal"] is None
    assert empty["active_plan"] is None

    client.post("/api/workouts/plans", headers=admin_headers, json={
        "member_id": member["id"], "title": "Strength", "goal": "Build muscle"})
    with_plan = client.get(f"/api/progress/members/{member['id']}/summary", headers=admin_headers).json()
    assert with_plan["current_goal"] == "Build muscle" and with_plan["active_plan"]["title"] == "Strength"

    made(client, admin_headers, member["id"], recorded_on=iso(-30), weight_kg="80", height_cm="180")
    made(client, admin_headers, member["id"], recorded_on=iso(-10), weight_kg="76", goal="Lose 5 kg")
    summary = client.get(f"/api/progress/members/{member['id']}/summary", headers=admin_headers).json()
    assert summary["records"] == 2 and summary["current_goal"] == "Lose 5 kg"             # the latest written goal wins
    assert summary["first"]["recorded_on"] == iso(-30) and summary["latest"]["recorded_on"] == iso(-10)
    assert money(summary["bmi"]) == D("23.5") and summary["bmi_category"] == "Healthy range"
    assert money({c["metric"]: c for c in summary["changes"]}["weight_kg"]["change"]) == D("-4")
    assert summary["active_plan"]["id"] == with_plan["active_plan"]["id"]


# ================================================================ privacy and access
def test_receptionists_have_no_access_to_body_data(client, admin_headers, reception_headers, make_member):
    member = make_member()
    rec = made(client, admin_headers, member["id"], weight_kg="80")
    base = f"/api/progress/members/{member['id']}"
    assert record(client, reception_headers, member["id"], weight_kg="80").status_code == 403
    assert client.get(f"/api/progress?member_id={member['id']}", headers=reception_headers).status_code == 403
    assert client.get(f"/api/progress/{rec['id']}", headers=reception_headers).status_code == 403
    assert client.patch(f"/api/progress/{rec['id']}", headers=reception_headers, json={"notes": "x"}).status_code == 403
    assert client.delete(f"/api/progress/{rec['id']}", headers=reception_headers).status_code == 403
    assert client.get(f"{base}/series", headers=reception_headers).status_code == 403
    assert client.get(f"{base}/summary", headers=reception_headers).status_code == 403


def test_nobody_logged_in_gets_nothing(client, make_member):
    member = make_member()
    assert client.post("/api/progress", json={"member_id": member["id"], "weight_kg": "80"}).status_code == 401
    assert client.get(f"/api/progress?member_id={member['id']}").status_code == 401
    assert client.get(f"/api/progress/members/{member['id']}/summary").status_code == 401


def test_a_trainer_sees_only_the_measurements_of_their_own_members(
        client, admin_headers, trainer, second_trainer, make_member):
    mine = make_member(assigned_trainer_id=trainer[0])
    theirs = make_member(assigned_trainer_id=second_trainer[0])
    own = made(client, trainer[1], mine["id"], weight_kg="80")
    foreign = made(client, admin_headers, theirs["id"], weight_kg="90")

    assert record(client, trainer[1], theirs["id"], weight_kg="90", recorded_on=iso(-1)).status_code == 404
    assert client.get(f"/api/progress?member_id={theirs['id']}", headers=trainer[1]).status_code == 404
    assert client.get(f"/api/progress/{foreign['id']}", headers=trainer[1]).status_code == 404
    assert client.patch(f"/api/progress/{foreign['id']}", headers=trainer[1], json={"notes": "x"}).status_code == 404
    assert client.delete(f"/api/progress/{foreign['id']}", headers=trainer[1]).status_code == 404
    assert client.get(f"/api/progress/members/{theirs['id']}/series", headers=trainer[1]).status_code == 404
    assert client.get(f"/api/progress/members/{theirs['id']}/summary", headers=trainer[1]).status_code == 404
    assert client.get(f"/api/progress/{own['id']}", headers=trainer[1]).status_code == 200
    assert client.get(f"/api/progress/members/{mine['id']}/summary", headers=trainer[1]).status_code == 200


def test_deleted_members_data_is_hidden(client, admin_headers, make_member):
    member = make_member()
    rec = made(client, admin_headers, member["id"], weight_kg="80")
    client.delete(f"/api/members/{member['id']}", headers=admin_headers)
    assert client.get(f"/api/progress/{rec['id']}", headers=admin_headers).status_code == 404
    assert client.get(f"/api/progress?member_id={member['id']}", headers=admin_headers).status_code == 404
    assert record(client, admin_headers, member["id"], weight_kg="79", recorded_on=iso(-1)).status_code == 404


# ================================================================ erasing and the audit trail
def test_a_record_can_be_deleted_by_admin_or_the_members_trainer(client, admin_headers, trainer, make_member):
    member = make_member(assigned_trainer_id=trainer[0])
    first = made(client, admin_headers, member["id"], weight_kg="80", recorded_on=iso(-2))
    second = made(client, trainer[1], member["id"], weight_kg="79", recorded_on=iso(-1))
    assert client.delete(f"/api/progress/{first['id']}", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/progress/{second['id']}", headers=trainer[1]).status_code == 200
    assert client.get(f"/api/progress?member_id={member['id']}", headers=admin_headers).json()["total"] == 0
    assert client.delete(f"/api/progress/{first['id']}", headers=admin_headers).status_code == 404


def test_the_audit_log_never_contains_the_measurements(client, admin_headers, make_member, session_factory):
    member = make_member()
    rec = made(client, admin_headers, member["id"], weight_kg="82.55", waist_cm="88.5", goal="Secret goal 999",
               notes="Private note 777")
    client.patch(f"/api/progress/{rec['id']}", headers=admin_headers, json={"weight_kg": "81.45", "hips_cm": "97.5"})
    client.delete(f"/api/progress/{rec['id']}", headers=admin_headers)

    with session_factory() as db:
        logs = db.query(AuditLog).filter(AuditLog.entity_type == "member_progress").all()
        by_action = {log.action: log for log in logs}
        everything = " ".join(str(log.old_values) + str(log.new_values) for log in logs)
    assert set(by_action) == {"progress.create", "progress.update", "progress.delete"}
    for secret in ("82.55", "81.45", "88.5", "97.5", "Secret goal", "Private note"):
        assert secret not in everything, secret
    assert by_action["progress.create"].new_values["fields"] == ["weight_kg", "waist_cm", "goal", "notes"]
    assert by_action["progress.update"].new_values["changed"] == ["hips_cm", "weight_kg"]
