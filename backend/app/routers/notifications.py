"""/api/notifications: each staff member's own alerts."""
import math
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_any_staff
from app.models import User
from app.schemas.dashboard import (
    MarkedOut, NotificationOut, NotificationPage, NotificationType, SyncOut, UnreadCount,
)
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# NOTE: fixed paths ("/unread-count", "/refresh", "/read-all") come BEFORE "/{notification_id}/read".
@router.get("/unread-count", response_model=UnreadCount)
def unread_count(db: Session = Depends(get_db), user: User = Depends(require_any_staff)):
    """For the bell icon. Brings the notifications up to date first (at most every few minutes)."""
    notification_service.maybe_sync(db)
    return UnreadCount(unread=notification_service.unread_count(db, user))


@router.post("/refresh", response_model=SyncOut)
def refresh(db: Session = Depends(get_db), _user: User = Depends(require_any_staff)):
    """Re-check memberships, payments and equipment now. Skipped if it ran in the last 30 seconds."""
    return notification_service.maybe_sync(db, force=True)


@router.post("/read-all", response_model=MarkedOut)
def read_all(db: Session = Depends(get_db), user: User = Depends(require_any_staff)):
    return MarkedOut(marked=notification_service.mark_all_read(db, user))


@router.get("", response_model=NotificationPage)
def list_notifications(
    unread_only: bool = False,
    type: Optional[NotificationType] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_any_staff),
):
    """Your notifications, newest first. Trainers only get the membership notices of their own members."""
    items, total, unread = notification_service.list_for_user(
        db, user, unread_only=unread_only, type_=type, page=page, page_size=page_size)
    return NotificationPage(items=items, total=total, page=page, page_size=page_size,
                            pages=math.ceil(total / page_size) if total else 0, unread_count=unread)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_staff)):
    return notification_service.to_out(notification_service.mark_read(db, user, notification_id))
