from app.services.receipt_html import render_receipt_html

BASE = {
    "gym_name": "GymFit", "receipt_number": "RCP-000001", "issued_local": "12 Oct 2026, 03:45 PM",
    "member_name": "Anita Sharma", "member_code": "GF-000001", "invoice_number": "INV-000001",
    "description": "Monthly", "lines": [("Price", "Rs 1,500.00"), ("Total", "Rs 1,500.00")],
    "payment_amount": "Rs 500.00", "paid_so_far": "Rs 500.00", "balance_due": "Rs 1,000.00",
    "method_label": "UPI", "reference_no": "UPI12345", "received_by": "Front Desk",
    "verification_label": "Manually recorded by staff (not verified online)",
}


def test_receipt_contains_the_key_facts():
    page = render_receipt_html(BASE)
    for text in ("RCP-000001", "Anita Sharma", "GF-000001", "INV-000001", "Rs 500.00",
                 "Rs 1,000.00", "UPI12345", "Front Desk", "not verified online"):
        assert text in page


def test_receipt_escapes_everything_a_user_can_type():
    evil = "<script>alert(1)</script>"
    page = render_receipt_html({**BASE, "member_name": evil, "gym_name": evil, "description": evil,
                                "reference_no": evil, "received_by": evil,
                                "lines": [(evil, evil)]})
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_receipt_without_reference_or_description():
    page = render_receipt_html({**BASE, "reference_no": None, "description": None})
    assert "Reference:" not in page and "For:" not in page
