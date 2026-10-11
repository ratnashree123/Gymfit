"""Small helpers shared by all models."""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Integer


def utcnow() -> datetime:
    """Current time in UTC as a naive datetime (MySQL DATETIME has no timezone)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# BIGINT on MySQL, INTEGER on SQLite (SQLite only auto-numbers INTEGER keys;
# the test-suite uses SQLite).
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")
