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


def get(client, headers, equipment_id):
    return client.get(f"/api/equipment/{equipment_id}", headers=headers)


# ================================================================ add and read
def test_admin_adds_equipment_and_gets_a_code(client, admin_headers):
    response = client.post("/api/equipment", headers=admin_headers, json={
        "name": "Treadmill Pro", "category": "Cardio", "brand_model": "NordicTrack X", "quantity": 3,
        "purchase_date": iso(-100), "purchase_price": "45000", "location": "Floor 1"})
    assert response.status_code == 201
    body = response.json()
    assert body["equipment_code"] == "EQ-0001" and body["quantity"] == 3
    assert body["condition_status"] == "good" and body["status"] == "available" and body["is_archived"] is False
    assert body["attention_level"] == "ok" and body["open_jobs"] == 0 and body["recent_maintenance"] == []
    assert money(body["purchase_price"]) == D("45000") and money(body["total_value"]) == D("135000")   # price x quantity
    assert body["financials_visible"] is True and body["created_at"].endswith("Z")


def test_codes_are_unique_and_sequential(client, make_equipment):
    assert [make_equipment()["equipment_code"] for _ in range(3)] == ["EQ-0001", "EQ-0002", "EQ-0003"]


def test_invalid_equipment_is_rejected(client, admin_headers):
    base = {"name": "Bike", "category": "Cardio"}
    for bad in (
        {"name": None}, {"category": None}, {"name": "   "}, {"category": "  "}, {"quantity": 0}, {"quantity": -2},
        {"quantity": 100001}, {"purchase_price": "-5"}, {"purchase_price": "abc"}, {"purchase_date": iso(1)},
        {"last_maintenance_date": iso(2)}, {"next_maintenance_date": "1999-01-01"}, {"condition_status": "broken"},
        {"status": "under_maintenance"}, {"location": "x" * 101}, {"is_archived": True}, {"equipment_code": "EQ-9"},
    ):
        response = client.post("/api/equipment", headers=admin_headers, json={**base, **bad})
        assert response.status_code == 422, bad
    assert client.post("/api/equipment", headers=admin_headers, json={"category": "Cardio"}).status_code == 422
    assert client.get("/api/equipment", headers=admin_headers).json()["total"] == 0


def test_blank_optional_fields_become_null(client, admin_headers):
    response = client.post("/api/equipment", headers=admin_headers, json={
        "name": "Bike", "category": "Cardio", "brand_model": "", "location": "   ", "notes": ""})
    assert response.status_code == 201
    body = response.json()
    assert body["brand_model"] is None and body["location"] is None and body["notes"] is None


def test_roles_and_financial_visibility(client, admin_headers, reception_headers, trainer, make_equipment):
    item = make_equipment(quantity=2, purchase_price="1000")
    assert client.post("/api/equipment", headers=reception_headers, json={"name": "X", "category": "Y"}).status_code == 403
    assert client.post("/api/equipment", headers=trainer[1], json={"name": "X", "category": "Y"}).status_code == 403
    assert client.post("/api/equipment", json={"name": "X", "category": "Y"}).status_code == 401
    assert client.get("/api/equipment").status_code == 401

    for headers in (reception_headers, trainer[1]):                       # everyone on staff may look
        assert client.get("/api/equipment", headers=headers).status_code == 200
        detail = get(client, headers, item["id"]).json()
        assert detail["purchase_price"] is None and detail["total_value"] is None
        assert detail["financials_visible"] is False
        assert "maintenance_cost_total" in detail and detail["maintenance_cost_total"] is None
    listed = client.get("/api/equipment", headers=reception_headers).json()["items"][0]
    assert listed["purchase_price"] is None
    assert money(client.get("/api/equipment", headers=admin_headers).json()["items"][0]["purchase_price"]) == D("1000")


def test_get_unknown_equipment(client, admin_headers):
    assert get(client, admin_headers, 9999).status_code == 404


# ================================================================ list, search, filters
def test_search_filters_sorting_and_pages(client, admin_headers, make_equipment):
    make_equipment(name="Treadmill A", category="Cardio", brand_model="Life Fitness", location="Floor 1")
    bench = make_equipment(name="Bench Press", category="Strength", location="Floor 2")
    make_equipment(name="Rowing Machine", category="cardio", location="Floor 1")
    client.patch(f"/api/equipment/{bench['id']}", headers=admin_headers, json={"condition_status": "poor"})

    def names(query):
        return [i["name"] for i in client.get(f"/api/equipment?{query}", headers=admin_headers).json()["items"]]

    assert names("search=bench") == ["Bench Press"]
    assert names("search=EQ-0001") == ["Treadmill A"]
    assert names("search=life") == ["Treadmill A"]
    assert names("search=floor 2") == ["Bench Press"]
    assert names("search=strength") == ["Bench Press"]
    assert names("search=%25") == []
    assert sorted(names("category=CARDIO")) == ["Rowing Machine", "Treadmill A"]        # not case sensitive
    assert names("condition=poor") == ["Bench Press"]
    assert names("status=damaged") == []
    assert names("sort_by=name&order=desc") == ["Treadmill A", "Rowing Machine", "Bench Press"]
    page = client.get("/api/equipment?page=2&page_size=2", headers=admin_headers).json()
    assert page["total"] == 3 and page["pages"] == 2 and len(page["items"]) == 1
    for bad in ("status=banana", "condition=banana", "attention=banana", "sort_by=banana", "page=0", "page_size=500"):
        assert client.get(f"/api/equipment?{bad}", headers=admin_headers).status_code == 422, bad


def test_categories_are_distinct_sorted_and_skip_archived(client, admin_headers, make_equipment):
    make_equipment(category="Cardio")
    make_equipment(category="cardio")
    strength = make_equipment(category="Strength")
    assert client.get("/api/equipment/categories", headers=admin_headers).json() == ["Cardio", "Strength"]
    client.post(f"/api/equipment/{strength['id']}/archive", headers=admin_headers)
    assert client.get("/api/equipment/categories", headers=admin_headers).json() == ["Cardio"]
    assert client.get("/api/equipment/categories").status_code == 401


# ================================================================ update
def test_admin_edits_equipment(client, admin_headers, make_equipment):
    item = make_equipment(location="Floor 1", quantity=1)
    response = client.patch(f"/api/equipment/{item['id']}", headers=admin_headers, json={
        "name": "Treadmill Deluxe", "quantity": 4, "condition_status": "fair", "location": None,
        "purchase_price": "999.99", "next_maintenance_date": iso(60)})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Treadmill Deluxe" and body["quantity"] == 4 and body["condition_status"] == "fair"
    assert body["location"] is None and body["next_maintenance_date"] == iso(60)
    assert money(body["total_value"]) == D("3999.96")
    assert body["category"] == "Cardio"                                                  # untouched


def test_status_can_be_set_to_damaged_and_back_but_not_to_under_maintenance(client, admin_headers, make_equipment):
    item = make_equipment()
    url = f"/api/equipment/{item['id']}"
    assert client.patch(url, headers=admin_headers, json={"status": "damaged"}).json()["status"] == "damaged"
    assert client.patch(url, headers=admin_headers, json={"status": "available"}).json()["status"] == "available"
    assert client.patch(url, headers=admin_headers, json={"status": "under_maintenance"}).status_code == 422


def test_status_is_locked_while_a_job_is_in_progress(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    job = make_job(item["id"])
    client.post(f"/api/maintenance/{job['id']}/start", headers=admin_headers, json={})
    response = client.patch(f"/api/equipment/{item['id']}", headers=admin_headers, json={"status": "available"})
    assert response.status_code == 400 and "in progress" in response.json()["detail"]
    # other fields can still be edited
    assert client.patch(f"/api/equipment/{item['id']}", headers=admin_headers, json={"location": "Floor 3"}).status_code == 200


def test_invalid_edits(client, admin_headers, reception_headers, trainer, make_equipment):
    item = make_equipment()
    url = f"/api/equipment/{item['id']}"
    assert client.patch(url, headers=admin_headers, json={"name": None}).status_code == 400
    assert client.patch(url, headers=admin_headers, json={"quantity": None}).status_code == 400
    assert client.patch(url, headers=admin_headers, json={"quantity": 0}).status_code == 422
    assert client.patch(url, headers=admin_headers, json={"equipment_code": "EQ-9999"}).status_code == 422
    assert client.patch("/api/equipment/9999", headers=admin_headers, json={"name": "X"}).status_code == 404
    assert client.patch(url, headers=reception_headers, json={"name": "X"}).status_code == 403
    assert client.patch(url, headers=trainer[1], json={"name": "X"}).status_code == 403
    assert client.patch(url, json={"name": "X"}).status_code == 401


# ================================================================ archive, never delete
def test_archive_hides_but_keeps_the_item_and_it_can_be_restored(client, admin_headers, reception_headers, make_equipment):
    item = make_equipment()
    assert client.post(f"/api/equipment/{item['id']}/archive", headers=admin_headers).json()["is_archived"] is True
    assert client.get("/api/equipment", headers=admin_headers).json()["total"] == 0
    assert client.get("/api/equipment?archived=true", headers=admin_headers).json()["total"] == 1
    assert client.get("/api/equipment?archived=true", headers=reception_headers).status_code == 403
    assert get(client, admin_headers, item["id"]).status_code == 200                    # still readable
    assert client.post(f"/api/equipment/{item['id']}/archive", headers=admin_headers).status_code == 400

    assert client.post(f"/api/equipment/{item['id']}/restore", headers=admin_headers).json()["is_archived"] is False
    assert client.post(f"/api/equipment/{item['id']}/restore", headers=admin_headers).status_code == 400
    assert client.get("/api/equipment", headers=admin_headers).json()["total"] == 1


def test_archived_items_cannot_get_new_maintenance(client, admin_headers, make_equipment):
    item = make_equipment()
    client.post(f"/api/equipment/{item['id']}/archive", headers=admin_headers)
    response = client.post(f"/api/equipment/{item['id']}/maintenance", headers=admin_headers, json={
        "maintenance_type": "routine", "scheduled_date": iso(5)})
    assert response.status_code == 400


def test_cannot_archive_while_a_job_is_in_progress(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    job = make_job(item["id"])
    client.post(f"/api/maintenance/{job['id']}/start", headers=admin_headers, json={})
    assert client.post(f"/api/equipment/{item['id']}/archive", headers=admin_headers).status_code == 400
    client.post(f"/api/maintenance/{job['id']}/complete", headers=admin_headers, json={})
    assert client.post(f"/api/equipment/{item['id']}/archive", headers=admin_headers).status_code == 200


def test_only_admin_can_archive(client, reception_headers, trainer, make_equipment):
    item = make_equipment()
    assert client.post(f"/api/equipment/{item['id']}/archive", headers=reception_headers).status_code == 403
    assert client.post(f"/api/equipment/{item['id']}/restore", headers=trainer[1]).status_code == 403
    assert client.post(f"/api/equipment/{item['id']}/archive").status_code == 401
    assert client.post("/api/equipment/9999/archive", headers=reception_headers).status_code == 403


def test_there_is_no_way_to_delete_equipment_or_history(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    job = make_job(item["id"])
    assert client.delete(f"/api/equipment/{item['id']}", headers=admin_headers).status_code == 405
    assert client.delete(f"/api/maintenance/{job['id']}", headers=admin_headers).status_code == 405


# ================================================================ damage reports
def test_any_staff_member_can_report_damage_and_a_repair_job_is_opened(
        client, admin_headers, reception_headers, trainer, make_equipment):
    for index, headers in enumerate((reception_headers, trainer[1], admin_headers)):
        item = make_equipment(name=f"Machine {index}")
        response = client.post(f"/api/equipment/{item['id']}/report-damage", headers=headers,
                               json={"description": "Belt is slipping and smells burnt"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "damaged" and body["attention_level"] == "urgent" and body["attention_code"] == "damaged"

        jobs = client.get(f"/api/maintenance?equipment_id={item['id']}", headers=admin_headers).json()["items"]
        assert len(jobs) == 1 and jobs[0]["maintenance_type"] == "repair" and jobs[0]["status"] == "scheduled"
        assert jobs[0]["description"] == "Damage reported: Belt is slipping and smells burnt"
        assert jobs[0]["scheduled_date"] == TODAY.isoformat()


def test_damage_report_rules(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    url = f"/api/equipment/{item['id']}/report-damage"
    assert client.post(url, headers=admin_headers, json={"description": "no"}).status_code == 422
    assert client.post(url, headers=admin_headers, json={}).status_code == 422
    assert client.post(url, json={"description": "Handle is broken"}).status_code == 401
    assert client.post("/api/equipment/9999/report-damage", headers=admin_headers,
                       json={"description": "Handle is broken"}).status_code == 404
    assert client.post(url, headers=admin_headers, json={"description": "Handle is broken"}).status_code == 200
    assert client.post(url, headers=admin_headers, json={"description": "Handle is broken"}).status_code == 400   # twice

    other = make_equipment()
    job = make_job(other["id"])
    client.post(f"/api/maintenance/{job['id']}/start", headers=admin_headers, json={})
    assert client.post(f"/api/equipment/{other['id']}/report-damage", headers=admin_headers,
                       json={"description": "Handle is broken"}).status_code == 400            # already being serviced

    archived = make_equipment()
    client.post(f"/api/equipment/{archived['id']}/archive", headers=admin_headers)
    assert client.post(f"/api/equipment/{archived['id']}/report-damage", headers=admin_headers,
                       json={"description": "Handle is broken"}).status_code == 400


def test_equipment_changes_are_audited(client, admin_headers, reception_headers, make_equipment, session_factory):
    item = make_equipment()
    client.patch(f"/api/equipment/{item['id']}", headers=admin_headers, json={"location": "Floor 9"})
    client.post(f"/api/equipment/{item['id']}/report-damage", headers=reception_headers,
                json={"description": "Handle is broken"})
    client.post(f"/api/equipment/{item['id']}/archive", headers=admin_headers)
    with session_factory() as db:
        actions = [log.action for log in db.query(AuditLog).all()]
        update = db.query(AuditLog).filter_by(action="equipment.update").one()
    assert {"equipment.create", "equipment.update", "equipment.report_damage", "equipment.archive"} <= set(actions)
    assert update.new_values["location"] == "Floor 9"
