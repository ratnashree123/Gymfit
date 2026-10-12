"""Printable receipt page (no database). Every value is HTML-escaped."""
from html import escape


def _row(label: str, value: str, strong: bool = False) -> str:
    cls = ' class="strong"' if strong else ""
    return f"<tr{cls}><td>{escape(label)}</td><td class=\"right\">{escape(value)}</td></tr>"


def render_receipt_html(r: dict) -> str:
    """r holds ready-to-print strings (see receipt_service.build_receipt)."""
    lines = "".join(_row(label, amount) for label, amount in r["lines"])
    reference = (f"<p><span>Reference:</span> {escape(r['reference_no'])}</p>"
                 if r.get("reference_no") else "")
    what = f"<p><span>For:</span> {escape(r['description'])}</p>" if r.get("description") else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Receipt {escape(r['receipt_number'])}</title>
<style>
  body {{ font-family: Arial, Helvetica, sans-serif; color: #111; margin: 0; padding: 24px; background: #f3f3f3; }}
  .receipt {{ max-width: 420px; margin: 0 auto; background: #fff; padding: 24px; border: 1px solid #ddd; }}
  h1 {{ margin: 0; font-size: 22px; text-align: center; }}
  .sub {{ text-align: center; color: #555; font-size: 13px; margin: 4px 0 16px; }}
  p {{ margin: 4px 0; font-size: 14px; }} p span {{ color: #555; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 14px; }}
  td {{ padding: 5px 0; border-bottom: 1px solid #eee; }} .right {{ text-align: right; }}
  tr.strong td {{ font-weight: bold; border-top: 2px solid #111; }}
  .note {{ font-size: 12px; color: #555; margin-top: 12px; text-align: center; }}
  button {{ display: block; margin: 16px auto 0; padding: 8px 18px; }}
  @media print {{ body {{ background: #fff; padding: 0; }} .receipt {{ border: 0; }} button {{ display: none; }} }}
</style></head>
<body><div class="receipt">
  <h1>{escape(r['gym_name'])}</h1>
  <div class="sub">Payment receipt</div>
  <p><span>Receipt no:</span> {escape(r['receipt_number'])}</p>
  <p><span>Date:</span> {escape(r['issued_local'])}</p>
  <p><span>Member:</span> {escape(r['member_name'])} ({escape(r['member_code'])})</p>
  <p><span>Invoice:</span> {escape(r['invoice_number'])}</p>
  {what}
  <table>{lines}</table>
  <table>
    {_row("Amount received", r['payment_amount'], strong=True)}
    {_row("Paid so far", r['paid_so_far'])}
    {_row("Balance due", r['balance_due'])}
  </table>
  <p><span>Method:</span> {escape(r['method_label'])}</p>
  {reference}
  <p><span>Received by:</span> {escape(r['received_by'])}</p>
  <p class="note">{escape(r['verification_label'])}</p>
  <button onclick="window.print()">Print</button>
</div></body></html>"""
