"""Date helpers. 'Today' always means today in the GYM's timezone, not the server's."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def gym_today() -> date:
    return datetime.now(ZoneInfo(get_settings().gym_timezone)).date()
