"""Money rules (no database). Always Decimal, never float. Rounded half-up to 2 places."""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class MoneyError(ValueError):
    """A money rule was broken (bad discount, bad tax...)."""


def quantize(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class InvoiceAmounts:
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal


def calculate_invoice(
    subtotal,
    *,
    discount_amount: Optional[Decimal] = None,
    discount_percent: Optional[Decimal] = None,
    tax_percent=0,
) -> InvoiceAmounts:
    """total = (subtotal - discount) + tax, where tax is charged on the discounted price."""
    sub = quantize(subtotal)
    if sub < 0:
        raise MoneyError("Price cannot be negative")
    if discount_amount is not None and discount_percent is not None:
        raise MoneyError("Use either a discount amount or a discount percent, not both")

    if discount_percent is not None:
        percent = Decimal(discount_percent)
        if not (0 <= percent <= 100):
            raise MoneyError("Discount percent must be between 0 and 100")
        discount = quantize(sub * percent / 100)
    elif discount_amount is not None:
        discount = quantize(discount_amount)
        if discount < 0:
            raise MoneyError("Discount cannot be negative")
    else:
        discount = ZERO

    if discount > sub:
        raise MoneyError("Discount cannot be more than the price")

    tax_rate = Decimal(tax_percent)
    if not (0 <= tax_rate <= 100):
        raise MoneyError("Tax percent must be between 0 and 100")

    taxable = sub - discount
    tax = quantize(taxable * tax_rate / 100)
    return InvoiceAmounts(sub, discount, tax, taxable + tax)


def discount_exceeds_percent(subtotal: Decimal, discount: Decimal, max_percent: Decimal) -> bool:
    return discount * 100 > subtotal * Decimal(max_percent)


def invoice_status(total: Decimal, paid: Decimal, cancelled: bool = False) -> str:
    """The status comes ONLY from real payments. Nothing is 'paid' unless money was recorded."""
    if cancelled:
        return "cancelled"
    if total > 0 and paid >= total:
        return "paid"
    if paid > 0:
        return "partial"
    return "pending"
