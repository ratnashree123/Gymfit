import csv
import io
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.utils.dates import gym_today

TODAY = gym_today()


def iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture()
def people(client, admin_headers, make_plan, make_member):
    monthly = make_plan("Monthly", 30, "1000")
    short = make_plan("Short", 5, "400")
    annual = make_plan("Annual", 365, "9000")
    make_member(full_name="Ann Active", plan_id=monthly["id"])                       # ends in 29 days
    make_member(full_name="Bob Soon", plan_id=short["id"])                           # ends in 4 days
    cat = make_member(full_name="Cat Lapsed")
    client.post(f"/api/members/{cat['id']}/memberships", headers=admin_headers,
                json={"plan_id": monthly["id"], "start_date": iso(-60)})            # ended 31 days ago
    make_member(full_name="Dan None")
    eve = make_member(full_name="Eve Renewed", plan_id=short["id"])
    client.post(f"/api/members/{eve['id']}/renew", headers=admin_headers, json={"plan_id": annual["id"]})
    make_member(full_name="Old Timer", registration_date=iso(-40))
    return SimpleNamespace(monthly=monthly, short=short, annual=annual)


def names(client, headers, query=""):
    response = client.get(f"/api/reports/memberships?page_size=100&{query}", headers=headers)
    assert response.status_code == 200, response.text
    return [m["full_name"] for m in response.json()["items"]]


def rows_of(response):
    return list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))


def test_report_and_summary(client, admin_headers, people):
    body = client.get("/api/reports/memberships", headers=admin_headers).json()
    assert body["total"] == 6
    assert body["summary"] == {"total": 6, "active": 3, "expiring_soon": 1, "upcoming": 0, "expired": 1,
                               "no_membership": 2, "inactive": 0}
    first = body["items"][0]
    assert first["full_name"] == "Ann Active" and first["plan_name"] == "Monthly" and first["membership_status"] == "active"
    assert first["expires_on"] == iso(29) and first["days_left"] == 29


def test_filter_by_status(client, admin_headers, people):
    assert names(client, admin_headers, "status=expired") == ["Cat Lapsed"]
    assert names(client, admin_headers, "status=no_membership") == ["Dan None", "Old Timer"]
    assert names(client, admin_headers, "status=active") == ["Ann Active", "Bob Soon", "Eve Renewed"]
    assert names(client, admin_headers, "status=upcoming") == []


def test_filter_by_plan_uses_the_latest_membership(client, admin_headers, people):
    assert names(client, admin_headers, f"plan_id={people.short['id']}") == ["Bob Soon"]            # Eve moved to Annual
    assert names(client, admin_headers, f"plan_id={people.annual['id']}") == ["Eve Renewed"]
    assert names(client, admin_headers, f"plan_id={people.monthly['id']}") == ["Ann Active", "Cat Lapsed"]
    assert names(client, admin_headers, f"status=active&plan_id={people.monthly['id']}") == ["Ann Active"]
    assert names(client, admin_headers, "plan_id=9999") == []


def test_filter_by_expiry_and_join_dates(client, admin_headers, people):
    assert names(client, admin_headers, f"expires_from={iso(0)}&expires_to={iso(10)}") == ["Bob Soon"]
    assert names(client, admin_headers, f"expires_to={iso(-1)}") == ["Cat Lapsed"]
    assert names(client, admin_headers, f"expires_from={iso(100)}") == ["Eve Renewed"]             # members without any membership drop out
    assert names(client, admin_headers, f"joined_to={iso(-30)}") == ["Old Timer"]
    assert names(client, admin_headers, f"joined_from={iso(-10)}") == [
        "Ann Active", "Bob Soon", "Cat Lapsed", "Dan None", "Eve Renewed"]
    assert names(client, admin_headers, f"joined_from={iso(-50)}&joined_to={iso(-30)}") == ["Old Timer"]


def test_search_sort_and_pages(client, admin_headers, people):
    assert names(client, admin_headers, "search=eve") == ["Eve Renewed"]
    assert names(client, admin_headers, "sort_by=registration_date&order=asc")[0] == "Old Timer"
    assert names(client, admin_headers, "order=desc")[0] == "Old Timer"
    page = client.get("/api/reports/memberships?page=2&page_size=2", headers=admin_headers).json()
    assert page["total"] == 6 and page["pages"] == 3 and len(page["items"]) == 2
    # the summary always describes the whole gym, whatever the filters
    filtered = client.get("/api/reports/memberships?status=expired", headers=admin_headers).json()
    assert filtered["total"] == 1 and filtered["summary"]["total"] == 6


def test_report_validation(client, admin_headers, people):
    for bad in (f"expires_from={iso(5)}&expires_to={iso(1)}", f"joined_from={iso(5)}&joined_to={iso(1)}"):
        assert client.get(f"/api/reports/memberships?{bad}", headers=admin_headers).status_code == 400
        assert client.get(f"/api/reports/memberships/export.csv?{bad}", headers=admin_headers).status_code == 400
    for bad in ("status=banana", "sort_by=banana", "order=sideways", "page=0", "page_size=500", "plan_id=abc",
                "expires_from=tomorrow"):
        assert client.get(f"/api/reports/memberships?{bad}", headers=admin_headers).status_code == 422, bad


def test_who_can_open_the_report(client, admin_headers, reception_headers, trainer, people):
    assert client.get("/api/reports/memberships", headers=reception_headers).status_code == 200
    assert client.get("/api/reports/memberships", headers=trainer[1]).status_code == 403
    assert client.get("/api/reports/memberships").status_code == 401


def test_csv_export(client, admin_headers, people):
    response = client.get("/api/reports/memberships/export.csv", headers=admin_headers)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="memberships.csv"'
    assert response.headers["cache-control"] == "no-store"
    rows = rows_of(response)
    assert rows[0] == ["Member code", "Name", "Phone", "Email", "Registered", "Member status", "Membership status",
                       "Plan", "Expires on", "Days left", "Trainer"]
    assert len(rows) == 7
    ann = [r for r in rows if r[1] == "Ann Active"][0]
    assert ann[0].startswith("GF-") and ann[4] == iso(0) and ann[5] == "active" and ann[6] == "active"
    assert ann[7] == "Monthly" and ann[8] == iso(29) and ann[9] == "29"
    dan = [r for r in rows if r[1] == "Dan None"][0]
    assert dan[6] == "no_membership" and dan[7] == "" and dan[8] == "" and dan[9] == ""


def test_csv_uses_the_same_filters_and_blocks_formula_injection(client, admin_headers, make_member, people):
    make_member(full_name="=1+1", plan_id=people.monthly["id"])
    expired = rows_of(client.get("/api/reports/memberships/export.csv?status=expired", headers=admin_headers))
    assert [r[1] for r in expired[1:]] == ["Cat Lapsed"]
    everyone = rows_of(client.get("/api/reports/memberships/export.csv", headers=admin_headers))
    assert "'=1+1" in [r[1] for r in everyone]


def test_csv_is_admin_only(client, reception_headers, trainer, people):
    assert client.get("/api/reports/memberships/export.csv").status_code == 401
    assert client.get("/api/reports/memberships/export.csv", headers=reception_headers).status_code == 403
    assert client.get("/api/reports/memberships/export.csv", headers=trainer[1]).status_code == 403
