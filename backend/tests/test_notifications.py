from collections import Counter
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.models import Notification
from app.services import notification_service
from app.utils.dates import gym_today

TODAY = gym_today()


def iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture()
def gym(client, admin_headers, trainer, make_plan, make_member, make_equipment, make_job, backdate_invoice):
    """Bella: membership ends in 4 days (her trainer is Ravi). Carl: ended 6 days ago, invoice overdue.
    One damaged machine and one machine whose maintenance is due in 3 days."""
    trainer_id, _ = trainer
    short = make_plan("Short 400", 5, "400")
    monthly = make_plan("Monthly 1000", 30, "1000")
    bella = make_member(full_name="Bella Expiring", assigned_trainer_id=trainer_id, plan_id=short["id"])
    carl = make_member(full_name="Carl Lapsed")
    carl_membership = client.post(f"/api/members/{carl['id']}/memberships", headers=admin_headers,
                                  json={"plan_id": monthly["id"], "start_date": iso(-35)}).json()
    backdate_invoice(carl_membership["invoice"]["id"], 3)
    broken = make_equipment(name="Broken Treadmill", status="damaged")
    rower = make_equipment(name="Rower")
    job = make_job(rower["id"], days=3)
    return SimpleNamespace(bella=bella, carl=carl, carl_invoice=carl_membership["invoice"]["id"], monthly=monthly,
                           broken=broken, rower=rower, job=job)


def mine(client, headers, query=""):
    response = client.get(f"/api/notifications?page_size=100&{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def kinds(body):
    return Counter(item["type"] for item in body["items"])


def refresh(client, headers):
    response = client.post("/api/notifications/refresh", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ================================================================ they appear from the real data
def test_notifications_are_created_from_memberships_payments_and_equipment(client, admin_headers, gym):
    body = mine(client, admin_headers)
    assert body["total"] == 5 and body["unread_count"] == 5
    assert kinds(body) == {"membership_expiring": 1, "membership_expired": 1, "payment_pending": 1, "maintenance_due": 2}
    assert all(item["is_read"] is False and item["created_at"].endswith("Z") for item in body["items"])

    by_type = {item["type"]: item for item in body["items"] if item["type"] != "maintenance_due"}
    expiring = by_type["membership_expiring"]
    assert expiring["related_type"] == "member" and expiring["related_id"] == gym.bella["id"]
    assert "Bella Expiring" in expiring["message"] and "Short 400" in expiring["message"]
    assert "Carl Lapsed" in by_type["membership_expired"]["message"]
    overdue = by_type["payment_pending"]
    assert overdue["related_type"] == "invoice" and overdue["related_id"] == gym.carl_invoice and "INV-" in overdue["message"]

    equipment = {item["related_type"]: item for item in body["items"] if item["type"] == "maintenance_due"}
    assert set(equipment) == {"equipment_urgent", "equipment_soon"}
    assert equipment["equipment_urgent"]["related_id"] == gym.broken["id"]
    assert "Broken Treadmill" in equipment["equipment_urgent"]["message"] and "Damaged" in equipment["equipment_urgent"]["message"]
    assert equipment["equipment_soon"]["related_id"] == gym.rower["id"]


def test_everyone_gets_their_own_copy_and_trainers_only_their_members(client, admin_headers, reception_headers, trainer, gym):
    assert mine(client, admin_headers)["total"] == 5
    assert mine(client, reception_headers)["total"] == 5
    ravi = mine(client, trainer[1])
    assert ravi["total"] == 1 and ravi["items"][0]["type"] == "membership_expiring"        # no payments, no equipment, not Carl
    assert "Bella Expiring" in ravi["items"][0]["message"]


def test_refreshing_never_creates_duplicates(client, admin_headers, gym):
    assert mine(client, admin_headers)["total"] == 5
    assert refresh(client, admin_headers) == {"skipped": False, "created": 0, "updated": 0, "removed": 0}
    assert mine(client, admin_headers)["total"] == 5
    assert mine(client, admin_headers)["total"] == 5


def test_filters_and_pages(client, admin_headers, gym):
    assert mine(client, admin_headers, "type=payment_pending")["total"] == 1
    assert mine(client, admin_headers, "type=maintenance_due")["total"] == 2
    assert mine(client, admin_headers, "type=system")["total"] == 0
    page = client.get("/api/notifications?page_size=2", headers=admin_headers).json()
    assert page["total"] == 5 and page["pages"] == 3 and len(page["items"]) == 2
    assert client.get("/api/notifications?type=banana", headers=admin_headers).status_code == 422
    assert client.get("/api/notifications?page_size=500", headers=admin_headers).status_code == 422


# ================================================================ read and unread
def test_marking_as_read_survives_refreshes(client, admin_headers, reception_headers, gym):
    items = mine(client, admin_headers)["items"]
    first = client.post(f"/api/notifications/{items[0]['id']}/read", headers=admin_headers)
    assert first.status_code == 200 and first.json()["is_read"] is True
    assert mine(client, admin_headers)["unread_count"] == 4
    refresh(client, admin_headers)
    after = mine(client, admin_headers)
    assert after["total"] == 5 and after["unread_count"] == 4                      # still read, not re-created
    assert mine(client, admin_headers, "unread_only=true")["total"] == 4
    assert mine(client, reception_headers)["unread_count"] == 5                    # the receptionist's copies are separate


def test_read_all(client, admin_headers, gym):
    mine(client, admin_headers)
    assert client.post("/api/notifications/read-all", headers=admin_headers).json() == {"marked": 5}
    assert mine(client, admin_headers)["unread_count"] == 0
    assert client.post("/api/notifications/read-all", headers=admin_headers).json() == {"marked": 0}


def test_you_cannot_touch_somebody_elses_notification(client, admin_headers, reception_headers, gym):
    theirs = mine(client, reception_headers)["items"][0]["id"]
    assert client.post(f"/api/notifications/{theirs}/read", headers=admin_headers).status_code == 404
    assert client.post("/api/notifications/9999/read", headers=admin_headers).status_code == 404
    assert mine(client, reception_headers)["unread_count"] == 5


def test_the_unread_counter_for_the_bell(client, admin_headers, trainer, gym):
    assert client.get("/api/notifications/unread-count", headers=admin_headers).json() == {"unread": 5}
    assert client.get("/api/notifications/unread-count", headers=trainer[1]).json() == {"unread": 1}
    client.post("/api/notifications/read-all", headers=admin_headers)
    assert client.get("/api/notifications/unread-count", headers=admin_headers).json() == {"unread": 0}


def test_notifications_need_login(client):
    for method, url in (("get", "/api/notifications"), ("get", "/api/notifications/unread-count"),
                        ("post", "/api/notifications/refresh"), ("post", "/api/notifications/read-all"),
                        ("post", "/api/notifications/1/read")):
        assert getattr(client, method)(url).status_code == 401, url


# ================================================================ they disappear when the cause is gone
def test_notifications_clear_themselves_when_the_problem_is_fixed(client, admin_headers, trainer, gym):
    assert kinds(mine(client, admin_headers))["membership_expiring"] == 1

    # Bella renews: no longer about to expire
    client.post(f"/api/members/{gym.bella['id']}/renew", headers=admin_headers, json={"plan_id": gym.monthly["id"]})
    assert refresh(client, admin_headers)["removed"] >= 1
    assert kinds(mine(client, admin_headers))["membership_expiring"] == 0
    assert mine(client, trainer[1])["total"] == 0

    # Carl pays what he owes: no longer overdue
    paid = client.post(f"/api/invoices/{gym.carl_invoice}/payments", headers=admin_headers,
                       json={"amount": "1000", "method": "cash"})
    assert paid.status_code == 201
    refresh(client, admin_headers)
    assert kinds(mine(client, admin_headers))["payment_pending"] == 0

    # the broken machine is repaired
    client.patch(f"/api/equipment/{gym.broken['id']}", headers=admin_headers, json={"status": "available"})
    refresh(client, admin_headers)
    remaining = mine(client, admin_headers)
    assert [i["related_type"] for i in remaining["items"] if i["type"] == "maintenance_due"] == ["equipment_soon"]


def test_deleted_and_inactive_members_stop_generating_notices(client, admin_headers, gym):
    mine(client, admin_headers)
    client.delete(f"/api/members/{gym.carl['id']}", headers=admin_headers)          # Carl: expired notice and his overdue invoice
    client.patch(f"/api/members/{gym.bella['id']}", headers=admin_headers, json={"status": "inactive"})
    refresh(client, admin_headers)
    body = mine(client, admin_headers)
    assert kinds(body) == {"maintenance_due": 2}
    client.patch(f"/api/members/{gym.bella['id']}", headers=admin_headers, json={"status": "active"})
    refresh(client, admin_headers)
    assert kinds(mine(client, admin_headers))["membership_expiring"] == 1


def test_a_worse_problem_raises_a_new_unread_notification(client, admin_headers, gym):
    body = mine(client, admin_headers)
    soon = [i for i in body["items"] if i["related_type"] == "equipment_soon"][0]
    client.post(f"/api/notifications/{soon['id']}/read", headers=admin_headers)
    assert mine(client, admin_headers)["unread_count"] == 4

    # the maintenance date for the rower is now in the past
    assert client.patch(f"/api/maintenance/{gym.job['id']}", headers=admin_headers,
                        json={"scheduled_date": iso(-2)}).status_code == 200
    refresh(client, admin_headers)
    after = mine(client, admin_headers)
    rower = [i for i in after["items"] if i["related_id"] == gym.rower["id"] and i["type"] == "maintenance_due"]
    assert [i["related_type"] for i in rower] == ["equipment_urgent"]               # the 'soon' one is gone
    assert rower[0]["is_read"] is False and "overdue" in rower[0]["message"].lower()
    assert after["unread_count"] == 5                                              # it counts as new again


def test_the_warning_windows_are_settings(client, admin_headers, gym, set_setting):
    mine(client, admin_headers)
    set_setting("expiry_alert_days", "2")                  # Bella ends in 4 days: not a warning any more
    set_setting("notification_expired_days", "3")          # Carl ended 6 days ago: too old to mention
    refresh(client, admin_headers)
    body = mine(client, admin_headers)
    assert kinds(body)["membership_expiring"] == 0 and kinds(body)["membership_expired"] == 0
    assert kinds(body)["payment_pending"] == 1


def test_a_refresh_that_ran_a_moment_ago_is_skipped(client, admin_headers, gym, monkeypatch):
    monkeypatch.setattr(notification_service, "FORCE_INTERVAL", 3600.0)
    notification_service.reset_throttle()
    assert refresh(client, admin_headers)["skipped"] is False
    client.post(f"/api/members/{gym.bella['id']}/renew", headers=admin_headers, json={"plan_id": gym.monthly["id"]})
    assert refresh(client, admin_headers) == {"skipped": True, "created": 0, "updated": 0, "removed": 0}
    notification_service.reset_throttle()
    assert refresh(client, admin_headers)["removed"] >= 1


def test_the_sync_does_not_touch_other_kinds_of_notification(client, admin_headers, gym, session_factory):
    admin_id = client.get("/api/auth/me", headers=admin_headers).json()["id"]
    with session_factory() as db:
        db.add(Notification(user_id=admin_id, type="system", title="Welcome", message="Hello", is_read=False))
        db.commit()
    refresh(client, admin_headers)
    refresh(client, admin_headers)
    body = mine(client, admin_headers, "type=system")
    assert body["total"] == 1 and body["items"][0]["title"] == "Welcome"
