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
