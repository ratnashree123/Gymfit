"""Reads values from the gym_settings table (with a safe default)."""
from sqlalchemy.orm import Session

from app.models import GymSetting


def get_int(db: Session, key: str, default: int) -> int:
    row = db.get(GymSetting, key)
    if row is None:
        return default
    try:
        return int(row.setting_value)
    except (TypeError, ValueError):
        return default


def get_str(db: Session, key: str, default: str) -> str:
    row = db.get(GymSetting, key)
    return row.setting_value if row is not None and row.setting_value != "" else default


def get_bool(db: Session, key: str, default: bool) -> bool:
    row = db.get(GymSetting, key)
    if row is None:
        return default
    return row.setting_value.strip().lower() in ("true", "1", "yes", "on")


def get_decimal(db: Session, key: str, default) -> "Decimal":
    from decimal import Decimal, InvalidOperation

    row = db.get(GymSetting, key)
    if row is None:
        return Decimal(str(default))
    try:
        return Decimal(row.setting_value.strip())
    except (InvalidOperation, AttributeError):
        return Decimal(str(default))
