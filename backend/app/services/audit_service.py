"""Writes rows to the audit_logs table (who did what, when)."""
import json
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AuditLog


def _clean(values: Optional[dict]) -> Optional[dict]:
    """Make the data JSON-safe and drop anything that looks like a password."""
    if values is None:
        return None
    safe = {k: v for k, v in values.items() if "password" not in k.lower()}
    return json.loads(json.dumps(safe, default=str))


def log_action(
    db: Session,
    *,
    user_id: Optional[int],
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    old: Optional[dict] = None,
    new: Optional[dict] = None,
    ip: Optional[str] = None,
) -> None:
    """Adds the log row to the current transaction. The caller commits."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_values=_clean(old),
            new_values=_clean(new),
            ip_address=ip,
        )
    )
