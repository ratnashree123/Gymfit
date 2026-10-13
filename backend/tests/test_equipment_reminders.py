from datetime import timedelta

from app.utils.dates import gym_today

TODAY = gym_today()


def iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


def reminders(client, headers, query=""):
    response = client.get(f"/api/maintenance/reminders{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def ids(items):
    return {entry["equipment"]["id"] for entry in items}


def listed(client, headers, query):
    return client.get(f"/api/equipment?page_size=100&{query}", headers=headers).json()["items"]


def test_an_overdue_job_is_urgent(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    make_job(item["id"], days=-5)
    urgent = reminders(client, admin_headers)["urgent"]
    assert len(urgent) == 1 and urgent[0]["equipment"]["id"] == item["id"]
    assert (urgent[0]["level"], urgent[0]["code"]) == ("urgent", "overdue")
    assert urgent[0]["message"] == "Maintenance overdue by 5 days" and urgent[0]["due_date"] == iso(-5)
    assert listed(client, admin_headers, "")[0]["attention_level"] == "urgent"
    assert [i["id"] for i in listed(client, admin_headers, "attention=urgent")] == [item["id"]]


def test_the_warning_window_and_how_to_change_it(client, admin_headers, make_equipment, make_job, set_setting):
    today_item, near, far = make_equipment(), make_equipment(), make_equipment()
    make_job(today_item["id"], days=0)
    make_job(near["id"], days=3)
    make_job(far["id"], days=10)

    default = reminders(client, admin_headers)
    assert default["alert_days"] == 7 and ids(default["soon"]) == {today_item["id"], near["id"]}
    messages = {e["equipment"]["id"]: e["message"] for e in default["soon"]}
    assert messages[today_item["id"]] == "Maintenance due today" and messages[near["id"]] == "Maintenance due in 3 days"

    assert ids(reminders(client, admin_headers, "?days=14")["soon"]) == {today_item["id"], near["id"], far["id"]}
    assert ids(reminders(client, admin_headers, "?days=0")["soon"]) == {today_item["id"]}
    set_setting("maintenance_alert_days", "14")
    assert reminders(client, admin_headers)["alert_days"] == 14
    assert ids(reminders(client, admin_headers)["soon"]) == {today_item["id"], near["id"], far["id"]}


def test_the_equipments_own_next_date_counts_too(client, admin_headers, make_equipment):
    late = make_equipment(next_maintenance_date=iso(-2))
    near = make_equipment(next_maintenance_date=iso(5))
    far = make_equipment(next_maintenance_date=iso(60))
    result = reminders(client, admin_headers)
    assert ids(result["urgent"]) == {late["id"]} and ids(result["soon"]) == {near["id"]}
    assert far["id"] not in ids(result["urgent"]) | ids(result["soon"])


def test_poor_condition_is_flagged_and_damaged_items_come_first(client, admin_headers, make_equipment, make_job):
    late = make_equipment(name="Late one")
    make_job(late["id"], days=-3)
    broken = make_equipment(name="Broken one", status="damaged")
    poor = make_equipment(name="Worn out", condition_status="poor")
    result = reminders(client, admin_headers)
    assert [e["equipment"]["id"] for e in result["urgent"]] == [broken["id"], late["id"]]     # damaged first
    assert result["urgent"][0]["code"] == "damaged"
    assert [(e["equipment"]["id"], e["code"]) for e in result["soon"]] == [(poor["id"], "poor_condition")]


def test_items_being_serviced_and_archived_items_are_not_listed(client, admin_headers, make_equipment, make_job):
    serviced = make_equipment()
    job = make_job(serviced["id"], days=-5)
    client.post(f"/api/maintenance/{job['id']}/start", headers=admin_headers, json={})
    archived = make_equipment()
    make_job(archived["id"], days=-5)
    client.post(f"/api/equipment/{archived['id']}/archive", headers=admin_headers)
    result = reminders(client, admin_headers)
    assert result["urgent_count"] == 0 and result["soon_count"] == 0
    item = [i for i in listed(client, admin_headers, "") if i["id"] == serviced["id"]][0]
    assert item["attention_level"] == "ok" and item["attention_code"] == "under_maintenance"


def test_completing_the_job_clears_the_reminder(client, admin_headers, make_equipment, make_job):
    item = make_equipment(next_maintenance_date=iso(-1))
    job = make_job(item["id"], days=-5)
    assert reminders(client, admin_headers)["urgent_count"] == 1
    client.post(f"/api/maintenance/{job['id']}/complete", headers=admin_headers, json={})
    assert reminders(client, admin_headers)["urgent_count"] == 0


def test_the_list_filter_and_the_reminders_always_agree(client, admin_headers, make_equipment, make_job):
    ok = make_equipment(name="ok")
    damaged = make_equipment(name="damaged", status="damaged")
    overdue_job = make_equipment(name="overdue job")
    make_job(overdue_job["id"], days=-4)
    overdue_date = make_equipment(name="overdue date", next_maintenance_date=iso(-1))
    soon_job = make_equipment(name="soon job")
    make_job(soon_job["id"], days=2)
    soon_date = make_equipment(name="soon date", next_maintenance_date=iso(7))
    poor = make_equipment(name="poor", condition_status="poor")
    broken_and_poor = make_equipment(name="broken and poor", status="damaged", condition_status="poor")
    poor_and_overdue = make_equipment(name="poor and overdue", condition_status="poor")
    make_job(poor_and_overdue["id"], days=-1)
    in_service = make_equipment(name="in service")
    started = make_job(in_service["id"], days=-9)
    client.post(f"/api/maintenance/{started['id']}/start", headers=admin_headers, json={})
    archived = make_equipment(name="archived")
    make_job(archived["id"], days=-9)
    client.post(f"/api/equipment/{archived['id']}/archive", headers=admin_headers)

    expected_urgent = {damaged["id"], overdue_job["id"], overdue_date["id"], broken_and_poor["id"], poor_and_overdue["id"]}
    expected_soon = {soon_job["id"], soon_date["id"], poor["id"]}

    result = reminders(client, admin_headers)
    assert ids(result["urgent"]) == expected_urgent and result["urgent_count"] == 5
    assert ids(result["soon"]) == expected_soon and result["soon_count"] == 3
    assert {i["id"] for i in listed(client, admin_headers, "attention=urgent")} == expected_urgent
    assert {i["id"] for i in listed(client, admin_headers, "attention=soon")} == expected_soon

    levels = {i["id"]: i["attention_level"] for i in listed(client, admin_headers, "")}
    assert levels[ok["id"]] == "ok" and levels[in_service["id"]] == "ok" and archived["id"] not in levels
    assert {i for i, level in levels.items() if level == "urgent"} == expected_urgent
    assert {i for i, level in levels.items() if level == "soon"} == expected_soon


def test_who_can_see_reminders(client, reception_headers, trainer, admin_headers):
    assert reminders(client, reception_headers)["urgent_count"] == 0
    assert reminders(client, admin_headers)["alert_days"] == 7
    assert client.get("/api/maintenance/reminders", headers=trainer[1]).status_code == 403
    assert client.get("/api/maintenance/reminders").status_code == 401
    assert client.get("/api/maintenance/reminders?days=-1", headers=admin_headers).status_code == 422
    assert client.get("/api/maintenance/reminders?days=366", headers=admin_headers).status_code == 422
