"""/api/equipment: inventory, damage reports, reports and CSV."""
import math
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status as http
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_admin, require_any_staff
from app.dependencies.common import get_client_ip
from app.exceptions import ForbiddenError
from app.models import User
from app.schemas.equipment import (
    Attention, Condition, DamageReport, EquipmentCreate, EquipmentDetailOut, EquipmentPage,
    EquipmentStatus, EquipmentUpdate, InventoryReport, MaintenanceCreate, MaintenanceOut,
)
from app.services import equipment_service, maintenance_service

router = APIRouter(prefix="/equipment", tags=["Equipment"])


def _detail(db: Session, equipment_id: int, user: User) -> EquipmentDetailOut:
    return equipment_service.detail_out(db, equipment_service.get_equipment(db, equipment_id), user)


# NOTE: fixed paths ("/categories", "/report", "/export.csv") are declared BEFORE "/{equipment_id}".
@router.get("/categories", response_model=list[str])
def list_categories(db: Session = Depends(get_db), _user: User = Depends(require_any_staff)):
    """Existing categories, for a dropdown."""
    return equipment_service.categories(db)


@router.get("/report", response_model=InventoryReport)
def inventory_report(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return equipment_service.inventory_report(db)


@router.get("/export.csv")
def export_inventory_csv(include_archived: bool = False, db: Session = Depends(get_db),
                         _admin: User = Depends(require_admin)):
    content = equipment_service.export_csv(db, include_archived)
    return Response(content=content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="equipment_inventory.csv"',
                             "Cache-Control": "no-store"})


@router.get("", response_model=EquipmentPage)
def list_equipment(
    search: Optional[str] = Query(None, max_length=100, description="Name, code, brand, location or category"),
    category: Optional[str] = Query(None, max_length=60),
    status: Optional[EquipmentStatus] = None,
    condition: Optional[Condition] = None,
    attention: Optional[Attention] = Query(None, description="urgent = damaged or overdue; soon = due soon or poor condition"),
    archived: bool = Query(False, description="Show archived items instead (Admin only)"),
    sort_by: Literal["name", "category", "equipment_code", "purchase_date", "created_at", "next_maintenance_date"] = "name",
    order: Literal["asc", "desc"] = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_any_staff),
):
    if archived and not equipment_service.is_admin(user):
        raise ForbiddenError("Only an Admin can view archived equipment")
    items, total = equipment_service.list_equipment(
        db, user, search=search, category=category, status=status, condition=condition,
        attention=attention, archived=archived, sort_by=sort_by, order=order, page=page, page_size=page_size)
    return EquipmentPage(items=items, total=total, page=page, page_size=page_size,
                         pages=math.ceil(total / page_size) if total else 0)


@router.post("", response_model=EquipmentDetailOut, status_code=http.HTTP_201_CREATED)
def create_equipment(payload: EquipmentCreate, request: Request, db: Session = Depends(get_db),
                     admin: User = Depends(require_admin)):
    eq = equipment_service.create_equipment(db, payload, admin, get_client_ip(request))
    return equipment_service.detail_out(db, eq, admin)


@router.get("/{equipment_id}", response_model=EquipmentDetailOut)
def read_equipment(equipment_id: int, db: Session = Depends(get_db), user: User = Depends(require_any_staff)):
    return _detail(db, equipment_id, user)


@router.patch("/{equipment_id}", response_model=EquipmentDetailOut)
def update_equipment(equipment_id: int, payload: EquipmentUpdate, request: Request,
                     db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    eq = equipment_service.update_equipment(db, equipment_id, payload, admin, get_client_ip(request))
    return equipment_service.detail_out(db, eq, admin)


@router.post("/{equipment_id}/archive", response_model=EquipmentDetailOut)
def archive_equipment(equipment_id: int, request: Request, db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    """Hides the item. It is never deleted, so its maintenance history stays."""
    eq = equipment_service.set_archived(db, equipment_id, True, admin, get_client_ip(request))
    return equipment_service.detail_out(db, eq, admin)


@router.post("/{equipment_id}/restore", response_model=EquipmentDetailOut)
def restore_equipment(equipment_id: int, request: Request, db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    eq = equipment_service.set_archived(db, equipment_id, False, admin, get_client_ip(request))
    return equipment_service.detail_out(db, eq, admin)


@router.post("/{equipment_id}/report-damage", response_model=EquipmentDetailOut)
def report_damage(equipment_id: int, payload: DamageReport, request: Request,
                  db: Session = Depends(get_db), user: User = Depends(require_any_staff)):
    """Any staff member can flag a broken item. It also opens a repair job for the Admin."""
    eq = equipment_service.report_damage(db, equipment_id, payload.description, user, get_client_ip(request))
    return equipment_service.detail_out(db, eq, user)


@router.post("/{equipment_id}/maintenance", response_model=MaintenanceOut, status_code=http.HTTP_201_CREATED)
def schedule_maintenance(equipment_id: int, payload: MaintenanceCreate, request: Request,
                         db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    job = maintenance_service.create_job(db, equipment_id, payload, admin, get_client_ip(request))
    return equipment_service.job_out(job, equipment_service.gym_today(), True)
