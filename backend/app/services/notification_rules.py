"""Notification rules (no database): what text to show, and how to bring the stored
notifications in line with what is true right now."""
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

AUTO_TYPES = ("membership_expiring", "membership_expired", "payment_pending", "maintenance_due")
TITLE_MAX = 150
MESSAGE_MAX = 255


def trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _day(value: date) -> str:
    return f"{value:%d %b %Y}"


def _when(days: int) -> str:
    if days <= 0:
        return "today"
    return "tomorrow" if days == 1 else f"in {days} days"


@dataclass(frozen=True)
class Desired:
    """One notification that SHOULD exist right now."""
    user_id: int
    type: str
    related_type: str
    related_id: int
    title: str
    message: str

    @property
    def key(self) -> tuple:
        return (self.user_id, self.type, self.related_type, self.related_id)


def expiring_notice(name: str, code: str, plan: str, end_date: date, days_left: int) -> tuple[str, str]:
    return ("Membership expiring soon",
            trim(f"{name} ({code}): {plan} ends on {_day(end_date)} ({_when(days_left)})", MESSAGE_MAX))


def expired_notice(name: str, code: str, plan: str, end_date: date) -> tuple[str, str]:
    return ("Membership expired", trim(f"{name} ({code}): {plan} ended on {_day(end_date)}", MESSAGE_MAX))


def overdue_notice(name: str, code: str, invoice_number: str, balance: str, due_date: date) -> tuple[str, str]:
    return ("Payment overdue",
            trim(f"{name} ({code}): invoice {invoice_number}, {balance} still to pay, was due {_day(due_date)}",
                 MESSAGE_MAX))


def maintenance_notice(name: str, code: str, level: str, reason: str) -> tuple[str, str]:
    title = "Equipment needs attention" if level == "urgent" else "Maintenance due soon"
    return title, trim(f"{name} ({code}): {reason}", MESSAGE_MAX)


@dataclass
class Diff:
    create: list = field(default_factory=list)       # Desired
    update: list = field(default_factory=list)       # (row id, Desired)
    delete_ids: list = field(default_factory=list)   # row ids


def diff(existing: Sequence, desired: Sequence[Desired]) -> Diff:
    """Compare the stored notifications with the ones that should exist.

    * missing ones are created (unread);
    * ones whose text changed are updated, and keep their read / unread state;
    * ones that are no longer true (member renewed, invoice paid, item repaired) are deleted;
    * accidental duplicates are removed, keeping the oldest.
    Each existing row needs: id, user_id, type, related_type, related_id, title, message.
    """
    wanted = {d.key: d for d in desired}
    kept: dict[tuple, object] = {}
    result = Diff()

    for row in sorted(existing, key=lambda r: r.id):
        key = (row.user_id, row.type, row.related_type, row.related_id)
        if key in kept:
            result.delete_ids.append(row.id)
        else:
            kept[key] = row

    for key, d in wanted.items():
        row = kept.get(key)
        if row is None:
            result.create.append(d)
        elif row.title != d.title or row.message != d.message:
            result.update.append((row.id, d))

    result.delete_ids += [row.id for key, row in kept.items() if key not in wanted]
    return result
