import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Attendance, AuditLog
from app.models._common import utcnow
from app.utils.dates import gym_today

TODAY = gym_today()


def iso(days_from_today):
    return (TODAY + timedelta(days=days_from_today)).isoformat()


def check_in(client, headers, member_id, **extra):
    return client.post("/api/attendance/check-in", headers=headers, json={"member_id": member_id, **extra})


def check_out(client, headers, member_id):
    return client.post("/api/attendance/check-out", headers=headers, json={"member_id": member_id})


def audit_actions(session_factory):
    with session_factory() as db:
        return [log.action for log in db.query(AuditLog).all()]


# ======================================================== check-in and check-out
def test_check_in_and_check_out_flow(client, reception_headers, paid_member):
    member = paid_member()
    entered = check_in(client, reception_headers, member["id"])
    assert entered.status_code == 201
    body = entered.json()
    assert body["status"] == "inside" and body["member"]["id"] == member["id"]
    assert body["check_out_at"] is None and body["check_out_local"] is None
    assert body["minutes_inside"] >= 0 and body["is_stale"] is False
    assert body["checked_in_by_name"] == "Front Desk" and isinstance(body["check_in_local"], str)
    assert body["check_in_at"].endswith("Z")                       # UTC, clearly marked

    left = check_out(client, reception_headers, member["id"])
    assert left.status_code == 200
    out = left.json()
    assert out["status"] == "completed" and out["check_out_at"] is not None
    assert 0 <= out["duration_minutes"] <= 1 and out["minutes_inside"] is None
    assert out["checked_out_by_name"] == "Front Desk" and out["id"] == body["id"]


def test_duration_is_counted_in_minutes(client, admin_headers, paid_member, shift_visit):
    member = paid_member()
    visit_id = check_in(client, admin_headers, member["id"]).json()["id"]
    shift_visit(visit_id, minutes=90)
    assert 90 <= check_out(client, admin_headers, member["id"]).json()["duration_minutes"] <= 91


def test_second_check_in_is_blocked(client, admin_headers, paid_member):
    member = paid_member()
    assert check_in(client, admin_headers, member["id"]).status_code == 201
    again = check_in(client, admin_headers, member["id"])
    assert again.status_code == 409 and "already checked in" in again.json()["detail"]
    assert client.get("/api/attendance", headers=admin_headers).json()["total"] == 1


def test_check_out_needs_an_open_visit(client, admin_headers, paid_member):
    member = paid_member()
    never = check_out(client, admin_headers, member["id"])
    assert never.status_code == 400 and "not checked in" in never.json()["detail"]
    check_in(client, admin_headers, member["id"])
    assert check_out(client, admin_headers, member["id"]).status_code == 200
    assert check_out(client, admin_headers, member["id"]).status_code == 400


def test_member_can_visit_again_after_leaving(client, admin_headers, paid_member):
    member = paid_member()
    check_in(client, admin_headers, member["id"])
    check_out(client, admin_headers, member["id"])
    assert check_in(client, admin_headers, member["id"]).status_code == 201
    assert client.get(f"/api/attendance?member_id={member['id']}", headers=admin_headers).json()["total"] == 2


def test_unknown_and_deleted_members(client, admin_headers, paid_member):
    assert check_in(client, admin_headers, 9999).status_code == 404
    assert check_out(client, admin_headers, 9999).status_code == 404
    gone = paid_member()
    client.delete(f"/api/members/{gone['id']}", headers=admin_headers)
    assert check_in(client, admin_headers, gone["id"]).status_code == 404

    inside = paid_member()
    check_in(client, admin_headers, inside["id"])
    client.delete(f"/api/members/{inside['id']}", headers=admin_headers)
    assert check_out(client, admin_headers, inside["id"]).status_code == 200   # someone can always leave


def test_roles_and_login(client, admin_headers, reception_headers, trainer, paid_member):
    member = paid_member()
    assert client.post("/api/attendance/check-in", json={"member_id": member["id"]}).status_code == 401
    assert check_in(client, trainer[1], member["id"]).status_code == 403
    assert check_out(client, trainer[1], member["id"]).status_code == 403
    assert client.post("/api/attendance/close-stale", headers=trainer[1]).status_code == 403
    assert client.get("/api/attendance/lookup?search=ab", headers=trainer[1]).status_code == 403
    assert check_in(client, reception_headers, member["id"]).status_code == 201
    assert check_out(client, admin_headers, member["id"]).status_code == 200


def test_invalid_payloads(client, admin_headers, paid_member):
    member = paid_member()
    assert client.post("/api/attendance/check-in", headers=admin_headers, json={}).status_code == 422
    assert check_in(client, admin_headers, member["id"], checked_in_by=1).status_code == 422
    assert check_in(client, admin_headers, member["id"], override_reason="no").status_code == 422
    assert client.post("/api/attendance/check-out", headers=admin_headers, json={}).status_code == 422


def test_attendance_actions_are_audited(client, admin_headers, paid_member, session_factory):
    member = paid_member()
    check_in(client, admin_headers, member["id"])
    check_out(client, admin_headers, member["id"])
    actions = audit_actions(session_factory)
    assert "attendance.check_in" in actions and "attendance.check_out" in actions


def test_database_itself_refuses_two_open_visits(session_factory, make_member):
    member = make_member()
    with session_factory() as db:
        db.add(Attendance(member_id=member["id"], check_in_at=utcnow(), status="inside"))
        db.commit()
        db.add(Attendance(member_id=member["id"], check_in_at=utcnow(), status="inside"))
        with pytest.raises(IntegrityError):
            db.commit()


# ======================================================== access rules
def test_unpaid_member_is_denied_until_the_fee_is_paid(client, admin_headers, reception_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1000")
    member = make_member(plan_id=plan["id"])
    invoice_id = member["current_membership"]["invoice"]["id"]
    denied = check_in(client, reception_headers, member["id"])
    assert denied.status_code == 403 and "not fully paid" in denied.json()["detail"]

    client.post(f"/api/invoices/{invoice_id}/payments", headers=admin_headers, json={"amount": "400", "method": "cash"})
    assert check_in(client, reception_headers, member["id"]).status_code == 403     # part-paid is still unpaid
    client.post(f"/api/invoices/{invoice_id}/payments", headers=admin_headers, json={"amount": "600", "method": "cash"})
    assert check_in(client, reception_headers, member["id"]).status_code == 201


def test_unpaid_members_can_enter_when_the_gym_allows_it(client, reception_headers, make_plan, make_member, set_setting):
    set_setting("allow_checkin_unpaid", "true")
    member = make_member(plan_id=make_plan("Monthly", 30, "1000")["id"])
    assert check_in(client, reception_headers, member["id"]).status_code == 201


def test_no_membership_expired_upcoming_and_inactive_are_denied(client, admin_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1000")

    nothing = make_member()
    assert "no membership" in check_in(client, admin_headers, nothing["id"]).json()["detail"].lower()

    expired = make_member()
    client.post(f"/api/members/{expired['id']}/memberships", headers=admin_headers,
                json={"plan_id": plan["id"], "start_date": iso(-60)})
    denied = check_in(client, admin_headers, expired["id"])
    assert denied.status_code == 403 and "expired on" in denied.json()["detail"]

    upcoming = make_member()
    client.post(f"/api/members/{upcoming['id']}/memberships", headers=admin_headers,
                json={"plan_id": plan["id"], "start_date": iso(10)})
    assert "starts on" in check_in(client, admin_headers, upcoming["id"]).json()["detail"]

    inactive = make_member()
    client.patch(f"/api/members/{inactive['id']}", headers=admin_headers, json={"status": "inactive"})
    assert "inactive" in check_in(client, admin_headers, inactive["id"]).json()["detail"].lower()


def test_grace_period_lets_a_recent_expiry_in(client, admin_headers, make_plan, make_member, set_setting):
    set_setting("allow_checkin_unpaid", "true")
    plan = make_plan("Monthly", 30, "1000")
    member = make_member()
    client.post(f"/api/members/{member['id']}/memberships", headers=admin_headers,
                json={"plan_id": plan["id"], "start_date": iso(-31)})      # ended 2 days ago

    set_setting("grace_period_days", "1")
    assert check_in(client, admin_headers, member["id"]).status_code == 403
    set_setting("grace_period_days", "3")
    shown = client.get("/api/attendance/lookup?search=" + member["member_code"], headers=admin_headers).json()[0]
    assert shown["access"]["allowed"] is True and shown["access"]["in_grace"] is True
    assert shown["access"]["code"] == "grace"
    assert check_in(client, admin_headers, member["id"]).status_code == 201


def test_free_plan_member_can_enter(client, admin_headers, make_plan, make_member):
    member = make_member(plan_id=make_plan("Free trial", 7, "0")["id"])
    assert member["current_membership"]["invoice"] is None
    assert check_in(client, admin_headers, member["id"]).status_code == 201


def test_cancelled_membership_is_denied(client, admin_headers, make_plan, make_member):
    member = make_member(plan_id=make_plan("Monthly", 30, "1000")["id"])
    membership_id = client.get(f"/api/members/{member['id']}/memberships", headers=admin_headers).json()[0]["id"]
    assert client.post(f"/api/members/{member['id']}/memberships/{membership_id}/cancel",
                       headers=admin_headers).status_code == 200
    assert "no membership" in check_in(client, admin_headers, member["id"]).json()["detail"].lower()


def test_only_an_admin_can_override_a_denied_check_in(client, admin_headers, reception_headers, make_member, session_factory):
    member = make_member()                                   # no membership: denied
    assert check_in(client, admin_headers, member["id"]).status_code == 403            # no reason given
    by_desk = check_in(client, reception_headers, member["id"], override_reason="Guest day pass")
    assert by_desk.status_code == 403 and "Only an Admin" in by_desk.json()["detail"]

    allowed = check_in(client, admin_headers, member["id"], override_reason="Guest day pass")
    assert allowed.status_code == 201
    assert allowed.json()["notes"] == "Override by Main Admin: Guest day pass"
    assert "attendance.check_in_override" in audit_actions(session_factory)


# ======================================================== lookup
def test_lookup_shows_inside_flag_and_access(client, admin_headers, reception_headers, make_plan, make_member, paid_member):
    anita = paid_member(full_name="Anita Sharma", phone="9811122233")
    unpaid = make_member(full_name="Anil Unpaid", plan_id=make_plan("Other plan", 30, "500")["id"])

    found = client.get("/api/attendance/lookup?search=anita", headers=reception_headers).json()
    assert len(found) == 1 and found[0]["member"]["id"] == anita["id"]
    assert found[0]["inside"] is False and found[0]["inside_since_local"] is None
    assert found[0]["access"]["allowed"] is True and found[0]["access"]["code"] == "ok"

    check_in(client, admin_headers, anita["id"])
    again = client.get("/api/attendance/lookup?search=9811122233", headers=reception_headers).json()[0]
    assert again["inside"] is True and isinstance(again["inside_since_local"], str)

    denied = client.get("/api/attendance/lookup?search=unpaid", headers=reception_headers).json()[0]
    assert denied["member"]["id"] == unpaid["id"]
    assert denied["access"]["allowed"] is False and denied["access"]["code"] == "unpaid"


def test_lookup_limits_hides_deleted_and_validates(client, admin_headers, make_member):
    for index in range(12):
        make_member(full_name=f"Zed {index:02d}")
    assert len(client.get("/api/attendance/lookup?search=zed", headers=admin_headers).json()) == 10
    gone = make_member(full_name="Qwerty Gone")
    client.delete(f"/api/members/{gone['id']}", headers=admin_headers)
    assert client.get("/api/attendance/lookup?search=qwerty", headers=admin_headers).json() == []
    assert client.get("/api/attendance/lookup?search=a", headers=admin_headers).status_code == 422
    assert client.get("/api/attendance/lookup", headers=admin_headers).status_code == 422
    assert client.get("/api/attendance/lookup?search=zed").status_code == 401
    assert client.get("/api/attendance/lookup?search=%25%25", headers=admin_headers).json() == []


# ======================================================== who is inside
def test_inside_list_tracks_who_is_in(client, admin_headers, paid_member):
    first, second = paid_member(full_name="First In"), paid_member(full_name="Second In")
    assert client.get("/api/attendance/inside", headers=admin_headers).json()["count"] == 0
    check_in(client, admin_headers, first["id"])
    check_in(client, admin_headers, second["id"])
    inside = client.get("/api/attendance/inside", headers=admin_headers).json()
    assert inside["count"] == 2 and inside["stale_count"] == 0
    assert [i["member"]["full_name"] for i in inside["items"]] == ["First In", "Second In"]   # oldest first
    check_out(client, admin_headers, first["id"])
    left = client.get("/api/attendance/inside", headers=admin_headers).json()
    assert left["count"] == 1 and left["items"][0]["member"]["id"] == second["id"]


def test_long_open_visits_are_flagged_and_the_limit_is_a_setting(client, admin_headers, paid_member, shift_visit, set_setting):
    member = paid_member()
    visit_id = check_in(client, admin_headers, member["id"]).json()["id"]
    shift_visit(visit_id, hours=9)
    flagged = client.get("/api/attendance/inside", headers=admin_headers).json()
    assert flagged["stale_count"] == 1 and flagged["items"][0]["is_stale"] is True
    assert flagged["items"][0]["minutes_inside"] >= 540
    set_setting("auto_checkout_hours", "12")
    assert client.get("/api/attendance/inside", headers=admin_headers).json()["stale_count"] == 0


def test_trainer_sees_only_own_members(client, admin_headers, trainer, paid_member):
    trainer_id, trainer_headers = trainer
    mine = paid_member(full_name="Mine", assigned_trainer_id=trainer_id)
    other = paid_member(full_name="Not Mine")
    check_in(client, admin_headers, mine["id"])
    check_in(client, admin_headers, other["id"])

    inside = client.get("/api/attendance/inside", headers=trainer_headers).json()
    assert inside["count"] == 1 and inside["items"][0]["member"]["id"] == mine["id"]
    history = client.get("/api/attendance", headers=trainer_headers).json()
    assert history["total"] == 1 and history["items"][0]["member"]["id"] == mine["id"]
    assert client.get(f"/api/attendance?member_id={other['id']}", headers=trainer_headers).json()["total"] == 0
    assert client.get("/api/attendance/inside").status_code == 401


# ======================================================== forgotten check-outs
def test_forgotten_check_out_is_closed_safely_on_the_next_check_in(client, admin_headers, paid_member, shift_visit, session_factory):
    member = paid_member()
    old_id = check_in(client, admin_headers, member["id"]).json()["id"]
    shift_visit(old_id, hours=10)

    new_visit = check_in(client, admin_headers, member["id"])
    assert new_visit.status_code == 201 and new_visit.json()["id"] != old_id

    old = client.get(f"/api/attendance/{old_id}", headers=admin_headers).json()
    assert old["status"] == "auto_closed" and old["duration_minutes"] == 480      # capped at 8 hours
    assert old["checked_out_by_name"] is None and "Auto-closed" in old["notes"]
    assert client.get("/api/attendance/inside", headers=admin_headers).json()["count"] == 1
    assert "attendance.auto_close" in audit_actions(session_factory)


def test_cleanup_is_kept_even_when_the_new_check_in_is_refused(client, admin_headers, paid_member, shift_visit):
    member = paid_member()
    old_id = check_in(client, admin_headers, member["id"]).json()["id"]
    shift_visit(old_id, hours=10)
    client.patch(f"/api/members/{member['id']}", headers=admin_headers, json={"status": "inactive"})
    assert check_in(client, admin_headers, member["id"]).status_code == 403
    assert client.get(f"/api/attendance/{old_id}", headers=admin_headers).json()["status"] == "auto_closed"


def test_close_stale_closes_only_old_visits(client, admin_headers, reception_headers, paid_member, shift_visit):
    old_member, fresh_member = paid_member(), paid_member()
    old_id = check_in(client, admin_headers, old_member["id"]).json()["id"]
    check_in(client, admin_headers, fresh_member["id"])
    shift_visit(old_id, hours=9)
    assert client.post("/api/attendance/close-stale", headers=reception_headers).json() == {"closed": 1}
    assert client.post("/api/attendance/close-stale", headers=reception_headers).json() == {"closed": 0}
    inside = client.get("/api/attendance/inside", headers=admin_headers).json()
    assert inside["count"] == 1 and inside["items"][0]["member"]["id"] == fresh_member["id"]


def test_close_stale_follows_the_gym_setting(client, admin_headers, paid_member, shift_visit, set_setting):
    set_setting("auto_checkout_hours", "2")
    member = paid_member()
    visit_id = check_in(client, admin_headers, member["id"]).json()["id"]
    shift_visit(visit_id, hours=3)
    assert client.post("/api/attendance/close-stale", headers=admin_headers).json() == {"closed": 1}
    assert client.get(f"/api/attendance/{visit_id}", headers=admin_headers).json()["duration_minutes"] == 120


# ======================================================== history and filters
def test_history_filters_search_and_pages(client, admin_headers, paid_member):
    anita, ravi = paid_member(full_name="Anita Sharma"), paid_member(full_name="Ravi Patel")
    for member in (anita, ravi, anita):
        check_in(client, admin_headers, member["id"])
        check_out(client, admin_headers, member["id"])

    everything = client.get("/api/attendance", headers=admin_headers).json()
    ids = [v["id"] for v in everything["items"]]
    assert everything["total"] == 3 and ids == sorted(ids, reverse=True)           # newest first
    assert client.get(f"/api/attendance?member_id={anita['id']}", headers=admin_headers).json()["total"] == 2
    assert client.get("/api/attendance?search=ravi", headers=admin_headers).json()["total"] == 1
    assert client.get("/api/attendance?status=completed", headers=admin_headers).json()["total"] == 3
    assert client.get("/api/attendance?status=auto_closed", headers=admin_headers).json()["total"] == 0
    page = client.get("/api/attendance?page=2&page_size=2", headers=admin_headers).json()
    assert page["pages"] == 2 and len(page["items"]) == 1
    assert client.get("/api/attendance?status=banana", headers=admin_headers).status_code == 422
    assert client.get("/api/attendance").status_code == 401


def test_day_week_month_filters_use_gym_local_dates(client, admin_headers, paid_member, add_visit):
    member = paid_member()
    # 12:00 UTC = 17:30 IST on the 10th | 19:00 UTC = 00:30 IST on the 11th | 10:00 UTC = 15:30 IST on the 15th
    add_visit(member["id"], datetime(2026, 3, 10, 12, 0), datetime(2026, 3, 10, 13, 0))
    add_visit(member["id"], datetime(2026, 3, 10, 19, 0), datetime(2026, 3, 10, 20, 0))
    add_visit(member["id"], datetime(2026, 3, 15, 10, 0), datetime(2026, 3, 15, 11, 0))

    def total(query):
        return client.get(f"/api/attendance?{query}", headers=admin_headers).json()["total"]

    assert total("period=day&date=2026-03-10") == 1
    assert total("period=day&date=2026-03-11") == 1                  # the late visit belongs to the 11th locally
    assert total("period=week&date=2026-03-12") == 3                 # Monday 9th to Sunday 15th
    assert total("period=week&date=2026-03-16") == 0
    assert total("period=month&date=2026-03-31") == 3
    assert total("period=month&date=2026-04-01") == 0
    assert total("period=month&date=2026-02-10") == 0
    assert total("date_from=2026-03-10&date_to=2026-03-10") == 1
    assert total("date_from=2026-03-11&date_to=2026-03-20") == 2

    assert client.get("/api/attendance?period=week&date_from=2026-03-01", headers=admin_headers).status_code == 400
    assert client.get("/api/attendance?date_from=2026-03-02&date_to=2026-03-01", headers=admin_headers).status_code == 400
    assert client.get("/api/attendance?date_from=2024-01-01&date_to=2026-03-01", headers=admin_headers).status_code == 400
    assert client.get("/api/attendance?period=year", headers=admin_headers).status_code == 422


def test_get_single_attendance_record(client, admin_headers, trainer, paid_member):
    member = paid_member()
    visit_id = check_in(client, admin_headers, member["id"]).json()["id"]
    assert client.get(f"/api/attendance/{visit_id}", headers=admin_headers).json()["member"]["id"] == member["id"]
    assert client.get("/api/attendance/9999", headers=admin_headers).status_code == 404
    assert client.get(f"/api/attendance/{visit_id}", headers=trainer[1]).status_code == 403


# ======================================================== corrections
def test_admin_corrects_times_in_gym_local_time(client, admin_headers, paid_member, add_visit, session_factory):
    member = paid_member()
    visit_id = add_visit(member["id"], datetime(2026, 3, 10, 4, 0), datetime(2026, 3, 10, 5, 0))
    response = client.patch(f"/api/attendance/{visit_id}", headers=admin_headers, json={
        "check_in_at": "2026-03-10T10:00:00", "check_out_at": "2026-03-10T11:30:00",
        "reason": "Entered the wrong time"})
    assert response.status_code == 200
    body = response.json()
    assert body["check_in_at"] == "2026-03-10T04:30:00Z" and body["check_out_at"] == "2026-03-10T06:00:00Z"
    assert body["check_in_local"] == "10 Mar 2026, 10:00 AM" and body["duration_minutes"] == 90
    assert body["status"] == "corrected" and body["notes"].startswith("Corrected by Main Admin")

    with session_factory() as db:
        log = db.query(AuditLog).filter_by(action="attendance.correct").one()
        assert log.old_values["check_in_at"].startswith("2026-03-10 04:00")
        assert log.new_values["reason"] == "Entered the wrong time"


def test_times_with_an_offset_are_converted_exactly(client, admin_headers, paid_member, add_visit):
    visit_id = add_visit(paid_member()["id"], datetime(2026, 3, 10, 4, 0), datetime(2026, 3, 10, 5, 0))
    body = client.patch(f"/api/attendance/{visit_id}", headers=admin_headers, json={
        "check_in_at": "2026-03-10T10:00:00Z", "check_out_at": "2026-03-10T16:30:00+05:30",
        "reason": "Fixed from the paper log"}).json()
    assert body["check_in_at"] == "2026-03-10T10:00:00Z" and body["check_out_at"] == "2026-03-10T11:00:00Z"
    assert body["duration_minutes"] == 60


def test_invalid_corrections(client, admin_headers, paid_member, add_visit):
    visit_id = add_visit(paid_member()["id"], datetime(2026, 3, 10, 4, 0), datetime(2026, 3, 10, 5, 0))
    url = f"/api/attendance/{visit_id}"
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    def patch(body):
        return client.patch(url, headers=admin_headers, json=body).status_code

    assert patch({"check_out_at": "2026-03-10T03:00:00Z", "reason": "Out before in"}) == 400
    assert patch({"check_out_at": tomorrow, "reason": "Future time"}) == 400
    assert patch({"check_out_at": "2026-03-11T05:00:00Z", "reason": "More than a day"}) == 400
    assert patch({"reason": "No times given"}) == 422
    assert patch({"check_in_at": "2026-03-10T04:00:00Z"}) == 422                       # reason is required
    assert patch({"check_in_at": "2026-03-10T04:00:00Z", "reason": "abc"}) == 422        # reason too short
    assert patch({"check_in_at": "yesterday", "reason": "Not a time"}) == 422
    assert patch({"check_in_at": "2026-03-10T04:00:00Z", "reason": "Extra field", "status": "inside"}) == 422
    assert client.patch("/api/attendance/9999", headers=admin_headers,
                        json={"check_in_at": "2026-03-10T04:00:00Z", "reason": "Unknown record"}).status_code == 404


def test_a_correction_cannot_overlap_another_visit(client, admin_headers, paid_member, add_visit):
    member = paid_member()
    add_visit(member["id"], datetime(2026, 3, 10, 10, 0), datetime(2026, 3, 10, 11, 0))
    second = add_visit(member["id"], datetime(2026, 3, 10, 12, 0), datetime(2026, 3, 10, 13, 0))
    url = f"/api/attendance/{second}"
    assert client.patch(url, headers=admin_headers, json={
        "check_in_at": "2026-03-10T10:30:00Z", "reason": "Overlaps the first"}).status_code == 409
    assert client.patch(url, headers=admin_headers, json={
        "check_in_at": "2026-03-10T11:30:00Z", "reason": "Fits after the first"}).status_code == 200


def test_correcting_an_open_visit_can_close_it(client, admin_headers, paid_member):
    member = paid_member()
    visit_id = check_in(client, admin_headers, member["id"]).json()["id"]
    body = client.patch(f"/api/attendance/{visit_id}", headers=admin_headers, json={
        "check_out_at": datetime.now(timezone.utc).isoformat(), "reason": "Left but was not checked out"}).json()
    assert body["status"] == "corrected" and body["check_out_at"] is not None
    assert client.get("/api/attendance/inside", headers=admin_headers).json()["count"] == 0
    assert check_in(client, admin_headers, member["id"]).status_code == 201


def test_only_an_admin_can_correct_or_remove(client, reception_headers, trainer, paid_member, add_visit):
    visit_id = add_visit(paid_member()["id"], datetime(2026, 3, 10, 4, 0), datetime(2026, 3, 10, 5, 0))
    body = {"check_in_at": "2026-03-10T04:30:00Z", "reason": "Trying to fix it"}
    assert client.patch(f"/api/attendance/{visit_id}", json=body).status_code == 401
    assert client.patch(f"/api/attendance/{visit_id}", headers=reception_headers, json=body).status_code == 403
    assert client.patch(f"/api/attendance/{visit_id}", headers=trainer[1], json=body).status_code == 403
    assert client.post(f"/api/attendance/{visit_id}/remove", headers=reception_headers,
                       json={"reason": "Wrong member"}).status_code == 403


def test_admin_removes_a_mistaken_check_in_and_the_record_is_kept_in_the_audit_log(
        client, admin_headers, paid_member, session_factory):
    member = paid_member()
    visit_id = check_in(client, admin_headers, member["id"]).json()["id"]
    url = f"/api/attendance/{visit_id}/remove"
    assert client.post(url, headers=admin_headers, json={}).status_code == 422
    assert client.post(url, headers=admin_headers, json={"reason": "no"}).status_code == 422
    assert client.post("/api/attendance/9999/remove", headers=admin_headers, json={"reason": "Unknown record"}).status_code == 404

    assert client.post(url, headers=admin_headers, json={"reason": "Wrong member typed"}).status_code == 200
    assert client.get(f"/api/attendance/{visit_id}", headers=admin_headers).status_code == 404
    assert client.get("/api/attendance", headers=admin_headers).json()["total"] == 0
    assert check_in(client, admin_headers, member["id"]).status_code == 201     # no longer 'inside'

    with session_factory() as db:
        log = db.query(AuditLog).filter_by(action="attendance.remove").one()
        assert log.old_values["member_id"] == member["id"] and log.new_values["reason"] == "Wrong member typed"


# ======================================================== reports
@pytest.fixture()
def march_10(paid_member, add_visit):
    """Five visits on 10 March 2026 (local), timed in UTC. Returns the three members."""
    one, two, three = paid_member(full_name="One"), paid_member(full_name="Two"), paid_member(full_name="Three")
    add_visit(one["id"], datetime(2026, 3, 10, 1, 0), datetime(2026, 3, 10, 2, 0), minutes=60)             # 06:30 IST
    add_visit(two["id"], datetime(2026, 3, 10, 1, 15), datetime(2026, 3, 10, 1, 45), minutes=30)           # 06:45 IST
    add_visit(one["id"], datetime(2026, 3, 10, 12, 40), datetime(2026, 3, 10, 13, 25), minutes=45)         # 18:10 IST
    add_visit(three["id"], datetime(2026, 3, 10, 1, 40), datetime(2026, 3, 10, 9, 40), "auto_closed", 480)  # 07:10 IST
    add_visit(two["id"], datetime(2026, 3, 10, 3, 0), datetime(2026, 3, 10, 3, 25), "corrected", 25)       # 08:30 IST
    return one, two, three


def test_daily_report(client, admin_headers, march_10):
    report = client.get("/api/attendance/report?period=day&date=2026-03-10", headers=admin_headers).json()
    assert report["date_from"] == report["date_to"] == "2026-03-10"
    assert report["visits"] == 5 and report["unique_members"] == 3
    assert report["avg_duration_minutes"] == 40.0                       # (60+30+45+25)/4, auto-closed excluded
    assert report["auto_closed_count"] == 1 and report["corrected_count"] == 1 and report["still_inside"] == 0
    assert report["peak_label"] == "06" and report["peak_visits"] == 2
    series = {p["label"]: p for p in report["series"]}
    assert len(report["series"]) == 24
    assert series["06"] == {"label": "06", "visits": 2, "unique_members": 2}
    assert series["07"]["visits"] == 1 and series["08"]["visits"] == 1 and series["18"]["visits"] == 1
    assert series["00"]["visits"] == 0


def test_weekly_and_monthly_reports(client, admin_headers, march_10):
    week = client.get("/api/attendance/report?period=week&date=2026-03-12", headers=admin_headers).json()
    assert [p["label"] for p in week["series"]][0] == "2026-03-09" and len(week["series"]) == 7
    assert week["date_from"] == "2026-03-09" and week["date_to"] == "2026-03-15"
    busy = {p["label"]: p for p in week["series"]}["2026-03-10"]
    assert busy["visits"] == 5 and busy["unique_members"] == 3
    assert week["peak_label"] == "2026-03-10" and week["peak_visits"] == 5

    month = client.get("/api/attendance/report?period=month&date=2026-03-31", headers=admin_headers).json()
    assert len(month["series"]) == 31 and month["visits"] == 5
    empty = client.get("/api/attendance/report?period=month&date=2026-02-10", headers=admin_headers).json()
    assert empty["visits"] == 0 and empty["peak_label"] is None and empty["avg_duration_minutes"] is None


def test_report_counts_people_still_inside(client, admin_headers, paid_member):
    check_in(client, admin_headers, paid_member()["id"])
    report = client.get("/api/attendance/report", headers=admin_headers).json()
    assert report["period"] == "day" and report["visits"] == 1 and report["still_inside"] == 1
    assert report["avg_duration_minutes"] is None and report["peak_visits"] == 1


def test_report_access_and_validation(client, admin_headers, reception_headers, trainer):
    assert client.get("/api/attendance/report", headers=reception_headers).status_code == 200
    assert client.get("/api/attendance/report", headers=trainer[1]).status_code == 403
    assert client.get("/api/attendance/report").status_code == 401
    assert client.get("/api/attendance/report?period=year", headers=admin_headers).status_code == 422
    assert client.get("/api/attendance/report?date=nope", headers=admin_headers).status_code == 422


# ======================================================== CSV export
def rows_of(response):
    return list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))


def test_csv_export(client, admin_headers, paid_member):
    member = paid_member(full_name="Anita Sharma")
    check_in(client, admin_headers, member["id"])
    check_out(client, admin_headers, member["id"])
    today = TODAY.isoformat()
    response = client.get(f"/api/attendance/export.csv?date_from={today}&date_to={today}", headers=admin_headers)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == f'attachment; filename="attendance_{today}_{today}.csv"'
    rows = rows_of(response)
    assert rows[0] == ["Member code", "Member name", "Check-in (local)", "Check-out (local)",
                       "Duration (min)", "Status", "Checked in by", "Checked out by", "Notes"]
    assert len(rows) == 2 and rows[1][0] == member["member_code"] and rows[1][1] == "Anita Sharma"
    assert rows[1][2].startswith(today) and rows[1][5] == "completed"
    assert rows[1][6] == "Main Admin" and rows[1][7] == "Main Admin"


def test_csv_blocks_formula_injection_and_respects_the_range(client, admin_headers, paid_member):
    member = paid_member(full_name="=1+1")
    check_in(client, admin_headers, member["id"])
    today = TODAY.isoformat()
    rows = rows_of(client.get(f"/api/attendance/export.csv?date_from={today}&date_to={today}", headers=admin_headers))
    assert rows[1][1] == "'=1+1"
    old = client.get("/api/attendance/export.csv?date_from=2020-01-01&date_to=2020-01-31", headers=admin_headers)
    assert len(rows_of(old)) == 1                                       # header only


def test_csv_export_rules(client, reception_headers, admin_headers):
    url = f"/api/attendance/export.csv?date_from={TODAY.isoformat()}&date_to={TODAY.isoformat()}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=reception_headers).status_code == 403
    assert client.get("/api/attendance/export.csv", headers=admin_headers).status_code == 422
    assert client.get("/api/attendance/export.csv?date_from=2026-03-02&date_to=2026-03-01", headers=admin_headers).status_code == 400
    assert client.get("/api/attendance/export.csv?date_from=2020-01-01&date_to=2026-03-01", headers=admin_headers).status_code == 400
