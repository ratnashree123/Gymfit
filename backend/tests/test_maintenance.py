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


def equipment(client, headers, equipment_id):
    return client.get(f"/api/equipment/{equipment_id}", headers=headers).json()


def act(client, headers, job_id, action, body=None):
    return client.post(f"/api/maintenance/{job_id}/{action}", headers=headers, json=body or {})


# ================================================================ scheduling
def test_admin_schedules_a_job(client, admin_headers, make_equipment):
    item = make_equipment()
    response = client.post(f"/api/equipment/{item['id']}/maintenance", headers=admin_headers, json={
        "maintenance_type": "routine", "scheduled_date": iso(10), "description": "Oil the belt",
        "performed_by": "FixIt Ltd"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "scheduled" and body["maintenance_type"] == "routine"
    assert body["equipment"]["equipment_code"] == "EQ-0001" and body["is_overdue"] is False
    assert money(body["cost"]) == D("0") and body["cost_visible"] is True
    assert body["performed_by"] == "FixIt Ltd" and body["created_by_name"] == "Main Admin"
    assert body["performed_date"] is None
    assert equipment(client, admin_headers, item["id"])["open_jobs"] == 1


def test_only_admin_manages_jobs(client, reception_headers, trainer, make_equipment, make_job):
    item = make_equipment()
    job = make_job(item["id"])
    body = {"maintenance_type": "routine", "scheduled_date": iso(3)}
    for headers in (reception_headers, trainer[1]):
        assert client.post(f"/api/equipment/{item['id']}/maintenance", headers=headers, json=body).status_code == 403
        assert client.patch(f"/api/maintenance/{job['id']}", headers=headers, json={"description": "x"}).status_code == 403
        for action in ("start", "complete", "cancel"):
            assert act(client, headers, job["id"], action).status_code == 403
    assert client.post(f"/api/equipment/{item['id']}/maintenance", json=body).status_code == 401
    assert act(client, {}, job["id"], "start").status_code == 401


def test_invalid_jobs_are_rejected(client, admin_headers, make_equipment):
    item = make_equipment()
    url = f"/api/equipment/{item['id']}/maintenance"
    good = {"maintenance_type": "routine", "scheduled_date": iso(3)}
    for bad in ({"maintenance_type": "party"}, {"maintenance_type": None}, {"scheduled_date": "1999-12-31"},
                {"scheduled_date": "2101-01-01"}, {"scheduled_date": "soon"}, {"cost": "5"}, {"status": "completed"}):
        assert client.post(url, headers=admin_headers, json={**good, **bad}).status_code == 422, bad
    assert client.post(url, headers=admin_headers, json={"maintenance_type": "routine"}).status_code == 422
    assert client.post("/api/equipment/9999/maintenance", headers=admin_headers, json=good).status_code == 404


# ================================================================ life cycle
def test_start_and_complete_update_the_equipment(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    job = make_job(item["id"])

    started = act(client, admin_headers, job["id"], "start", {"performed_by": "FixIt Ltd"})
    assert started.status_code == 200 and started.json()["status"] == "in_progress"
    assert started.json()["performed_by"] == "FixIt Ltd"
    assert equipment(client, admin_headers, item["id"])["status"] == "under_maintenance"

    done = act(client, admin_headers, job["id"], "complete", {"cost": "350.50", "notes": "Belt replaced"})
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "completed" and body["performed_date"] == TODAY.isoformat()
    assert money(body["cost"]) == D("350.50") and "Result: Belt replaced" in body["description"]

    detail = equipment(client, admin_headers, item["id"])
    assert detail["status"] == "available" and detail["last_maintenance_date"] == TODAY.isoformat()
    assert detail["open_jobs"] == 0 and money(detail["maintenance_cost_total"]) == D("350.50")
    assert money(detail["repair_cost_total"]) == D("0")


def test_a_job_can_be_completed_without_starting_it(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    job = make_job(item["id"], days=-3)
    done = act(client, admin_headers, job["id"], "complete", {"performed_date": iso(-1), "cost": "100"})
    assert done.status_code == 200 and done.json()["performed_date"] == iso(-1)
    assert equipment(client, admin_headers, item["id"])["last_maintenance_date"] == iso(-1)


def test_finished_jobs_are_locked_history(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    completed, cancelled = make_job(item["id"]), make_job(item["id"], days=2)
    act(client, admin_headers, completed["id"], "complete", {"cost": "10"})
    act(client, admin_headers, cancelled["id"], "cancel")
    for job in (completed, cancelled):
        for action in ("start", "complete", "cancel"):
            response = act(client, admin_headers, job["id"], action)
            assert response.status_code == 400 and "history" in response.json()["detail"], action
        assert client.patch(f"/api/maintenance/{job['id']}", headers=admin_headers,
                            json={"description": "rewrite history"}).status_code == 400
    assert client.get(f"/api/maintenance/{completed['id']}", headers=admin_headers).json()["status"] == "completed"


def test_cannot_start_a_job_twice(client, admin_headers, make_equipment, make_job):
    job = make_job(make_equipment()["id"])
    assert act(client, admin_headers, job["id"], "start").status_code == 200
    assert act(client, admin_headers, job["id"], "start").status_code == 400


def test_unknown_job_is_404(client, admin_headers):
    for action in ("start", "complete", "cancel"):
        assert act(client, admin_headers, 9999, action).status_code == 404
    assert client.get("/api/maintenance/9999", headers=admin_headers).status_code == 404
    assert client.patch("/api/maintenance/9999", headers=admin_headers, json={"description": "x"}).status_code == 404


def test_next_maintenance_date_rules(client, admin_headers, make_equipment, make_job):
    # a due date that this job satisfies is cleared
    overdue = make_equipment(next_maintenance_date=iso(-3))
    act(client, admin_headers, make_job(overdue["id"])["id"], "complete")
    assert equipment(client, admin_headers, overdue["id"])["next_maintenance_date"] is None

    # a future date is kept
    future = make_equipment(next_maintenance_date=iso(30))
    act(client, admin_headers, make_job(future["id"])["id"], "complete")
    assert equipment(client, admin_headers, future["id"])["next_maintenance_date"] == iso(30)

    # a date typed by the admin wins; an explicit null clears it
    typed = make_equipment(next_maintenance_date=iso(30))
    act(client, admin_headers, make_job(typed["id"])["id"], "complete", {"next_maintenance_date": iso(90)})
    assert equipment(client, admin_headers, typed["id"])["next_maintenance_date"] == iso(90)
    cleared = make_equipment(next_maintenance_date=iso(30))
    act(client, admin_headers, make_job(cleared["id"])["id"], "complete", {"next_maintenance_date": None})
    assert equipment(client, admin_headers, cleared["id"])["next_maintenance_date"] is None

    # a repair never touches the routine schedule
    repaired = make_equipment(next_maintenance_date=iso(-3))
    act(client, admin_headers, make_job(repaired["id"], "repair")["id"], "complete")
    assert equipment(client, admin_headers, repaired["id"])["next_maintenance_date"] == iso(-3)


def test_completion_validation_and_condition_update(client, admin_headers, make_equipment, make_job):
    item = make_equipment(condition_status="poor")
    job = make_job(item["id"])
    for bad in ({"performed_date": iso(1)}, {"cost": "-1"}, {"cost": "abc"}, {"cost": "1.999"},
                {"condition_after": "broken"}, {"surprise": 1}, {"performed_date": "1999-01-01"}):
        assert act(client, admin_headers, job["id"], "complete", bad).status_code == 422, bad
    assert act(client, admin_headers, job["id"], "complete",
               {"performed_date": iso(0), "next_maintenance_date": iso(-1)}).status_code == 400
    assert equipment(client, admin_headers, item["id"])["open_jobs"] == 1                # nothing changed by the failures

    done = act(client, admin_headers, job["id"], "complete", {"condition_after": "good"})
    assert done.status_code == 200
    assert equipment(client, admin_headers, item["id"])["condition_status"] == "good"


def test_cancelling_a_job(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    scheduled = make_job(item["id"])
    cancelled = act(client, admin_headers, scheduled["id"], "cancel", {"reason": "Part not available"})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert "Cancelled: Part not available" in cancelled.json()["description"]
    assert equipment(client, admin_headers, item["id"])["status"] == "available"        # it never started
    assert act(client, admin_headers, make_job(item["id"])["id"], "cancel", {"reason": "no"}).status_code == 422


def test_cancelling_half_done_work_sets_the_right_status(client, admin_headers, make_equipment, make_job):
    broken = make_equipment()
    repair = make_job(broken["id"], "repair")
    act(client, admin_headers, repair["id"], "start")
    act(client, admin_headers, repair["id"], "cancel")
    assert equipment(client, admin_headers, broken["id"])["status"] == "damaged"        # a repair that never finished

    serviced = make_equipment()
    routine = make_job(serviced["id"], "routine")
    act(client, admin_headers, routine["id"], "start")
    act(client, admin_headers, routine["id"], "cancel")
    assert equipment(client, admin_headers, serviced["id"])["status"] == "available"


def test_a_routine_service_does_not_repair_a_broken_item(client, admin_headers, make_equipment, make_job):
    item = make_equipment(status="damaged")
    act(client, admin_headers, make_job(item["id"], "routine")["id"], "complete")
    assert equipment(client, admin_headers, item["id"])["status"] == "damaged"
    act(client, admin_headers, make_job(item["id"], "repair")["id"], "complete")
    assert equipment(client, admin_headers, item["id"])["status"] == "available"


def test_two_jobs_in_progress_keep_the_item_under_maintenance_until_both_finish(
        client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    first, second = make_job(item["id"]), make_job(item["id"], "inspection")
    act(client, admin_headers, first["id"], "start")
    act(client, admin_headers, second["id"], "start")
    act(client, admin_headers, first["id"], "complete")
    assert equipment(client, admin_headers, item["id"])["status"] == "under_maintenance"
    act(client, admin_headers, second["id"], "complete")
    assert equipment(client, admin_headers, item["id"])["status"] == "available"


def test_editing_a_job(client, admin_headers, make_equipment, make_job):
    job = make_job(make_equipment()["id"])
    url = f"/api/maintenance/{job['id']}"
    edited = client.patch(url, headers=admin_headers, json={
        "scheduled_date": iso(9), "description": "Full service", "performed_by": "Gym Tech", "maintenance_type": "inspection"})
    assert edited.status_code == 200
    body = edited.json()
    assert body["scheduled_date"] == iso(9) and body["description"] == "Full service"
    assert body["performed_by"] == "Gym Tech" and body["maintenance_type"] == "inspection"
    assert client.patch(url, headers=admin_headers, json={"scheduled_date": None}).status_code == 400
    assert client.patch(url, headers=admin_headers, json={"maintenance_type": None}).status_code == 400
    assert client.patch(url, headers=admin_headers, json={"cost": "5"}).status_code == 422        # cost is set on completion

    act(client, admin_headers, job["id"], "start")
    assert client.patch(url, headers=admin_headers, json={"maintenance_type": "repair"}).status_code == 400
    assert client.patch(url, headers=admin_headers, json={"scheduled_date": iso(2)}).status_code == 200


# ================================================================ history and costs
def test_history_filters_search_and_totals(client, admin_headers, make_equipment, make_job):
    bike = make_equipment(name="Spin Bike", category="Cardio")
    press = make_equipment(name="Leg Press", category="Strength")
    done_repair = make_job(bike["id"], "repair", days=-10)
    act(client, admin_headers, done_repair["id"], "complete", {"performed_date": iso(-9), "cost": "1200"})
    done_routine = make_job(press["id"], "routine", days=-5)
    act(client, admin_headers, done_routine["id"], "complete", {"performed_date": iso(-5), "cost": "300.50"})
    late = make_job(bike["id"], "inspection", days=-2)
    soon = make_job(press["id"], "routine", days=4)

    def query(text):
        return client.get(f"/api/maintenance?{text}", headers=admin_headers).json()

    assert query("")["total"] == 4
    assert [i["id"] for i in query("")["items"]] == [soon["id"], late["id"], done_routine["id"], done_repair["id"]]
    assert [i["id"] for i in query("order=asc")["items"]][0] == done_repair["id"]
    assert query(f"equipment_id={bike['id']}")["total"] == 2
    assert query("status=completed")["total"] == 2 and query("status=scheduled")["total"] == 2
    assert query("maintenance_type=repair")["total"] == 1
    assert [i["id"] for i in query("overdue=true")["items"]] == [late["id"]]
    assert query("overdue=true")["items"][0]["is_overdue"] is True
    assert query("search=spin")["total"] == 2 and query("search=EQ-0002")["total"] == 2 and query("search=%25")["total"] == 0
    assert query(f"date_from={iso(-6)}&date_to={iso(0)}")["total"] == 2
    assert money(query("")["total_cost"]) == D("1500.50")                         # completed jobs only
    assert money(query("maintenance_type=repair")["total_cost"]) == D("1200")
    page = query("page=2&page_size=3")
    assert page["pages"] == 2 and len(page["items"]) == 1

    assert client.get("/api/maintenance?status=banana", headers=admin_headers).status_code == 422
    assert client.get("/api/maintenance?maintenance_type=party", headers=admin_headers).status_code == 422
    assert client.get(f"/api/maintenance?date_from={iso(2)}&date_to={iso(1)}", headers=admin_headers).status_code == 400


def test_receptionist_sees_history_without_costs_and_trainer_not_at_all(
        client, admin_headers, reception_headers, trainer, make_equipment, make_job):
    item = make_equipment()
    job = make_job(item["id"])
    act(client, admin_headers, job["id"], "complete", {"cost": "500"})

    seen = client.get("/api/maintenance", headers=reception_headers).json()
    assert seen["total"] == 1 and seen["total_cost"] is None
    assert seen["items"][0]["cost"] is None and seen["items"][0]["cost_visible"] is False
    assert client.get(f"/api/maintenance/{job['id']}", headers=reception_headers).json()["cost"] is None

    detail = equipment(client, reception_headers, item["id"])
    assert len(detail["recent_maintenance"]) == 1 and detail["recent_maintenance"][0]["cost"] is None
    assert detail["maintenance_cost_total"] is None and detail["repair_cost_total"] is None

    assert client.get("/api/maintenance", headers=trainer[1]).status_code == 403
    assert client.get(f"/api/maintenance/{job['id']}", headers=trainer[1]).status_code == 403
    assert equipment(client, trainer[1], item["id"])["recent_maintenance"] == []
    assert client.get("/api/maintenance").status_code == 401


def test_repair_cost_is_tracked_separately_from_other_costs(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    act(client, admin_headers, make_job(item["id"], "repair")["id"], "complete", {"cost": "1200"})
    act(client, admin_headers, make_job(item["id"], "routine")["id"], "complete", {"cost": "300"})
    cancelled = make_job(item["id"], "repair")
    act(client, admin_headers, cancelled["id"], "cancel")                      # cancelled work costs nothing
    detail = equipment(client, admin_headers, item["id"])
    assert money(detail["maintenance_cost_total"]) == D("1500") and money(detail["repair_cost_total"]) == D("1200")
    assert len(detail["recent_maintenance"]) == 3


def test_maintenance_actions_are_audited(client, admin_headers, make_equipment, make_job, session_factory):
    item = make_equipment()
    job = make_job(item["id"])
    act(client, admin_headers, job["id"], "start")
    act(client, admin_headers, job["id"], "complete", {"cost": "50"})
    with session_factory() as db:
        actions = [log.action for log in db.query(AuditLog).all()]
        log = db.query(AuditLog).filter_by(action="maintenance.complete").one()
    assert {"maintenance.create", "maintenance.start", "maintenance.complete"} <= set(actions)
    assert log.old_values["equipment"]["status"] == "under_maintenance"
    assert log.new_values["equipment"]["status"] == "available"
