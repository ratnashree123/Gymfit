from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.utils.dates import gym_today

TODAY = gym_today()
D = Decimal


def iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


def money(value):
    return D(str(value))


@pytest.fixture()
def gym(client, admin_headers, trainer, make_plan, make_member, paid_member, make_equipment, make_job):
    """Six members in six different situations, three pieces of equipment, one visit, one payment."""
    trainer_id, _ = trainer
    a = paid_member(full_name="Active A", assigned_trainer_id=trainer_id)          # running, fully paid
    short = make_plan("Short 400", 5, "400")
    monthly = make_plan("Monthly 1000", 30, "1000")
    b = make_member(full_name="Expiring B", assigned_trainer_id=trainer_id, plan_id=short["id"])   # ends in 4 days
    c = make_member(full_name="Expired C")
    client.post(f"/api/members/{c['id']}/memberships", headers=admin_headers,
                json={"plan_id": monthly["id"], "start_date": iso(-60)})            # ended 31 days ago
    d = make_member(full_name="Nothing D")
    e = make_member(full_name="Inactive E", plan_id=monthly["id"])
    client.patch(f"/api/members/{e['id']}", headers=admin_headers, json={"status": "inactive"})
    f = make_member(full_name="Upcoming F")
    client.post(f"/api/members/{f['id']}/memberships", headers=admin_headers,
                json={"plan_id": monthly["id"], "start_date": iso(20)})
    make_equipment(name="Broken", status="damaged")
    due = make_equipment(name="Due soon")
    make_job(due["id"], days=3)
    make_equipment(name="Fine")
    client.post("/api/attendance/check-in", headers=admin_headers, json={"member_id": a["id"]})
    return SimpleNamespace(a=a, b=b, c=c, d=d, e=e, f=f)


def dash(client, headers):
    response = client.get("/api/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ================================================================ admin
def test_admin_sees_every_number(client, admin_headers, gym):
    body = dash(client, admin_headers)
    assert body["role"] == "Admin" and body["scope"] == "all" and body["generated_at"].endswith("Z")
    assert body["members"] == {"total": 6, "active": 5, "inactive": 1, "joined_this_month": 6}
    assert body["memberships"] == {"active": 2, "expiring_soon": 1, "expired": 1, "upcoming": 1,
                                   "no_membership": 1, "inactive": 1, "alert_days": 7}
    assert body["attendance"] == {"visits_today": 1, "inside_now": 1, "stale_inside": 0}
    assert body["trainers_total"] == 1

    money_block = body["money"]
    assert money(money_block["collected_today"]) == D("1000") and money_block["payments_today"] == 1
    assert money(money_block["collected_this_month"]) == D("1000")
    assert money_block["pending_count"] == 4 and money_block["overdue_count"] == 0
    assert money(money_block["outstanding_total"]) == D("3400") and money(money_block["overdue_total"]) == D("0")

    assert body["equipment"] == {"records": 3, "total_quantity": 3, "damaged": 1, "under_maintenance": 0,
                                 "urgent": 1, "soon": 1}


def test_charts_use_real_data(client, admin_headers, gym):
    body = dash(client, admin_headers)
    chart = body["revenue_chart"]
    assert chart["period"] == "monthly" and len(chart["series"]) == 6
    assert chart["series"][-1]["label"] == f"{TODAY.year:04d}-{TODAY.month:02d}"
    assert money(chart["series"][-1]["amount"]) == D("1000")
    assert all(money(point["amount"]) == D("0") for point in chart["series"][:-1])

    slices = {(s["label"], s["members"]) for s in body["membership_distribution"]}
    assert slices == {("Paid plan 0", 1), ("Short 400", 1)}
    assert sum(s["members"] for s in body["membership_distribution"]) == body["memberships"]["active"]


def test_recent_activity(client, admin_headers, gym):
    body = dash(client, admin_headers)
    names = [m["full_name"] for m in body["recent_members"]]
    assert len(names) == 5 and names[0] == "Upcoming F"                        # newest first, the oldest is left out
    assert set(names) == {"Expiring B", "Expired C", "Nothing D", "Inactive E", "Upcoming F"}
    assert body["recent_members"][0]["membership_status"] == "upcoming"
    assert [v["member"]["full_name"] for v in body["recent_attendance"]] == ["Active A"]
    assert body["recent_attendance"][0]["status"] == "inside"


def test_dashboard_agrees_with_the_other_screens(client, admin_headers, gym):
    body = dash(client, admin_headers)

    def total(url):
        return client.get(url, headers=admin_headers).json()["total"]

    assert body["members"]["total"] == total("/api/members")
    for key in ("active", "upcoming", "expired", "no_membership", "inactive"):
        assert body["memberships"][key] == total(f"/api/members?status={key}"), key
    assert body["memberships"]["expiring_soon"] == total("/api/members?expiring_soon=true")

    assert body["attendance"]["inside_now"] == client.get("/api/attendance/inside", headers=admin_headers).json()["count"]
    day = client.get("/api/attendance/report?period=day", headers=admin_headers).json()
    assert body["attendance"]["visits_today"] == day["visits"]

    summary = client.get("/api/invoices/summary", headers=admin_headers).json()
    assert body["money"]["pending_count"] == summary["pending_count"]
    assert money(body["money"]["outstanding_total"]) == money(summary["outstanding_total"])

    revenue = client.get("/api/reports/revenue?period=daily", headers=admin_headers).json()
    assert money(body["money"]["collected_today"]) == money(revenue["series"][-1]["amount"])

    reminders = client.get("/api/maintenance/reminders", headers=admin_headers).json()
    assert body["equipment"]["urgent"] == reminders["urgent_count"] and body["equipment"]["soon"] == reminders["soon_count"]


def test_an_empty_gym_shows_zeros_not_errors(client, admin_headers):
    body = dash(client, admin_headers)
    assert body["members"] == {"total": 0, "active": 0, "inactive": 0, "joined_this_month": 0}
    assert set(body["memberships"].values()) == {0, 7}                          # all zero, plus alert_days = 7
    assert body["attendance"] == {"visits_today": 0, "inside_now": 0, "stale_inside": 0}
    assert money(body["money"]["collected_today"]) == D("0") and body["money"]["pending_count"] == 0
    assert body["trainers_total"] == 0 and body["equipment"]["records"] == 0
    assert body["membership_distribution"] == [] and body["recent_members"] == [] and body["recent_attendance"] == []
    assert len(body["revenue_chart"]["series"]) == 6 and money(body["revenue_chart"]["total"]) == D("0")
    assert body["unread_notifications"] == 0


def test_stale_visits_are_counted_separately(client, admin_headers, paid_member, shift_visit):
    member = paid_member()
    visit_id = client.post("/api/attendance/check-in", headers=admin_headers, json={"member_id": member["id"]}).json()["id"]
    shift_visit(visit_id, hours=9)
    attendance = dash(client, admin_headers)["attendance"]
    assert attendance["inside_now"] == 1 and attendance["stale_inside"] == 1


def test_unread_notifications_appear_on_the_dashboard(client, admin_headers, gym):
    listed = client.get("/api/notifications", headers=admin_headers).json()
    assert listed["unread_count"] > 0
    assert dash(client, admin_headers)["unread_notifications"] == listed["unread_count"]


# ================================================================ other roles
def test_receptionist_sees_money_but_no_revenue_chart(client, reception_headers, gym):
    body = dash(client, reception_headers)
    assert body["role"] == "Receptionist" and body["scope"] == "all"
    assert body["money"] is not None and body["money"]["pending_count"] == 4
    assert body["revenue_chart"] is None and body["trainers_total"] == 1
    assert body["members"]["total"] == 6 and body["equipment"]["records"] == 3


def test_trainer_sees_only_their_own_members_and_no_money(client, trainer, gym):
    body = dash(client, trainer[1])
    assert body["role"] == "Trainer" and body["scope"] == "own_members"
    assert body["members"] == {"total": 2, "active": 2, "inactive": 0, "joined_this_month": 2}
    assert body["memberships"] == {"active": 2, "expiring_soon": 1, "expired": 0, "upcoming": 0,
                                   "no_membership": 0, "inactive": 0, "alert_days": 7}
    assert body["attendance"]["visits_today"] == 1 and body["attendance"]["inside_now"] == 1
    assert body["money"] is None and body["trainers_total"] is None and body["revenue_chart"] is None
    assert body["equipment"]["records"] == 3                                    # equipment counts are shared
    assert {m["full_name"] for m in body["recent_members"]} == {"Active A", "Expiring B"}
    assert sum(s["members"] for s in body["membership_distribution"]) == 2
    assert len(body["recent_attendance"]) == 1


def test_a_trainer_with_no_members_sees_zeros(client, second_trainer, gym):
    body = dash(client, second_trainer[1])
    assert body["members"]["total"] == 0 and body["attendance"] == {"visits_today": 0, "inside_now": 0, "stale_inside": 0}
    assert body["recent_members"] == [] and body["recent_attendance"] == [] and body["membership_distribution"] == []


def test_dashboard_needs_login(client):
    assert client.get("/api/dashboard").status_code == 401
