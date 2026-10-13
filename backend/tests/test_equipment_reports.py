import csv
import io
from datetime import timedelta
from decimal import Decimal

from app.utils.dates import gym_today

TODAY = gym_today()
D = Decimal


def iso(days):
    return (TODAY + timedelta(days=days)).isoformat()


def money(value):
    return D(str(value))


def rows_of(response):
    return list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))


def test_inventory_report(client, admin_headers, make_equipment, make_job):
    a = make_equipment(name="A", category="Cardio", quantity=3, purchase_price="1000")
    make_equipment(name="B", category="Strength", quantity=2, purchase_price="500.50", condition_status="poor")
    make_equipment(name="C", category="cardio", quantity=1, status="damaged")
    archived = make_equipment(name="D", category="Misc", quantity=10, purchase_price="99")
    client.post(f"/api/equipment/{archived['id']}/archive", headers=admin_headers)

    make_job(a["id"], days=3)                                              # due soon
    late = make_job(a["id"], "repair", days=-2)
    client.post(f"/api/maintenance/{late['id']}/complete", headers=admin_headers, json={"cost": "400"})

    report = client.get("/api/equipment/report", headers=admin_headers).json()
    assert report["records"] == 3 and report["total_quantity"] == 6 and report["archived_records"] == 1
    assert money(report["total_value"]) == D("4001.00")                  # 3 x 1000 + 2 x 500.50, archived item left out
    assert [(r["name"], r["records"], r["quantity"]) for r in report["by_status"]] == [
        ("available", 2, 5), ("damaged", 1, 1)]
    assert [(r["name"], r["records"], r["quantity"]) for r in report["by_condition"]] == [("good", 2, 4), ("poor", 1, 2)]
    assert [(r["name"].lower(), r["records"], r["quantity"]) for r in report["by_category"]] == [
        ("cardio", 2, 4), ("strength", 1, 2)]                            # "Cardio" and "cardio" are one category
    assert report["urgent_count"] == 1 and report["soon_count"] == 2      # damaged C | due-soon A and poor B
    assert report["open_jobs"] == 1 and report["overdue_jobs"] == 0
    assert money(report["maintenance_cost_total"]) == D("400") and money(report["repair_cost_total"]) == D("400")


def test_report_counts_overdue_jobs(client, admin_headers, make_equipment, make_job):
    item = make_equipment()
    make_job(item["id"], days=-3)
    make_job(item["id"], days=5)
    report = client.get("/api/equipment/report", headers=admin_headers).json()
    assert report["open_jobs"] == 2 and report["overdue_jobs"] == 1 and report["urgent_count"] == 1


def test_empty_inventory_report(client, admin_headers):
    report = client.get("/api/equipment/report", headers=admin_headers).json()
    assert report["records"] == 0 and report["total_quantity"] == 0 and money(report["total_value"]) == D("0")
    assert report["by_status"] == [] and report["urgent_count"] == 0


def test_reports_are_admin_only(client, reception_headers, trainer):
    for url in ("/api/equipment/report", "/api/equipment/export.csv"):
        assert client.get(url).status_code == 401
        assert client.get(url, headers=reception_headers).status_code == 403
        assert client.get(url, headers=trainer[1]).status_code == 403


def test_csv_export(client, admin_headers, make_equipment):
    make_equipment(name="Treadmill", category="Cardio", brand_model="Life Fitness", quantity=2,
                   purchase_date=iso(-50), purchase_price="1500.50", location="Floor 1")
    make_equipment(name="Old bench", category="Strength", status="damaged")
    response = client.get("/api/equipment/export.csv", headers=admin_headers)
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="equipment_inventory.csv"'
    assert response.headers["cache-control"] == "no-store"

    rows = rows_of(response)
    assert rows[0] == ["Code", "Name", "Category", "Brand / model", "Quantity", "Condition", "Status", "Location",
                       "Purchase date", "Price per item", "Total value", "Last maintenance", "Next maintenance",
                       "Attention", "Archived"]
    assert len(rows) == 3
    first, second = rows[1], rows[2]
    assert first[:5] == ["EQ-0001", "Treadmill", "Cardio", "Life Fitness", "2"] and first[7] == "Floor 1"
    assert first[8] == iso(-50) and money(first[9]) == D("1500.50") and money(first[10]) == D("3001.00")
    assert first[13] == "" and first[14] == "no"
    assert second[6] == "damaged" and second[9] == "" and second[13] == "Damaged: needs repair"


def test_csv_blocks_formula_injection_and_can_include_archived(client, admin_headers, make_equipment):
    make_equipment(name="=HYPERLINK(\"http://evil.example\",\"x\")")
    hidden = make_equipment(name="Retired bike")
    client.post(f"/api/equipment/{hidden['id']}/archive", headers=admin_headers)

    default = rows_of(client.get("/api/equipment/export.csv", headers=admin_headers))
    assert len(default) == 2 and default[1][1].startswith("'=HYPERLINK")
    with_archived = rows_of(client.get("/api/equipment/export.csv?include_archived=true", headers=admin_headers))
    assert len(with_archived) == 3 and with_archived[2][14] == "yes"
