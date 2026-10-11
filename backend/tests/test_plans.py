from decimal import Decimal


def test_admin_creates_plan(client, admin_headers):
    response = client.post("/api/plans", headers=admin_headers, json={
        "name": "Quarterly", "duration_days": 90, "price": "4000",
        "description": "3 months", "benefits": "Locker, towel"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Quarterly" and body["duration_days"] == 90
    assert Decimal(body["price"]) == Decimal("4000")
    assert body["plan_type"] == "membership" and body["is_active"] is True


def test_receptionist_can_read_but_not_change_plans(client, admin_headers, reception_headers, make_plan):
    plan = make_plan()
    assert client.get("/api/plans", headers=reception_headers).status_code == 200
    assert client.get(f"/api/plans/{plan['id']}", headers=reception_headers).status_code == 200
    assert client.post("/api/plans", headers=reception_headers,
                       json={"name": "X", "duration_days": 30, "price": "1"}).status_code == 403
    assert client.patch(f"/api/plans/{plan['id']}", headers=reception_headers,
                        json={"price": "1"}).status_code == 403
    assert client.delete(f"/api/plans/{plan['id']}", headers=reception_headers).status_code == 403


def test_trainer_cannot_read_plans(client, trainer):
    _, headers = trainer
    assert client.get("/api/plans", headers=headers).status_code == 403


def test_plans_require_login(client):
    assert client.get("/api/plans").status_code == 401


def test_duplicate_plan_name_returns_409_even_with_different_case(client, admin_headers, make_plan):
    make_plan("Monthly")
    response = client.post("/api/plans", headers=admin_headers,
                           json={"name": "MONTHLY", "duration_days": 30, "price": "1"})
    assert response.status_code == 409


def test_invalid_plan_input_returns_422(client, admin_headers):
    base = {"name": "Bad", "duration_days": 30, "price": "100"}
    for bad in ({"price": "-1"}, {"duration_days": 0}, {"name": "   "}, {"price": "abc"},
                {"plan_type": "gold"}, {"surprise": 1}):
        response = client.post("/api/plans", headers=admin_headers, json={**base, **bad})
        assert response.status_code == 422, bad


def test_update_plan_and_old_memberships_keep_their_price(client, admin_headers, make_plan, make_member):
    plan = make_plan(price="1500")
    member = make_member(plan_id=plan["id"])
    response = client.patch(f"/api/plans/{plan['id']}", headers=admin_headers, json={"price": "1800"})
    assert response.status_code == 200 and Decimal(response.json()["price"]) == Decimal("1800")
    history = client.get(f"/api/members/{member['id']}/memberships", headers=admin_headers).json()
    assert Decimal(history[0]["price_at_purchase"]) == Decimal("1500")


def test_deactivate_plan_and_filter(client, admin_headers, make_plan):
    keep = make_plan("Annual", 365, "12000")
    gone = make_plan("Old promo", 30, "999")
    response = client.delete(f"/api/plans/{gone['id']}", headers=admin_headers)
    assert response.status_code == 200 and response.json()["is_active"] is False
    active = client.get("/api/plans?active_only=true", headers=admin_headers).json()
    assert [p["id"] for p in active] == [keep["id"]]
    assert len(client.get("/api/plans", headers=admin_headers).json()) == 2


def test_plan_type_filter_and_missing_plan(client, admin_headers, make_plan):
    make_plan("Monthly")
    make_plan("Personal training", 30, "3000", plan_type="addon")
    addons = client.get("/api/plans?plan_type=addon", headers=admin_headers).json()
    assert [p["name"] for p in addons] == ["Personal training"]
    assert client.get("/api/plans/9999", headers=admin_headers).status_code == 404
