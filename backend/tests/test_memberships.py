from datetime import timedelta
from decimal import Decimal

from app.utils.dates import gym_today

TODAY = gym_today()


def iso(days_from_today):
    return (TODAY + timedelta(days=days_from_today)).isoformat()


# ---------- assigning and expiry calculation ----------
def test_assign_plan_calculates_expiry(client, admin_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1500")
    member = make_member()
    response = client.post(f"/api/members/{member['id']}/memberships", headers=admin_headers,
                           json={"plan_id": plan["id"], "start_date": iso(-10)})
    assert response.status_code == 201
    body = response.json()
    assert body["start_date"] == iso(-10)
    assert body["end_date"] == iso(-10 + 29)          # 30 days, start day included
    assert Decimal(body["price_at_purchase"]) == Decimal("1500")
    assert body["is_renewal"] is False and body["state"] == "active"


def test_start_date_defaults_to_today(client, admin_headers, make_plan, make_member):
    plan, member = make_plan("Weekly", 7, "400"), make_member()
    body = client.post(f"/api/members/{member['id']}/memberships", headers=admin_headers,
                       json={"plan_id": plan["id"]}).json()
    assert body["start_date"] == iso(0) and body["end_date"] == iso(6)


def test_register_with_plan_in_one_step(client, admin_headers, make_plan, make_member):
    plan = make_plan("Quarterly", 90, "4000")
    member = make_member(plan_id=plan["id"])
    assert member["membership_status"] == "active"
    assert member["plan_name"] == "Quarterly"
    assert member["expires_on"] == iso(89)
    assert member["days_left"] == 89
    assert member["current_membership"]["plan_id"] == plan["id"]


def test_failed_plan_assignment_does_not_leave_a_half_created_member(client, admin_headers, make_plan):
    from tests.conftest import NEW_MEMBER
    response = client.post("/api/members", headers=admin_headers, json={**NEW_MEMBER, "plan_id": 9999})
    assert response.status_code == 404
    assert client.get("/api/members", headers=admin_headers).json()["total"] == 0


def test_receptionist_can_assign_but_trainer_cannot(client, reception_headers, trainer, make_plan, make_member):
    plan, member = make_plan(), make_member()
    url = f"/api/members/{member['id']}/memberships"
    assert client.post(url, headers=reception_headers, json={"plan_id": plan["id"]}).status_code == 201
    assert client.post(url, headers=trainer[1], json={"plan_id": plan["id"]}).status_code == 403


# ---------- renewal ----------
def test_renewal_starts_the_day_after_current_membership_ends(client, admin_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1500")
    member = make_member(plan_id=plan["id"])           # today .. today+29
    renewal = client.post(f"/api/members/{member['id']}/renew", headers=admin_headers, json={})
    assert renewal.status_code == 201
    body = renewal.json()
    assert body["start_date"] == iso(30)               # no lost days
    assert body["end_date"] == iso(59)
    assert body["is_renewal"] is True and body["state"] == "upcoming"

    detail = client.get(f"/api/members/{member['id']}", headers=admin_headers).json()
    assert detail["membership_status"] == "active" and detail["expires_on"] == iso(59)


def test_renewal_after_expiry_starts_today(client, admin_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1500")
    member = make_member()
    client.post(f"/api/members/{member['id']}/memberships", headers=admin_headers,
                json={"plan_id": plan["id"], "start_date": iso(-60)})   # ended 31 days ago
    body = client.post(f"/api/members/{member['id']}/renew", headers=admin_headers, json={}).json()
    assert body["start_date"] == iso(0) and body["is_renewal"] is True


def test_renew_with_a_different_plan(client, admin_headers, make_plan, make_member):
    monthly, annual = make_plan("Monthly", 30, "1500"), make_plan("Annual", 365, "12000")
    member = make_member(plan_id=monthly["id"])
    body = client.post(f"/api/members/{member['id']}/renew", headers=admin_headers,
                       json={"plan_id": annual["id"]}).json()
    assert body["plan_name"] == "Annual" and body["end_date"] == iso(30 + 364)


def test_renew_without_history_is_rejected(client, admin_headers, make_member):
    member = make_member()
    assert client.post(f"/api/members/{member['id']}/renew", headers=admin_headers, json={}).status_code == 400


# ---------- guards ----------
def test_overlapping_period_is_rejected(client, admin_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1500")
    member = make_member(plan_id=plan["id"])
    url = f"/api/members/{member['id']}/memberships"
    assert client.post(url, headers=admin_headers, json={"plan_id": plan["id"], "start_date": iso(5)}).status_code == 409
    # a double-click sends the same request twice: the second must not create a duplicate
    assert client.post(url, headers=admin_headers, json={"plan_id": plan["id"], "start_date": iso(0)}).status_code == 409
    assert len(client.get(url, headers=admin_headers).json()) == 1


def test_start_date_limits(client, admin_headers, make_plan, make_member):
    plan, member = make_plan(), make_member()
    url = f"/api/members/{member['id']}/memberships"
    assert client.post(url, headers=admin_headers, json={"plan_id": plan["id"], "start_date": iso(-400)}).status_code == 400
    assert client.post(url, headers=admin_headers, json={"plan_id": plan["id"], "start_date": iso(400)}).status_code == 400


def test_inactive_plan_addon_and_unknown_plan_are_rejected(client, admin_headers, make_plan, make_member):
    member = make_member()
    url = f"/api/members/{member['id']}/memberships"
    old = make_plan("Old", 30, "100")
    client.delete(f"/api/plans/{old['id']}", headers=admin_headers)
    addon = make_plan("Personal training", 30, "3000", plan_type="addon")
    assert client.post(url, headers=admin_headers, json={"plan_id": old["id"]}).status_code == 400
    assert client.post(url, headers=admin_headers, json={"plan_id": addon["id"]}).status_code == 400
    assert client.post(url, headers=admin_headers, json={"plan_id": 9999}).status_code == 404


def test_inactive_member_cannot_get_a_membership(client, admin_headers, make_plan, make_member):
    plan, member = make_plan(), make_member()
    client.patch(f"/api/members/{member['id']}", headers=admin_headers, json={"status": "inactive"})
    response = client.post(f"/api/members/{member['id']}/memberships", headers=admin_headers,
                           json={"plan_id": plan["id"]})
    assert response.status_code == 400


def test_deleted_or_missing_member_gets_404(client, admin_headers, make_plan, make_member):
    plan, member = make_plan(), make_member()
    client.delete(f"/api/members/{member['id']}", headers=admin_headers)
    assert client.post(f"/api/members/{member['id']}/memberships", headers=admin_headers,
                       json={"plan_id": plan["id"]}).status_code == 404
    assert client.post("/api/members/9999/renew", headers=admin_headers, json={}).status_code == 404


# ---------- history and cancellation ----------
def test_membership_history_is_newest_first(client, admin_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1500")
    member = make_member(plan_id=plan["id"])
    client.post(f"/api/members/{member['id']}/renew", headers=admin_headers, json={})
    history = client.get(f"/api/members/{member['id']}/memberships", headers=admin_headers).json()
    assert len(history) == 2
    assert history[0]["start_date"] == iso(30) and history[1]["start_date"] == iso(0)


def test_only_admin_can_cancel_and_cancelled_is_ignored(client, admin_headers, reception_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1500")
    member = make_member(plan_id=plan["id"])
    membership_id = client.get(f"/api/members/{member['id']}/memberships", headers=admin_headers).json()[0]["id"]
    url = f"/api/members/{member['id']}/memberships/{membership_id}/cancel"

    assert client.post(url, headers=reception_headers).status_code == 403
    cancelled = client.post(url, headers=admin_headers)
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    assert client.post(url, headers=admin_headers).status_code == 400  # already cancelled
    assert client.get(f"/api/members/{member['id']}", headers=admin_headers).json()["membership_status"] == "no_membership"
    # the same dates can now be sold again
    assert client.post(f"/api/members/{member['id']}/memberships", headers=admin_headers,
                       json={"plan_id": plan["id"]}).status_code == 201
    # wrong member id in the URL
    other = make_member()
    assert client.post(f"/api/members/{other['id']}/memberships/{membership_id}/cancel",
                       headers=admin_headers).status_code == 404


# ---------- status filters (SQL must agree with the Python rules) ----------
def test_status_filters_and_expiring_soon(client, admin_headers, make_plan, make_member):
    monthly = make_plan("Monthly", 30, "1500")
    weekly = make_plan("Weekly", 7, "400")

    active = make_member(full_name="A Active", plan_id=monthly["id"])
    soon = make_member(full_name="B Soon", plan_id=weekly["id"])
    expired = make_member(full_name="C Expired")
    client.post(f"/api/members/{expired['id']}/memberships", headers=admin_headers,
                json={"plan_id": monthly["id"], "start_date": iso(-60)})
    upcoming = make_member(full_name="D Upcoming")
    client.post(f"/api/members/{upcoming['id']}/memberships", headers=admin_headers,
                json={"plan_id": monthly["id"], "start_date": iso(20)})
    none = make_member(full_name="E None")
    inactive = make_member(full_name="F Inactive", plan_id=monthly["id"])
    client.patch(f"/api/members/{inactive['id']}", headers=admin_headers, json={"status": "inactive"})

    def names(query):
        items = client.get(f"/api/members?{query}", headers=admin_headers).json()["items"]
        return [m["full_name"] for m in items]

    assert names("status=active") == ["A Active", "B Soon"]
    assert names("status=expired") == ["C Expired"]
    assert names("status=upcoming") == ["D Upcoming"]
    assert names("status=no_membership") == ["E None"]
    assert names("status=inactive") == ["F Inactive"]
    assert names("expiring_soon=true") == ["B Soon"]

    by_name = {m["full_name"]: m for m in client.get("/api/members?page_size=100", headers=admin_headers).json()["items"]}
    assert by_name["A Active"]["membership_status"] == "active" and by_name["A Active"]["expiring_soon"] is False
    assert by_name["B Soon"]["expiring_soon"] is True and by_name["B Soon"]["days_left"] == 6
    assert by_name["C Expired"]["membership_status"] == "expired" and by_name["C Expired"]["days_left"] < 0
    assert by_name["D Upcoming"]["membership_status"] == "upcoming"
    assert by_name["E None"]["membership_status"] == "no_membership"
    assert by_name["F Inactive"]["membership_status"] == "inactive"


def test_renewing_in_advance_removes_the_expiring_soon_flag(client, admin_headers, make_plan, make_member):
    weekly = make_plan("Weekly", 7, "400")
    member = make_member(plan_id=weekly["id"])
    assert client.get("/api/members?expiring_soon=true", headers=admin_headers).json()["total"] == 1
    client.post(f"/api/members/{member['id']}/renew", headers=admin_headers, json={"plan_id": make_plan("Annual", 365, "12000")["id"]})
    assert client.get("/api/members?expiring_soon=true", headers=admin_headers).json()["total"] == 0


def test_invalid_status_filter_returns_422(client, admin_headers):
    assert client.get("/api/members?status=banana", headers=admin_headers).status_code == 422
