from datetime import timedelta

from app.models import AuditLog
from app.utils.dates import gym_today

TODAY = gym_today()


def iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


def exercise(day=1, group="Chest", name="Bench press", **extra):
    return {"day_number": day, "muscle_group": group, "exercise_name": name, "sets": 3, "reps": 10, **extra}


def create(client, headers, member_id, **extra):
    body = {"member_id": member_id, "title": "Beginner strength", "goal": "Build muscle", **extra}
    return client.post("/api/workouts/plans", headers=headers, json=body)


def plan_of(client, headers, member_id, **extra):
    response = create(client, headers, member_id, **extra)
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, headers, plan_id, **body):
    return client.patch(f"/api/workouts/plans/{plan_id}", headers=headers, json=body)


# ================================================================ creating plans
def test_admin_creates_a_plan_with_exercises_grouped_by_day(client, admin_headers, make_member):
    member = make_member()
    response = create(client, admin_headers, member["id"], exercises=[
        exercise(1, "chest", "Bench press"), exercise(1, "Triceps", "Dips", sets=4, reps=12, rest_seconds=60),
        exercise(2, "back", "Rows", sets=4, reps=8),
        exercise(3, "cardio", "Treadmill", sets=None, reps=None, duration_minutes=20)])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active" and body["start_date"] == TODAY.isoformat() and body["end_date"] is None
    assert body["exercise_count"] == 4 and body["training_days"] == 3
    assert body["member"]["id"] == member["id"] and body["trainer_id"] is None and body["trainer_name"] is None
    day1, day2, day3 = body["days"]
    assert day1["day_number"] == 1 and day1["muscle_groups"] == ["Chest", "Triceps"]          # tidied: chest -> Chest
    assert [(e["exercise_name"], e["sort_order"]) for e in day1["exercises"]] == [("Bench press", 1), ("Dips", 2)]
    assert day1["exercises"][1]["rest_seconds"] == 60
    assert day2["muscle_groups"] == ["Back"] and day2["exercises"][0]["sort_order"] == 1
    assert day3["exercises"][0]["duration_minutes"] == 20 and day3["exercises"][0]["sets"] is None


def test_a_plan_can_start_empty_and_have_dates(client, admin_headers, make_member):
    body = plan_of(client, admin_headers, make_member()["id"], start_date=iso(2), end_date=iso(60), notes="Go slowly")
    assert body["days"] == [] and body["exercise_count"] == 0 and body["training_days"] == 0
    assert body["start_date"] == iso(2) and body["end_date"] == iso(60) and body["notes"] == "Go slowly"


def test_the_plan_author_is_the_trainer_or_the_members_trainer(
        client, admin_headers, trainer, second_trainer, make_member):
    trainer_id, trainer_headers = trainer
    mine = make_member(assigned_trainer_id=trainer_id)

    by_trainer = plan_of(client, trainer_headers, mine["id"])
    assert by_trainer["trainer_id"] == trainer_id and by_trainer["trainer_name"] == "Ravi Kumar"

    other = make_member(assigned_trainer_id=trainer_id)
    by_admin = plan_of(client, admin_headers, other["id"])
    assert by_admin["trainer_id"] == trainer_id                                    # defaults to the assigned trainer

    third = make_member()
    chosen = plan_of(client, admin_headers, third["id"], trainer_id=second_trainer[0])
    assert chosen["trainer_name"] == "Meera Nair"


def test_choosing_the_trainer_is_for_admins_and_must_be_a_real_trainer(
        client, admin_headers, trainer, make_member):
    mine = make_member(assigned_trainer_id=trainer[0])
    assert create(client, trainer[1], mine["id"], trainer_id=trainer[0]).status_code == 403
    assert create(client, admin_headers, make_member()["id"], trainer_id=9999).status_code == 400
    desk = client.post("/api/staff", headers=admin_headers, json={
        "full_name": "Desk Two", "email": "desk2@gymfit.com", "password": "DeskPass123",
        "role": "Receptionist", "phone": "9000000099"}).json()
    assert create(client, admin_headers, make_member()["id"], trainer_id=desk["id"]).status_code == 400


def test_roles_and_scope(client, admin_headers, reception_headers, trainer, second_trainer, make_member):
    mine = make_member(assigned_trainer_id=trainer[0])
    other = make_member(assigned_trainer_id=second_trainer[0])
    plan = plan_of(client, admin_headers, mine["id"])
    exercise_id = client.post(f"/api/workouts/plans/{plan['id']}/exercises", headers=admin_headers,
                              json=exercise()).json()["id"]

    # receptionists have no access to workout data at all
    assert client.get("/api/workouts/plans", headers=reception_headers).status_code == 403
    assert create(client, reception_headers, mine["id"]).status_code == 403
    assert client.get(f"/api/workouts/plans/{plan['id']}", headers=reception_headers).status_code == 403
    assert patch(client, reception_headers, plan["id"], title="X").status_code == 403
    assert client.post(f"/api/workouts/plans/{plan['id']}/exercises", headers=reception_headers,
                       json=exercise()).status_code == 403
    assert client.delete(f"/api/workouts/exercises/{exercise_id}", headers=reception_headers).status_code == 403
    assert client.get("/api/workouts/muscle-groups", headers=reception_headers).status_code == 403

    # nobody logged in
    assert client.get("/api/workouts/plans").status_code == 401
    assert create(client, {}, mine["id"]).status_code == 401

    # a trainer cannot touch someone else's member: 404, as if it did not exist
    assert create(client, trainer[1], other["id"]).status_code == 404
    foreign = plan_of(client, admin_headers, other["id"])
    assert client.get(f"/api/workouts/plans/{foreign['id']}", headers=trainer[1]).status_code == 404
    assert patch(client, trainer[1], foreign["id"], title="Mine now").status_code == 404
    assert client.post(f"/api/workouts/plans/{foreign['id']}/exercises", headers=trainer[1],
                       json=exercise()).status_code == 404
    assert create(client, admin_headers, 9999).status_code == 404


def test_one_active_plan_per_member(client, admin_headers, make_member):
    member = make_member()
    first = plan_of(client, admin_headers, member["id"], title="First")
    again = create(client, admin_headers, member["id"], title="Second")
    assert again.status_code == 409 and "already has an active plan" in again.json()["detail"]

    done = patch(client, admin_headers, first["id"], status="completed")
    assert done.status_code == 200 and done.json()["end_date"] == TODAY.isoformat()
    second = plan_of(client, admin_headers, member["id"], title="Second")
    assert patch(client, admin_headers, first["id"], status="active").status_code == 409     # one is already active
    assert patch(client, admin_headers, second["id"], status="archived").status_code == 200
    assert patch(client, admin_headers, first["id"], status="active").status_code == 200


def test_invalid_plans_are_rejected(client, admin_headers, make_member):
    member = make_member()
    base = {"member_id": member["id"], "title": "Plan"}
    many = [exercise(1, name=f"E{i}") for i in range(61)]
    for bad in (
        {"title": None}, {"title": "   "}, {"start_date": "1999-01-01"}, {"start_date": iso(1), "end_date": iso(0)},
        {"is_admin": True}, {"status": "completed"}, {"exercises": many}, {"member_id": "abc"},
        {"exercises": [exercise(0)]}, {"exercises": [exercise(8)]},
        {"exercises": [exercise(sets=3, reps=None)]}, {"exercises": [exercise(sets=None, reps=10)]},
        {"exercises": [exercise(sets=None, reps=None)]}, {"exercises": [exercise(name="  ")]},
        {"exercises": [exercise(group=" ")]}, {"exercises": [exercise(sets=0)]}, {"exercises": [exercise(reps=0)]},
        {"exercises": [exercise(sets=21)]}, {"exercises": [exercise(sets=None, reps=None, duration_minutes=0)]},
        {"exercises": [exercise(rest_seconds=-1)]}, {"exercises": [exercise(surprise=1)]},
    ):
        assert client.post("/api/workouts/plans", headers=admin_headers, json={**base, **bad}).status_code == 422, bad
    assert client.post("/api/workouts/plans", headers=admin_headers, json={"title": "No member"}).status_code == 422
    assert client.get("/api/workouts/plans", headers=admin_headers).json()["total"] == 0


def test_thirty_exercises_a_day_at_most(client, admin_headers, make_member):
    too_many = [exercise(1, name=f"E{i}") for i in range(31)]
    assert create(client, admin_headers, make_member()["id"], exercises=too_many).status_code == 400
    plan = plan_of(client, admin_headers, make_member()["id"], exercises=too_many[:30])
    url = f"/api/workouts/plans/{plan['id']}/exercises"
    assert client.post(url, headers=admin_headers, json=exercise(1, name="One more")).status_code == 400
    assert client.post(url, headers=admin_headers, json=exercise(2, name="Other day")).status_code == 201


# ================================================================ listing
def test_list_scope_filters_and_pages(client, admin_headers, trainer, make_member):
    anita = make_member(full_name="Anita Sharma", assigned_trainer_id=trainer[0])
    ravi = make_member(full_name="Ravi Patel")
    meena = make_member(full_name="Meena Iyer", assigned_trainer_id=trainer[0])
    plan_of(client, admin_headers, anita["id"], title="Fat loss", goal="Lose 5 kg")
    plan_of(client, admin_headers, ravi["id"], title="Mass gain")
    archived = plan_of(client, admin_headers, meena["id"], title="Old plan")
    patch(client, admin_headers, archived["id"], status="archived")

    def titles(headers, query=""):
        return [p["title"] for p in client.get(f"/api/workouts/plans?{query}", headers=headers).json()["items"]]

    assert sorted(titles(admin_headers)) == ["Fat loss", "Mass gain", "Old plan"]
    assert sorted(titles(trainer[1])) == ["Fat loss", "Old plan"]                      # not Ravi's
    assert titles(admin_headers, f"member_id={ravi['id']}") == ["Mass gain"]
    assert titles(trainer[1], f"member_id={ravi['id']}") == []                           # no widening of access
    assert titles(admin_headers, "status=archived") == ["Old plan"]
    assert titles(admin_headers, "search=lose") == ["Fat loss"]
    assert titles(admin_headers, "search=ravi") == ["Mass gain"]
    assert titles(admin_headers, f"search={anita['member_code']}") == ["Fat loss"]
    assert titles(admin_headers, "search=%25") == []
    assert sorted(titles(admin_headers, f"trainer_id={trainer[0]}")) == ["Fat loss", "Old plan"]
    page = client.get("/api/workouts/plans?page=2&page_size=2", headers=admin_headers).json()
    assert page["total"] == 3 and page["pages"] == 2 and len(page["items"]) == 1
    assert client.get("/api/workouts/plans?status=banana", headers=admin_headers).status_code == 422


def test_plans_of_deleted_members_disappear(client, admin_headers, make_member):
    member = make_member()
    plan = plan_of(client, admin_headers, member["id"])
    client.delete(f"/api/members/{member['id']}", headers=admin_headers)
    assert client.get("/api/workouts/plans", headers=admin_headers).json()["total"] == 0
    assert client.get(f"/api/workouts/plans/{plan['id']}", headers=admin_headers).status_code == 404


# ================================================================ editing plans
def test_editing_an_active_plan(client, admin_headers, make_member):
    plan = plan_of(client, admin_headers, make_member()["id"])
    body = patch(client, admin_headers, plan["id"], title="Strength block 2", goal="Squat 100 kg",
                 notes="Deload week 4", start_date=iso(-3), end_date=iso(40)).json()
    assert body["title"] == "Strength block 2" and body["goal"] == "Squat 100 kg" and body["notes"] == "Deload week 4"
    assert body["start_date"] == iso(-3) and body["end_date"] == iso(40)
    assert patch(client, admin_headers, plan["id"], goal=None, end_date=None).json()["goal"] is None
    assert patch(client, admin_headers, plan["id"], title=None).status_code == 400
    assert patch(client, admin_headers, plan["id"], status=None).status_code == 400
    assert patch(client, admin_headers, plan["id"], end_date=iso(-10)).status_code == 400          # before start
    assert patch(client, admin_headers, plan["id"], member_id=1).status_code == 422
    assert patch(client, admin_headers, 9999, title="X").status_code == 404


def test_finished_plans_are_read_only_except_for_status(client, admin_headers, make_member):
    plan = plan_of(client, admin_headers, make_member()["id"], exercises=[exercise()])
    patch(client, admin_headers, plan["id"], status="completed")
    assert patch(client, admin_headers, plan["id"], title="Rewrite").status_code == 400
    assert patch(client, admin_headers, plan["id"], status="archived").status_code == 200
    assert patch(client, admin_headers, plan["id"], title="Rewrite").status_code == 400


def test_only_admin_changes_the_trainer(client, admin_headers, trainer, second_trainer, make_member):
    mine = make_member(assigned_trainer_id=trainer[0])
    plan = plan_of(client, trainer[1], mine["id"])
    assert patch(client, trainer[1], plan["id"], trainer_id=second_trainer[0]).status_code == 403
    assert patch(client, admin_headers, plan["id"], trainer_id=second_trainer[0]).json()["trainer_name"] == "Meera Nair"
    assert patch(client, admin_headers, plan["id"], trainer_id=9999).status_code == 400
    assert patch(client, admin_headers, plan["id"], trainer_id=None).json()["trainer_id"] is None


def test_reassigning_the_member_moves_the_access_to_the_new_trainer(
        client, admin_headers, trainer, second_trainer, make_member):
    member = make_member(assigned_trainer_id=trainer[0])
    plan = plan_of(client, trainer[1], member["id"])
    url = f"/api/workouts/plans/{plan['id']}"
    assert client.get(url, headers=trainer[1]).status_code == 200
    client.patch(f"/api/members/{member['id']}", headers=admin_headers,
                 json={"assigned_trainer_id": second_trainer[0]})
    assert client.get(url, headers=trainer[1]).status_code == 404
    assert client.get(url, headers=second_trainer[1]).status_code == 200
    assert client.post(f"{url}/exercises", headers=second_trainer[1], json=exercise()).status_code == 201


# ================================================================ exercises
def test_adding_exercises_numbers_them_per_day(client, admin_headers, make_member):
    plan = plan_of(client, admin_headers, make_member()["id"])
    url = f"/api/workouts/plans/{plan['id']}/exercises"
    first = client.post(url, headers=admin_headers, json=exercise(1, "chest", "Push-ups", sets=3, reps=15, notes="Slow"))
    assert first.status_code == 201
    body = first.json()
    assert body["sort_order"] == 1 and body["muscle_group"] == "Chest" and body["notes"] == "Slow"
    assert client.post(url, headers=admin_headers, json=exercise(1, "Chest", "Flyes")).json()["sort_order"] == 2
    assert client.post(url, headers=admin_headers, json=exercise(2, "Legs", "Squats")).json()["sort_order"] == 1
    assert client.post(url, headers=admin_headers, json=exercise(3, "Rotator cuff", "External rotation")).json()["muscle_group"] == "Rotator cuff"
    assert client.get(f"/api/workouts/plans/{plan['id']}", headers=admin_headers).json()["exercise_count"] == 4
    assert client.post("/api/workouts/plans/9999/exercises", headers=admin_headers, json=exercise()).status_code == 404
    assert client.post(url, headers=admin_headers, json={**exercise(), "sets": None, "reps": None}).status_code == 422


def test_editing_an_exercise(client, admin_headers, make_member):
    plan = plan_of(client, admin_headers, make_member()["id"], exercises=[exercise(1, name="Bench"), exercise(2, "Back", "Rows")])
    first, second = plan["days"][0]["exercises"][0], plan["days"][1]["exercises"][0]
    url = f"/api/workouts/exercises/{first['id']}"

    edited = client.patch(url, headers=admin_headers, json={"sets": 5, "muscle_group": "shoulders", "notes": "Heavy"})
    assert edited.status_code == 200
    assert edited.json()["sets"] == 5 and edited.json()["reps"] == 10 and edited.json()["muscle_group"] == "Shoulders"

    assert client.patch(url, headers=admin_headers, json={"reps": None}).status_code == 400          # sets without reps
    assert client.patch(url, headers=admin_headers, json={"reps": None, "duration_minutes": 15}).status_code == 200
    assert client.patch(url, headers=admin_headers, json={"exercise_name": None}).status_code == 400
    assert client.patch(url, headers=admin_headers, json={"day_number": 9}).status_code == 422
    assert client.patch(url, headers=admin_headers, json={"plan_id": 2}).status_code == 422
    assert client.patch("/api/workouts/exercises/9999", headers=admin_headers, json={"sets": 2}).status_code == 404

    moved = client.patch(url, headers=admin_headers, json={"day_number": 2})
    assert moved.json()["day_number"] == 2 and moved.json()["sort_order"] == second["sort_order"] + 1


def test_removing_an_exercise(client, admin_headers, make_member):
    plan = plan_of(client, admin_headers, make_member()["id"], exercises=[exercise(name="A"), exercise(name="B")])
    target = plan["days"][0]["exercises"][0]["id"]
    assert client.delete(f"/api/workouts/exercises/{target}", headers=admin_headers).status_code == 200
    detail = client.get(f"/api/workouts/plans/{plan['id']}", headers=admin_headers).json()
    assert [e["exercise_name"] for e in detail["days"][0]["exercises"]] == ["B"]
    assert client.delete(f"/api/workouts/exercises/{target}", headers=admin_headers).status_code == 404


def test_trainers_cannot_touch_exercises_of_other_trainers_members(client, admin_headers, trainer, second_trainer, make_member):
    foreign = plan_of(client, admin_headers, make_member(assigned_trainer_id=second_trainer[0])["id"], exercises=[exercise()])
    exercise_id = foreign["days"][0]["exercises"][0]["id"]
    assert client.patch(f"/api/workouts/exercises/{exercise_id}", headers=trainer[1], json={"sets": 9}).status_code == 404
    assert client.delete(f"/api/workouts/exercises/{exercise_id}", headers=trainer[1]).status_code == 404


def test_exercises_of_finished_plans_are_locked(client, admin_headers, make_member):
    plan = plan_of(client, admin_headers, make_member()["id"], exercises=[exercise(name="A"), exercise(name="B")])
    ids = [e["id"] for e in plan["days"][0]["exercises"]]
    patch(client, admin_headers, plan["id"], status="completed")
    assert client.post(f"/api/workouts/plans/{plan['id']}/exercises", headers=admin_headers, json=exercise()).status_code == 400
    assert client.patch(f"/api/workouts/exercises/{ids[0]}", headers=admin_headers, json={"sets": 4}).status_code == 400
    assert client.delete(f"/api/workouts/exercises/{ids[0]}", headers=admin_headers).status_code == 400
    assert client.post(f"/api/workouts/plans/{plan['id']}/reorder", headers=admin_headers,
                       json={"day_number": 1, "exercise_ids": ids[::-1]}).status_code == 400


def test_reordering_the_exercises_of_a_day(client, admin_headers, make_member):
    plan = plan_of(client, admin_headers, make_member()["id"], exercises=[
        exercise(1, name="A"), exercise(1, name="B"), exercise(1, name="C"), exercise(2, "Back", "Rows")])
    a, b, c = [e["id"] for e in plan["days"][0]["exercises"]]
    other_day = plan["days"][1]["exercises"][0]["id"]
    url = f"/api/workouts/plans/{plan['id']}/reorder"

    done = client.post(url, headers=admin_headers, json={"day_number": 1, "exercise_ids": [c, a, b]})
    assert done.status_code == 200
    day1 = done.json()["days"][0]["exercises"]
    assert [(e["exercise_name"], e["sort_order"]) for e in day1] == [("C", 1), ("A", 2), ("B", 3)]

    for bad in ([a, b], [a, b, c, other_day], [a, a, b], [a, b, other_day]):
        assert client.post(url, headers=admin_headers, json={"day_number": 1, "exercise_ids": bad}).status_code == 400, bad
    assert client.post(url, headers=admin_headers, json={"day_number": 1, "exercise_ids": []}).status_code == 422
    assert client.post(url, headers=admin_headers, json={"day_number": 8, "exercise_ids": [a]}).status_code == 422
    assert client.post("/api/workouts/plans/9999/reorder", headers=admin_headers,
                       json={"day_number": 1, "exercise_ids": [a]}).status_code == 404


def test_muscle_group_suggestions(client, admin_headers, trainer):
    groups = client.get("/api/workouts/muscle-groups", headers=admin_headers).json()
    assert "Chest" in groups and "Cardio" in groups and "Full body" in groups
    assert client.get("/api/workouts/muscle-groups", headers=trainer[1]).status_code == 200
    assert client.get("/api/workouts/muscle-groups").status_code == 401


def test_workout_changes_are_audited(client, admin_headers, make_member, session_factory):
    plan = plan_of(client, admin_headers, make_member()["id"], exercises=[exercise()])
    exercise_id = plan["days"][0]["exercises"][0]["id"]
    patch(client, admin_headers, plan["id"], title="Renamed")
    client.patch(f"/api/workouts/exercises/{exercise_id}", headers=admin_headers, json={"sets": 4})
    client.delete(f"/api/workouts/exercises/{exercise_id}", headers=admin_headers)
    with session_factory() as db:
        actions = {log.action for log in db.query(AuditLog).all()}
        update = db.query(AuditLog).filter_by(action="workout.plan_update").one()
    assert {"workout.plan_create", "workout.plan_update", "workout.exercise_update", "workout.exercise_delete"} <= actions
    assert update.new_values["changed"] == ["title"] and update.old_values["title"] == "Beginner strength"
