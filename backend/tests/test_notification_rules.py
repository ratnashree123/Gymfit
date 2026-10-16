from datetime import date
from types import SimpleNamespace

from app.services.notification_rules import (
    Desired, diff, expired_notice, expiring_notice, maintenance_notice, overdue_notice, trim,
)


def row(id, user=1, type="membership_expiring", related="member", related_id=5, title="T", message="M"):
    return SimpleNamespace(id=id, user_id=user, type=type, related_type=related, related_id=related_id,
                           title=title, message=message)


def want(user=1, type="membership_expiring", related="member", related_id=5, title="T", message="M"):
    return Desired(user, type, related, related_id, title, message)


# ---------- text ----------
def test_trim_keeps_short_text_and_cuts_long_text():
    assert trim("short", 10) == "short"
    cut = trim("x" * 300, 255)
    assert len(cut) == 255 and cut.endswith("\u2026")


def test_expiring_notice_wording():
    day = date(2026, 11, 5)
    assert expiring_notice("Anita Sharma", "GF-000001", "Monthly", day, 3) == (
        "Membership expiring soon", "Anita Sharma (GF-000001): Monthly ends on 05 Nov 2026 (in 3 days)")
    assert expiring_notice("A", "C", "P", day, 1)[1].endswith("(tomorrow)")
    assert expiring_notice("A", "C", "P", day, 0)[1].endswith("(today)")


def test_other_notice_wording():
    assert expired_notice("Anita", "GF-000001", "Monthly", date(2026, 10, 1)) == (
        "Membership expired", "Anita (GF-000001): Monthly ended on 01 Oct 2026")
    title, message = overdue_notice("Anita", "GF-000001", "INV-000007", "Rs 400.00", date(2026, 10, 1))
    assert title == "Payment overdue" and "INV-000007" in message and "Rs 400.00" in message and "01 Oct 2026" in message
    assert maintenance_notice("Treadmill", "EQ-0001", "urgent", "Damaged: needs repair")[0] == "Equipment needs attention"
    assert maintenance_notice("Treadmill", "EQ-0001", "soon", "Maintenance due in 3 days")[0] == "Maintenance due soon"


def test_long_messages_fit_the_database_column():
    assert len(expiring_notice("N" * 400, "C", "P", date(2026, 1, 1), 2)[1]) == 255


# ---------- syncing the stored notifications ----------
def test_missing_notifications_are_created():
    result = diff([], [want(related_id=1), want(related_id=2)])
    assert [d.related_id for d in result.create] == [1, 2] and not result.update and not result.delete_ids


def test_matching_notifications_are_left_alone():
    result = diff([row(1)], [want()])
    assert not result.create and not result.update and not result.delete_ids


def test_changed_text_is_updated_in_place():
    result = diff([row(1, message="ends in 5 days")], [want(message="ends in 4 days")])
    assert not result.create and not result.delete_ids
    assert result.update[0][0] == 1 and result.update[0][1].message == "ends in 4 days"


def test_resolved_notifications_are_deleted():
    result = diff([row(1), row(2, related_id=9)], [want()])
    assert result.delete_ids == [2] and not result.create


def test_each_user_has_their_own_notification():
    result = diff([row(1, user=1)], [want(user=1), want(user=2)])
    assert [d.user_id for d in result.create] == [2] and not result.delete_ids


def test_duplicates_are_removed_keeping_the_oldest():
    result = diff([row(7), row(3), row(5)], [want()])
    assert sorted(result.delete_ids) == [5, 7] and not result.create and not result.update


def test_a_soon_item_that_becomes_urgent_gets_a_new_unread_notification():
    soon = row(1, type="maintenance_due", related="equipment_soon", related_id=4)
    urgent = want(type="maintenance_due", related="equipment_urgent", related_id=4)
    result = diff([soon], [urgent])
    assert [d.related_type for d in result.create] == ["equipment_urgent"] and result.delete_ids == [1]
