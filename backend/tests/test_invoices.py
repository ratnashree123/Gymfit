from datetime import timedelta
from decimal import Decimal

from app.utils.dates import gym_today

D = Decimal


def money(value):
    return D(str(value))


def assign(client, headers, member_id, plan_id, **extra):
    return client.post(f"/api/members/{member_id}/memberships", headers=headers,
                       json={"plan_id": plan_id, **extra})


# ---------- automatic invoices ----------
def test_assigning_a_plan_creates_a_pending_invoice(client, admin_headers, make_plan, make_member):
    plan, member = make_plan("Monthly", 30, "1500"), make_member()
    response = assign(client, admin_headers, member["id"], plan["id"])
    assert response.status_code == 201
    invoice = response.json()["invoice"]
    assert invoice["invoice_number"] == "INV-000001"
    assert invoice["invoice_type"] == "membership"
    assert invoice["status"] == "pending"                      # never 'paid' without a payment
    assert money(invoice["total_amount"]) == D("1500")
    assert money(invoice["amount_paid"]) == D("0") and money(invoice["balance"]) == D("1500")
    assert invoice["is_overdue"] is False
    assert invoice["due_date"] == (gym_today() + timedelta(days=7)).isoformat()


def test_renewal_creates_a_renewal_invoice(client, admin_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1500")
    member = make_member(plan_id=plan["id"])
    renewal = client.post(f"/api/members/{member['id']}/renew", headers=admin_headers, json={}).json()
    assert renewal["invoice"]["invoice_type"] == "renewal"
    assert renewal["invoice"]["invoice_number"] == "INV-000002"


def test_registering_with_a_plan_creates_the_invoice_too(client, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1500")
    member = make_member(plan_id=plan["id"])
    invoice = member["current_membership"]["invoice"]
    assert invoice["status"] == "pending" and money(invoice["total_amount"]) == D("1500")


def test_membership_history_shows_each_invoice(client, admin_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1500")
    member = make_member(plan_id=plan["id"])
    client.post(f"/api/members/{member['id']}/renew", headers=admin_headers, json={})
    history = client.get(f"/api/members/{member['id']}/memberships", headers=admin_headers).json()
    assert [h["invoice"]["invoice_number"] for h in history] == ["INV-000002", "INV-000001"]


def test_free_plan_creates_no_invoice(client, admin_headers, make_plan, make_member):
    plan, member = make_plan("Free trial", 7, "0"), make_member()
    response = assign(client, admin_headers, member["id"], plan["id"])
    assert response.status_code == 201 and response.json()["invoice"] is None
    assert client.get("/api/invoices", headers=admin_headers).json()["total"] == 0


# ---------- discount and tax ----------
def test_tax_from_settings_and_percent_discount(client, admin_headers, make_plan, make_member, set_setting):
    set_setting("tax_percent", "18")
    plan, member = make_plan("Monthly", 30, "1000"), make_member()
    response = assign(client, admin_headers, member["id"], plan["id"], discount_percent="10")
    invoice_id = response.json()["invoice"]["id"]
    detail = client.get(f"/api/invoices/{invoice_id}", headers=admin_headers).json()
    assert money(detail["subtotal"]) == D("1000")
    assert money(detail["discount_amount"]) == D("100")
    assert money(detail["tax_amount"]) == D("162")        # 18% of the discounted 900
    assert money(detail["total_amount"]) == D("1062")


def test_fixed_discount(client, admin_headers, make_plan, make_member):
    plan, member = make_plan("Monthly", 30, "1500"), make_member()
    response = assign(client, admin_headers, member["id"], plan["id"], discount_amount="250.50")
    assert money(response.json()["invoice"]["total_amount"]) == D("1249.50")


def test_bad_discounts_are_rejected(client, admin_headers, make_plan, make_member):
    plan, member = make_plan("Monthly", 30, "1500"), make_member()
    url = f"/api/members/{member['id']}/memberships"
    assert client.post(url, headers=admin_headers, json={
        "plan_id": plan["id"], "discount_percent": "10", "discount_amount": "50"}).status_code == 422
    assert client.post(url, headers=admin_headers, json={"plan_id": plan["id"], "discount_percent": "101"}).status_code == 422
    assert client.post(url, headers=admin_headers, json={"plan_id": plan["id"], "discount_amount": "-1"}).status_code == 422
    assert client.post(url, headers=admin_headers, json={"plan_id": plan["id"], "discount_amount": "2000"}).status_code == 400
    # nothing was created by the failed attempts
    assert client.get(f"/api/members/{member['id']}/memberships", headers=admin_headers).json() == []
    assert client.get("/api/invoices", headers=admin_headers).json()["total"] == 0


def test_receptionist_discount_is_capped_but_admin_is_not(client, admin_headers, reception_headers, make_plan, make_member):
    plan = make_plan("Monthly", 30, "1000")
    first, second, third = make_member(), make_member(), make_member()
    ok = assign(client, reception_headers, first["id"], plan["id"], discount_percent="10")
    assert ok.status_code == 201 and money(ok.json()["invoice"]["total_amount"]) == D("900")
    too_much = assign(client, reception_headers, second["id"], plan["id"], discount_percent="11")
    assert too_much.status_code == 403
    assert client.get(f"/api/members/{second['id']}/memberships", headers=admin_headers).json() == []
    assert assign(client, admin_headers, third["id"], plan["id"], discount_percent="50").status_code == 201


def test_discount_cap_can_be_changed_in_settings(client, reception_headers, make_plan, make_member, set_setting):
    set_setting("max_receptionist_discount_percent", "25")
    plan, member = make_plan("Monthly", 30, "1000"), make_member()
    assert assign(client, reception_headers, member["id"], plan["id"], discount_percent="20").status_code == 201


def test_registration_with_too_big_discount_leaves_no_half_created_member(client, reception_headers, admin_headers, make_plan):
    from tests.conftest import NEW_MEMBER
    plan = make_plan("Monthly", 30, "1000")
    response = client.post("/api/members", headers=reception_headers,
                           json={**NEW_MEMBER, "plan_id": plan["id"], "discount_percent": "30"})
    assert response.status_code == 403
    assert client.get("/api/members", headers=admin_headers).json()["total"] == 0


def test_discount_without_plan_is_rejected_at_registration(client, admin_headers):
    from tests.conftest import NEW_MEMBER
    response = client.post("/api/members", headers=admin_headers, json={**NEW_MEMBER, "discount_percent": "5"})
    assert response.status_code == 422


# ---------- listing, search, filters ----------
def test_invoice_list_search_filters_and_pages(client, admin_headers, billed_member):
    anita, anita_invoice = billed_member("1500", full_name="Anita Sharma")
    ravi, ravi_invoice = billed_member("2000", full_name="Ravi Patel")

    everything = client.get("/api/invoices", headers=admin_headers).json()
    assert everything["total"] == 2
    assert everything["items"][0]["id"] == ravi_invoice            # newest first
    assert everything["items"][0]["member"]["full_name"] == "Ravi Patel"

    assert client.get(f"/api/invoices?member_id={anita['id']}", headers=admin_headers).json()["total"] == 1
    assert client.get("/api/invoices?search=anita", headers=admin_headers).json()["total"] == 1
    assert client.get("/api/invoices?search=INV-000002", headers=admin_headers).json()["items"][0]["id"] == ravi_invoice
    assert client.get(f"/api/invoices?search={anita['member_code']}", headers=admin_headers).json()["total"] == 1
    assert client.get("/api/invoices?search=%25", headers=admin_headers).json()["total"] == 0
    assert client.get("/api/invoices?status=pending", headers=admin_headers).json()["total"] == 2
    assert client.get("/api/invoices?status=paid", headers=admin_headers).json()["total"] == 0
    page = client.get("/api/invoices?page=2&page_size=1", headers=admin_headers).json()
    assert page["pages"] == 2 and page["items"][0]["id"] == anita_invoice
    assert client.get("/api/invoices?status=banana", headers=admin_headers).status_code == 422
    today = gym_today().isoformat()
    assert client.get(f"/api/invoices?date_from={today}&date_to={today}", headers=admin_headers).json()["total"] == 2
    assert client.get("/api/invoices?date_to=2000-01-01", headers=admin_headers).json()["total"] == 0


def test_overdue_filter_and_flag(client, admin_headers, billed_member, backdate_invoice):
    _, late = billed_member("1500")
    _, on_time = billed_member("1500")
    backdate_invoice(late, 3)
    overdue = client.get("/api/invoices?overdue=true", headers=admin_headers).json()
    assert [i["id"] for i in overdue["items"]] == [late]
    assert overdue["items"][0]["is_overdue"] is True
    assert client.get(f"/api/invoices/{on_time}", headers=admin_headers).json()["is_overdue"] is False


def test_paid_invoice_is_no_longer_overdue(client, admin_headers, billed_member, backdate_invoice):
    _, invoice_id = billed_member("1500")
    backdate_invoice(invoice_id, 3)
    client.post(f"/api/invoices/{invoice_id}/payments", headers=admin_headers, json={"amount": "1500", "method": "cash"})
    assert client.get("/api/invoices?overdue=true", headers=admin_headers).json()["total"] == 0


def test_invoice_summary(client, admin_headers, billed_member, backdate_invoice):
    _, first = billed_member("1500")
    _, second = billed_member("1000")
    client.post(f"/api/invoices/{first}/payments", headers=admin_headers, json={"amount": "500", "method": "cash"})
    summary = client.get("/api/invoices/summary", headers=admin_headers).json()
    assert summary["pending_count"] == 2 and money(summary["outstanding_total"]) == D("2000")
    assert summary["overdue_count"] == 0 and money(summary["overdue_total"]) == D("0")
    backdate_invoice(first, 5)
    summary = client.get("/api/invoices/summary", headers=admin_headers).json()
    assert summary["overdue_count"] == 1 and money(summary["overdue_total"]) == D("1000")
    assert second


def test_invoice_summary_for_one_member(client, admin_headers, billed_member):
    anita, _ = billed_member("1500")
    billed_member("1000")
    summary = client.get(f"/api/invoices/summary?member_id={anita['id']}", headers=admin_headers).json()
    assert summary["pending_count"] == 1 and money(summary["outstanding_total"]) == D("1500")


def test_invoice_detail_and_404(client, admin_headers, billed_member):
    member, invoice_id = billed_member("1500")
    detail = client.get(f"/api/invoices/{invoice_id}", headers=admin_headers).json()
    assert detail["member"]["id"] == member["id"] and detail["payments"] == []
    assert detail["plan_name"].startswith("Plan") and detail["membership_id"] is not None
    assert client.get("/api/invoices/9999", headers=admin_headers).status_code == 404


# ---------- personal training and other one-off bills ----------
def test_personal_training_invoice_from_an_addon_plan(client, admin_headers, make_plan, make_member):
    addon = make_plan("Personal training", 30, "3000", plan_type="addon")
    member = make_member()
    response = client.post("/api/invoices", headers=admin_headers, json={
        "member_id": member["id"], "invoice_type": "personal_training", "plan_id": addon["id"]})
    assert response.status_code == 201
    body = response.json()
    assert body["invoice_type"] == "personal_training" and body["membership_id"] is None
    assert money(body["total_amount"]) == D("3000") and body["status"] == "pending"
    assert body["notes"] == "Personal training"


def test_one_off_invoice_with_a_typed_amount_and_due_date(client, reception_headers, make_member):
    member = make_member()
    due = (gym_today() + timedelta(days=30)).isoformat()
    response = client.post("/api/invoices", headers=reception_headers, json={
        "member_id": member["id"], "invoice_type": "other", "amount": "250.75",
        "notes": "Locker key deposit", "due_date": due})
    assert response.status_code == 201
    assert money(response.json()["total_amount"]) == D("250.75")
    assert response.json()["due_date"] == due


def test_one_off_invoice_validation(client, admin_headers, make_plan, make_member):
    member, monthly = make_member(), make_plan("Monthly", 30, "1500")
    old_addon = make_plan("Old addon", 30, "100", plan_type="addon")
    client.delete(f"/api/plans/{old_addon['id']}", headers=admin_headers)
    base = {"member_id": member["id"], "invoice_type": "other"}

    assert client.post("/api/invoices", headers=admin_headers, json=base).status_code == 422                       # no price
    assert client.post("/api/invoices", headers=admin_headers, json={**base, "amount": "5", "plan_id": 1}).status_code == 422
    assert client.post("/api/invoices", headers=admin_headers, json={**base, "amount": "0"}).status_code == 422
    assert client.post("/api/invoices", headers=admin_headers, json={**base, "amount": "-5"}).status_code == 422
    assert client.post("/api/invoices", headers=admin_headers, json={**base, "invoice_type": "membership", "amount": "5"}).status_code == 422
    assert client.post("/api/invoices", headers=admin_headers, json={**base, "plan_id": monthly["id"]}).status_code == 400
    assert client.post("/api/invoices", headers=admin_headers, json={**base, "plan_id": old_addon["id"]}).status_code == 400
    assert client.post("/api/invoices", headers=admin_headers, json={**base, "plan_id": 9999}).status_code == 404
    assert client.post("/api/invoices", headers=admin_headers, json={**base, "member_id": 9999, "amount": "5"}).status_code == 404
    assert client.post("/api/invoices", headers=admin_headers, json={**base, "amount": "100", "discount_percent": "100"}).status_code == 400
    assert client.get("/api/invoices", headers=admin_headers).json()["total"] == 0


def test_cancel_one_off_invoice_rules(client, admin_headers, reception_headers, make_member, billed_member):
    member = make_member()
    created = client.post("/api/invoices", headers=admin_headers, json={
        "member_id": member["id"], "invoice_type": "other", "amount": "100"}).json()
    url = f"/api/invoices/{created['id']}/cancel"

    assert client.post(url, headers=reception_headers).status_code == 403
    cancelled = client.post(url, headers=admin_headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client.post(url, headers=admin_headers).status_code == 400
    blocked = client.post(f"/api/invoices/{created['id']}/payments", headers=admin_headers,
                          json={"amount": "100", "method": "cash"})
    assert blocked.status_code == 400

    _, membership_invoice = billed_member("1500")
    assert client.post(f"/api/invoices/{membership_invoice}/cancel", headers=admin_headers).status_code == 400

    paid = client.post("/api/invoices", headers=admin_headers, json={
        "member_id": member["id"], "invoice_type": "other", "amount": "100"}).json()
    client.post(f"/api/invoices/{paid['id']}/payments", headers=admin_headers, json={"amount": "40", "method": "cash"})
    assert client.post(f"/api/invoices/{paid['id']}/cancel", headers=admin_headers).status_code == 400
    assert client.post("/api/invoices/9999/cancel", headers=admin_headers).status_code == 404


# ---------- membership cancellation and money ----------
def test_cancelling_a_membership_cancels_its_unpaid_invoice(client, admin_headers, billed_member):
    member, invoice_id = billed_member("1500")
    membership_id = client.get(f"/api/members/{member['id']}/memberships", headers=admin_headers).json()[0]["id"]
    assert client.post(f"/api/members/{member['id']}/memberships/{membership_id}/cancel",
                       headers=admin_headers).status_code == 200
    assert client.get(f"/api/invoices/{invoice_id}", headers=admin_headers).json()["status"] == "cancelled"
    assert client.get("/api/invoices/summary", headers=admin_headers).json()["pending_count"] == 0


def test_membership_with_payments_cannot_be_cancelled(client, admin_headers, billed_member):
    member, invoice_id = billed_member("1500")
    client.post(f"/api/invoices/{invoice_id}/payments", headers=admin_headers, json={"amount": "500", "method": "cash"})
    membership_id = client.get(f"/api/members/{member['id']}/memberships", headers=admin_headers).json()[0]["id"]
    response = client.post(f"/api/members/{member['id']}/memberships/{membership_id}/cancel", headers=admin_headers)
    assert response.status_code == 400 and "refund" in response.json()["detail"].lower()
    assert client.get(f"/api/members/{member['id']}", headers=admin_headers).json()["membership_status"] == "active"


# ---------- access ----------
def test_invoices_need_login_and_front_desk_role(client, trainer):
    assert client.get("/api/invoices").status_code == 401
    assert client.get("/api/invoices", headers=trainer[1]).status_code == 403
    assert client.get("/api/invoices/summary", headers=trainer[1]).status_code == 403
    assert client.post("/api/invoices", headers=trainer[1], json={"member_id": 1, "invoice_type": "other", "amount": "5"}).status_code == 403


def test_invoice_creation_is_audited(client, admin_headers, billed_member, session_factory):
    billed_member("1500")
    from app.models import AuditLog
    with session_factory() as db:
        actions = [log.action for log in db.query(AuditLog).all()]
    assert "invoice.create" in actions and "membership.create" in actions
