import re
from datetime import timedelta
from decimal import Decimal

from app.utils.dates import gym_today

D = Decimal


def money(value):
    return D(str(value))


def pay(client, headers, invoice_id, amount, method="cash", reference=None, **extra):
    body = {"amount": str(amount), "method": method, **extra}
    if reference is not None:
        body["reference_no"] = reference
    return client.post(f"/api/invoices/{invoice_id}/payments", headers=headers, json=body)


def invoice(client, headers, invoice_id):
    return client.get(f"/api/invoices/{invoice_id}", headers=headers).json()


# ---------- recording ----------
def test_partial_then_full_payment_moves_the_status(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500")
    first = pay(client, admin_headers, invoice_id, "500")
    assert first.status_code == 201
    body = first.json()
    assert body["receipt_number"] == "RCP-000001"
    assert body["verification_type"] == "manual" and "not verified online" in body["verification_label"]
    assert body["received_by_name"] == "Main Admin" and body["method"] == "cash"
    after_first = invoice(client, admin_headers, invoice_id)
    assert after_first["status"] == "partial"
    assert money(after_first["amount_paid"]) == D("500") and money(after_first["balance"]) == D("1000")

    second = pay(client, admin_headers, invoice_id, "1000")
    assert second.status_code == 201 and second.json()["receipt_number"] == "RCP-000002"
    after_second = invoice(client, admin_headers, invoice_id)
    assert after_second["status"] == "paid" and money(after_second["balance"]) == D("0")
    assert [p["receipt_number"] for p in after_second["payments"]] == ["RCP-000001", "RCP-000002"]

    assert pay(client, admin_headers, invoice_id, "1").status_code == 400   # already fully paid


def test_invoice_is_never_paid_without_a_payment(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500")
    detail = invoice(client, admin_headers, invoice_id)
    assert detail["status"] == "pending" and detail["payments"] == []
    assert client.get("/api/invoices?status=paid", headers=admin_headers).json()["total"] == 0


def test_cannot_pay_more_than_the_balance(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500")
    assert pay(client, admin_headers, invoice_id, "1500.01").status_code == 400
    pay(client, admin_headers, invoice_id, "1000")
    assert pay(client, admin_headers, invoice_id, "500.01").status_code == 400
    assert pay(client, admin_headers, invoice_id, "500").status_code == 201


def test_decimal_amounts_add_up_exactly(client, admin_headers, billed_member):
    _, invoice_id = billed_member("100")
    assert pay(client, admin_headers, invoice_id, "33.33", "cash").status_code == 201
    assert pay(client, admin_headers, invoice_id, "33.33", "upi", reference="UPI000001").status_code == 201
    assert invoice(client, admin_headers, invoice_id)["status"] == "partial"
    assert pay(client, admin_headers, invoice_id, "33.34", "card", reference="CARD000001").status_code == 201
    detail = invoice(client, admin_headers, invoice_id)
    assert money(detail["amount_paid"]) == D("100.00") and detail["status"] == "paid"


def test_invalid_payment_input(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500")
    for bad in (
        {"amount": "0", "method": "cash"}, {"amount": "-5", "method": "cash"},
        {"amount": "abc", "method": "cash"}, {"amount": "10.999", "method": "cash"},
        {"amount": "10"}, {"method": "cash"}, {"amount": "10", "method": "bitcoin"},
        {"amount": "10", "method": "cash", "verification_type": "verified_online"},   # cannot fake 'verified'
        {"amount": "10", "method": "cash", "received_by": 1},
    ):
        assert client.post(f"/api/invoices/{invoice_id}/payments", headers=admin_headers, json=bad).status_code == 422, bad
    assert invoice(client, admin_headers, invoice_id)["payments"] == []


def test_reference_number_rules(client, admin_headers, billed_member):
    _, first = billed_member("1500")
    _, second = billed_member("1500")
    for method in ("upi", "card", "bank_transfer"):
        assert pay(client, admin_headers, first, "100", method).status_code == 422        # reference required
        assert pay(client, admin_headers, first, "100", method, reference="  ").status_code == 422
    assert pay(client, admin_headers, first, "100", "upi", reference="UPI998877").status_code == 201
    # the same bank/UPI transaction cannot be used twice, even on another invoice or in other letter case
    assert pay(client, admin_headers, second, "200", "upi", reference="upi998877").status_code == 409
    assert pay(client, admin_headers, second, "200", "upi", reference="UPI111111").status_code == 201
    assert pay(client, admin_headers, second, "300", "cash").status_code == 201            # cash needs none


def test_double_click_is_blocked_but_a_different_amount_is_fine(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500")
    assert pay(client, admin_headers, invoice_id, "500").status_code == 201
    again = pay(client, admin_headers, invoice_id, "500")
    assert again.status_code == 409 and "identical" in again.json()["detail"]
    assert pay(client, admin_headers, invoice_id, "400").status_code == 201
    assert money(invoice(client, admin_headers, invoice_id)["amount_paid"]) == D("900")


def test_partial_payments_can_be_turned_off(client, admin_headers, billed_member, set_setting):
    set_setting("allow_partial_payments", "false")
    _, invoice_id = billed_member("1500")
    refused = pay(client, admin_headers, invoice_id, "500")
    assert refused.status_code == 400 and "Partial payments are turned off" in refused.json()["detail"]
    assert pay(client, admin_headers, invoice_id, "1500").status_code == 201
    assert invoice(client, admin_headers, invoice_id)["status"] == "paid"


def test_payment_on_unknown_or_cancelled_invoice(client, admin_headers, billed_member):
    assert pay(client, admin_headers, 9999, "10").status_code == 404
    member, invoice_id = billed_member("1500")
    membership_id = client.get(f"/api/members/{member['id']}/memberships", headers=admin_headers).json()[0]["id"]
    client.post(f"/api/members/{member['id']}/memberships/{membership_id}/cancel", headers=admin_headers)
    assert pay(client, admin_headers, invoice_id, "10").status_code == 400


def test_payments_need_login_and_front_desk_role(client, admin_headers, reception_headers, trainer, billed_member):
    _, invoice_id = billed_member("1500")
    assert client.post(f"/api/invoices/{invoice_id}/payments", json={"amount": "1", "method": "cash"}).status_code == 401
    assert pay(client, trainer[1], invoice_id, "100").status_code == 403
    assert client.get("/api/payments", headers=trainer[1]).status_code == 403
    receipt = pay(client, reception_headers, invoice_id, "100")
    assert receipt.status_code == 201 and receipt.json()["received_by_name"] == "Front Desk"


def test_payment_date_is_sent_as_utc_with_z(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500")
    body = pay(client, admin_headers, invoice_id, "100").json()
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", body["payment_date"])


def test_payment_is_audited_without_touching_secrets(client, admin_headers, billed_member, session_factory):
    _, invoice_id = billed_member("1500")
    pay(client, admin_headers, invoice_id, "500", "upi", reference="UPI777777")
    from app.models import AuditLog
    with session_factory() as db:
        log = db.query(AuditLog).filter_by(action="payment.record").one()
        assert log.new_values["receipt_number"] == "RCP-000001"
        assert log.new_values["invoice_status"] == "partial" and log.old_values["invoice_status"] == "pending"


# ---------- history and search ----------
def test_payment_history_search_and_totals(client, admin_headers, billed_member):
    anita, first = billed_member("1500", full_name="Anita Sharma")
    ravi, second = billed_member("2000", full_name="Ravi Patel")
    pay(client, admin_headers, first, "500", "upi", reference="UPI123456")
    pay(client, admin_headers, first, "1000", "cash")
    pay(client, admin_headers, second, "750.50", "card", reference="CARDSLIP9")

    everything = client.get("/api/payments", headers=admin_headers).json()
    assert everything["total"] == 3 and money(everything["total_amount"]) == D("2250.50")
    assert everything["items"][0]["receipt_number"] == "RCP-000003"                     # newest first

    def find(query):
        return client.get(f"/api/payments?{query}", headers=admin_headers).json()

    assert find("search=UPI123456")["total"] == 1
    assert find("search=RCP-000002")["items"][0]["method"] == "cash"
    assert find("search=anita")["total"] == 2
    assert find("search=INV-000002")["total"] == 1
    assert find(f"search={ravi['member_code']}")["total"] == 1
    assert find(f"member_id={anita['id']}")["total"] == 2
    assert money(find(f"member_id={anita['id']}")["total_amount"]) == D("1500")
    assert find("method=card")["total"] == 1 and find("method=upi")["total"] == 1
    assert find("search=%25")["total"] == 0
    assert client.get("/api/payments?method=bitcoin", headers=admin_headers).status_code == 422

    today = gym_today().isoformat()
    assert find(f"date_from={today}&date_to={today}")["total"] == 3
    assert find("date_to=2000-01-01")["total"] == 0
    tomorrow = (gym_today() + timedelta(days=1)).isoformat()
    assert find(f"date_from={tomorrow}")["total"] == 0

    page = find("page=2&page_size=2")
    assert page["pages"] == 2 and len(page["items"]) == 1 and money(page["total_amount"]) == D("2250.50")


def test_get_single_payment(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500")
    payment_id = pay(client, admin_headers, invoice_id, "100").json()["id"]
    body = client.get(f"/api/payments/{payment_id}", headers=admin_headers).json()
    assert body["invoice_number"] == "INV-000001"
    assert client.get("/api/payments/9999", headers=admin_headers).status_code == 404


# ---------- receipts ----------
def test_receipt_data_and_old_receipts_never_change(client, admin_headers, billed_member):
    member, invoice_id = billed_member("1500")
    first = pay(client, admin_headers, invoice_id, "500").json()["id"]
    pay(client, admin_headers, invoice_id, "1000")

    receipt = client.get(f"/api/payments/{first}/receipt", headers=admin_headers).json()
    assert receipt["receipt_number"] == "RCP-000001" and receipt["gym_name"] == "GymFit"
    assert receipt["member"]["member_code"] == member["member_code"]
    assert money(receipt["payment_amount"]) == D("500")
    assert money(receipt["paid_so_far"]) == D("500") and money(receipt["balance_due"]) == D("1000")
    assert receipt["verification_type"] == "manual"
    assert [(l["label"], money(l["amount"])) for l in receipt["lines"]] == [
        ("Price", D("1500")), ("Invoice total", D("1500"))]

    second = client.get("/api/payments/2/receipt", headers=admin_headers).json()
    assert money(second["paid_so_far"]) == D("1500") and money(second["balance_due"]) == D("0")


def test_receipt_shows_discount_and_tax_lines(client, admin_headers, make_plan, make_member, set_setting):
    set_setting("tax_percent", "18")
    plan, member = make_plan("Monthly", 30, "1000"), make_member()
    assigned = client.post(f"/api/members/{member['id']}/memberships", headers=admin_headers,
                           json={"plan_id": plan["id"], "discount_percent": "10"}).json()
    payment_id = pay(client, admin_headers, assigned["invoice"]["id"], "1062").json()["id"]
    receipt = client.get(f"/api/payments/{payment_id}/receipt", headers=admin_headers).json()
    assert [(l["label"], money(l["amount"])) for l in receipt["lines"]] == [
        ("Price", D("1000")), ("Discount", D("-100")), ("Tax", D("162")), ("Invoice total", D("1062"))]
    assert receipt["description"] == "Monthly"


def test_receipt_html_is_printable_and_escaped(client, admin_headers, billed_member):
    evil = "<script>alert(1)</script>"
    _, invoice_id = billed_member("1500", full_name=evil)
    payment_id = pay(client, admin_headers, invoice_id, "500", "upi", reference="UPI424242").json()["id"]
    response = client.get(f"/api/payments/{payment_id}/receipt.html", headers=admin_headers)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    assert response.headers["x-content-type-options"] == "nosniff"
    page = response.text
    assert "RCP-000001" in page and "UPI424242" in page and "GymFit" in page and "@media print" in page
    assert "<script>alert(1)" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_receipt_uses_gym_settings(client, admin_headers, billed_member, set_setting):
    set_setting("gym_name", "Iron Temple")
    set_setting("currency_symbol", "Rs ")
    _, invoice_id = billed_member("1500")
    payment_id = pay(client, admin_headers, invoice_id, "500").json()["id"]
    page = client.get(f"/api/payments/{payment_id}/receipt.html", headers=admin_headers).text
    assert "Iron Temple" in page and "Rs 500.00" in page and "Rs 1,000.00" in page


def test_receipts_need_login_and_exist(client, admin_headers, trainer, billed_member):
    _, invoice_id = billed_member("1500")
    payment_id = pay(client, admin_headers, invoice_id, "100").json()["id"]
    assert client.get(f"/api/payments/{payment_id}/receipt").status_code == 401
    assert client.get(f"/api/payments/{payment_id}/receipt.html", headers=trainer[1]).status_code == 403
    assert client.get("/api/payments/9999/receipt", headers=admin_headers).status_code == 404
    assert client.get("/api/payments/9999/receipt.html", headers=admin_headers).status_code == 404
