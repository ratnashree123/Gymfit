import csv
import io
from datetime import timedelta
from decimal import Decimal

from app.utils.dates import gym_today

D = Decimal
TODAY = gym_today()


def money(value):
    return D(str(value))


def pay(client, headers, invoice_id, amount, method="cash", reference=None):
    body = {"amount": str(amount), "method": method}
    if reference:
        body["reference_no"] = reference
    response = client.post(f"/api/invoices/{invoice_id}/payments", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def rows_of(response):
    return list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))


# ---------- revenue report ----------
def test_daily_revenue_adds_up_and_fills_empty_days(client, admin_headers, billed_member):
    _, first = billed_member("1500")
    _, second = billed_member("1000")
    pay(client, admin_headers, first, "500", "upi", "UPI100001")
    pay(client, admin_headers, first, "250.50", "cash")
    pay(client, admin_headers, second, "1000", "card", "CARD100001")

    report = client.get("/api/reports/revenue", headers=admin_headers).json()
    assert report["period"] == "daily" and report["payment_count"] == 3
    assert money(report["total"]) == D("1750.50")
    assert {k: money(v) for k, v in report["by_method"].items()} == {
        "cash": D("250.50"), "upi": D("500"), "card": D("1000"), "bank_transfer": D("0")}

    series = report["series"]
    assert len(series) == 30                                   # last 30 days, no gaps
    assert series[-1]["label"] == TODAY.isoformat()
    assert money(series[-1]["amount"]) == D("1750.50") and series[-1]["count"] == 3
    assert all(money(point["amount"]) == D("0") for point in series[:-1])
    assert report["date_to"] == TODAY.isoformat()


def test_monthly_and_yearly_revenue(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500")
    pay(client, admin_headers, invoice_id, "600")

    monthly = client.get("/api/reports/revenue?period=monthly", headers=admin_headers).json()
    assert len(monthly["series"]) == 12
    assert monthly["series"][-1]["label"] == f"{TODAY.year:04d}-{TODAY.month:02d}"
    assert money(monthly["series"][-1]["amount"]) == D("600")

    yearly = client.get("/api/reports/revenue?period=yearly", headers=admin_headers).json()
    assert [p["label"] for p in yearly["series"]][-1] == str(TODAY.year) and len(yearly["series"]) == 5
    assert money(yearly["series"][-1]["amount"]) == D("600")


def test_revenue_with_explicit_range_and_no_payments(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500")
    pay(client, admin_headers, invoice_id, "600")
    old = client.get("/api/reports/revenue?date_from=2020-01-01&date_to=2020-01-31", headers=admin_headers).json()
    assert money(old["total"]) == D("0") and old["payment_count"] == 0 and len(old["series"]) == 31
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    future = client.get(f"/api/reports/revenue?date_from={tomorrow}&date_to={tomorrow}", headers=admin_headers).json()
    assert money(future["total"]) == D("0")


def test_revenue_input_validation(client, admin_headers):
    def get(query):
        return client.get(f"/api/reports/revenue?{query}", headers=admin_headers).status_code

    assert get("date_from=2026-03-02&date_to=2026-03-01") == 400
    assert get("period=daily&date_from=2020-01-01&date_to=2026-01-01") == 400
    assert get("period=monthly&date_from=2000-01-01&date_to=2026-01-01") == 400
    assert get("period=yearly&date_from=1990-01-01&date_to=2026-01-01") == 400
    assert get("period=weekly") == 422
    assert get("date_from=not-a-date") == 422


def test_revenue_is_admin_only(client, reception_headers, trainer):
    assert client.get("/api/reports/revenue").status_code == 401
    assert client.get("/api/reports/revenue", headers=reception_headers).status_code == 403
    assert client.get("/api/reports/revenue", headers=trainer[1]).status_code == 403


# ---------- CSV export ----------
def test_csv_export_contents(client, admin_headers, billed_member):
    member, invoice_id = billed_member("1500", full_name="Anita Sharma")
    pay(client, admin_headers, invoice_id, "500", "upi", "UPI555555")

    today = TODAY.isoformat()
    response = client.get(f"/api/payments/export.csv?date_from={today}&date_to={today}", headers=admin_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == f'attachment; filename="payments_{today}_{today}.csv"'
    assert response.headers["cache-control"] == "no-store"

    rows = rows_of(response)
    assert rows[0] == ["Receipt no", "Date (local)", "Member code", "Member name", "Invoice no",
                       "Amount", "Method", "Recording", "Reference", "Received by"]
    assert len(rows) == 2
    row = rows[1]
    assert row[0] == "RCP-000001" and row[2] == member["member_code"] and row[3] == "Anita Sharma"
    assert row[4] == "INV-000001" and money(row[5]) == D("500")
    assert row[6] == "UPI" and row[7] == "manual" and row[8] == "UPI555555" and row[9] == "Main Admin"
    assert row[1].startswith(today)                                    # local date, not UTC


def test_csv_range_filters_rows(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500")
    pay(client, admin_headers, invoice_id, "500")
    old = client.get("/api/payments/export.csv?date_from=2020-01-01&date_to=2020-12-31", headers=admin_headers)
    assert len(rows_of(old)) == 1                                      # header only


def test_csv_blocks_formula_injection(client, admin_headers, billed_member):
    _, invoice_id = billed_member("1500", full_name='=HYPERLINK("http://evil.example","click")')
    pay(client, admin_headers, invoice_id, "500", "upi", "+UPI999999")
    today = TODAY.isoformat()
    rows = rows_of(client.get(f"/api/payments/export.csv?date_from={today}&date_to={today}", headers=admin_headers))
    assert rows[1][3].startswith("'=HYPERLINK")            # shown as text, not run as a formula
    assert rows[1][8] == "'+UPI999999"


def test_csv_export_rules(client, admin_headers, reception_headers):
    today = TODAY.isoformat()
    url = f"/api/payments/export.csv?date_from={today}&date_to={today}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=reception_headers).status_code == 403
    assert client.get("/api/payments/export.csv", headers=admin_headers).status_code == 422
    assert client.get("/api/payments/export.csv?date_from=2026-03-02&date_to=2026-03-01", headers=admin_headers).status_code == 400
    assert client.get("/api/payments/export.csv?date_from=1990-01-01&date_to=2026-03-01", headers=admin_headers).status_code == 400
