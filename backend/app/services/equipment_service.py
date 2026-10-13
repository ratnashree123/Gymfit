"""Equipment inventory: add, edit, archive, report damage, reports."""
import csv
import io
import uuid
from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.constants import ROLE_ADMIN
from app.exceptions import BadRequestError, NotFoundError
from app.models import Equipment, EquipmentMaintenance, User
from app.schemas.equipment import (
    CountRow, EquipmentBrief, EquipmentCreate, EquipmentDetailOut, EquipmentOut, EquipmentUpdate,
    InventoryReport, MaintenanceOut,
)
from app.services import settings_service
from app.services.audit_service import log_action
from app.services.equipment_rules import Urgency, inventory_value, maintenance_urgency
from app.services.revenue_rules import csv_safe
from app.utils.dates import gym_today

SORT_COLUMNS = {
    "name": Equipment.name, "category": Equipment.category, "equipment_code": Equipment.equipment_code,
    "purchase_date": Equipment.purchase_date, "created_at": Equipment.created_at,
    "next_maintenance_date": Equipment.next_maintenance_date,
}
REQUIRED_ON_UPDATE = {"name", "category", "quantity", "condition_status", "status"}
EDITABLE = ("name", "category", "brand_model", "quantity", "purchase_date", "purchase_price",
            "condition_status", "location", "last_maintenance_date", "next_maintenance_date", "notes")
OPEN_JOB_STATUSES = ("scheduled", "in_progress")


# ------------------------------------------------------------------ helpers
def is_admin(user: User) -> bool:
    return user.role.name == ROLE_ADMIN


def alert_days(db: Session, override: Optional[int] = None) -> int:
    if override is not None:
        return override
    return max(0, settings_service.get_int(db, "maintenance_alert_days", 7))


def due_dates_for(db: Session, ids: list[int]) -> dict[int, list[date]]:
    """Dates of the scheduled (not yet started) jobs of each item."""
    grouped: dict[int, list[date]] = {i: [] for i in ids}
    if ids:
        rows = db.execute(select(EquipmentMaintenance.equipment_id, EquipmentMaintenance.scheduled_date)
                          .where(EquipmentMaintenance.equipment_id.in_(ids),
                                 EquipmentMaintenance.status == "scheduled")).all()
        for equipment_id, scheduled in rows:
            grouped[equipment_id].append(scheduled)
    return grouped


def urgency_for(eq: Equipment, due_map: dict[int, list[date]], today: date, days: int) -> Urgency:
    dates = list(due_map.get(eq.id, []))
    if eq.next_maintenance_date is not None:
        dates.append(eq.next_maintenance_date)
    return maintenance_urgency(eq.status, eq.condition_status, dates, today, days)


def brief(eq: Equipment) -> EquipmentBrief:
    return EquipmentBrief(id=eq.id, equipment_code=eq.equipment_code, name=eq.name, category=eq.category,
                          location=eq.location, quantity=eq.quantity, status=eq.status,
                          condition_status=eq.condition_status)


def to_out(eq: Equipment, urgency: Urgency, admin: bool) -> EquipmentOut:
    return EquipmentOut(
        id=eq.id, equipment_code=eq.equipment_code, name=eq.name, category=eq.category,
        brand_model=eq.brand_model, quantity=eq.quantity, purchase_date=eq.purchase_date,
        condition_status=eq.condition_status, location=eq.location, status=eq.status,
        last_maintenance_date=eq.last_maintenance_date, next_maintenance_date=eq.next_maintenance_date,
        notes=eq.notes, is_archived=eq.is_archived, attention_level=urgency.level,
        attention_code=urgency.code, attention_message=urgency.message, due_date=urgency.due_date,
        purchase_price=eq.purchase_price if admin else None,
        total_value=inventory_value(eq.purchase_price, eq.quantity) if admin else None,
        financials_visible=admin, created_at=eq.created_at, updated_at=eq.updated_at)


def job_out(job: EquipmentMaintenance, today: date, admin: bool) -> MaintenanceOut:
    return MaintenanceOut(
        id=job.id, equipment=brief(job.equipment), maintenance_type=job.maintenance_type,
        status=job.status, scheduled_date=job.scheduled_date, performed_date=job.performed_date,
        is_overdue=job.status == "scheduled" and job.scheduled_date < today,
        cost=job.cost if admin else None, cost_visible=admin, performed_by=job.performed_by,
        description=job.description, created_by_name=job.creator.full_name if job.creator else None,
        created_at=job.created_at)


def _snapshot(eq: Equipment) -> dict:
    return {"equipment_code": eq.equipment_code, "name": eq.name, "category": eq.category,
            "brand_model": eq.brand_model, "quantity": eq.quantity, "purchase_date": eq.purchase_date,
            "purchase_price": eq.purchase_price, "condition_status": eq.condition_status,
            "location": eq.location, "status": eq.status,
            "last_maintenance_date": eq.last_maintenance_date,
            "next_maintenance_date": eq.next_maintenance_date, "is_archived": eq.is_archived}


def get_equipment(db: Session, equipment_id: int) -> Equipment:
    eq = db.get(Equipment, equipment_id)
    if eq is None:
        raise NotFoundError("Equipment not found")
    return eq


def lock_equipment(db: Session, equipment_id: int) -> Equipment:
    """SELECT ... FOR UPDATE, so two people changing the same item are handled one after the other."""
    eq = db.scalar(select(Equipment).where(Equipment.id == equipment_id).with_for_update())
    if eq is None:
        raise NotFoundError("Equipment not found")
    return eq


def count_open_jobs(db: Session, equipment_id: int, status: Optional[str] = None) -> int:
    statuses = (status,) if status else OPEN_JOB_STATUSES
    return db.scalar(select(func.count(EquipmentMaintenance.id)).where(
        EquipmentMaintenance.equipment_id == equipment_id,
        EquipmentMaintenance.status.in_(statuses))) or 0


# ------------------------------------------------------------------ reading
def _attention_conditions(attention: str, today: date, days: int):
    """The same rules as equipment_rules.maintenance_urgency, written as SQL for filtering."""
    limit = today + timedelta(days=days)

    def next_before(day):
        return and_(Equipment.next_maintenance_date.is_not(None), Equipment.next_maintenance_date < day)

    def next_by(day):
        return and_(Equipment.next_maintenance_date.is_not(None), Equipment.next_maintenance_date <= day)

    def job(op, day):
        return exists().where(EquipmentMaintenance.equipment_id == Equipment.id,
                              EquipmentMaintenance.status == "scheduled", op(EquipmentMaintenance.scheduled_date, day))

    overdue = or_(next_before(today), job(lambda col, d: col < d, today))
    if attention == "urgent":
        return or_(Equipment.status == "damaged", and_(Equipment.status == "available", overdue))
    return and_(Equipment.status == "available", not_(overdue),
                or_(Equipment.condition_status == "poor", next_by(limit), job(lambda col, d: col <= d, limit)))


def list_equipment(db: Session, user: User, *, search: Optional[str], category: Optional[str],
                   status: Optional[str], condition: Optional[str], attention: Optional[str],
                   archived: bool, sort_by: str, order: str, page: int, page_size: int):
    today, days = gym_today(), alert_days(db)
    conditions = [Equipment.is_archived.is_(archived)]
    if search and search.strip():
        pattern = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(or_(*[col.ilike(pattern, escape="\\") for col in (
            Equipment.name, Equipment.equipment_code, Equipment.brand_model, Equipment.location, Equipment.category)]))
    if category:
        conditions.append(func.lower(Equipment.category) == category.strip().lower())
    if status:
        conditions.append(Equipment.status == status)
    if condition:
        conditions.append(Equipment.condition_status == condition)
    if attention:
        conditions.append(_attention_conditions(attention, today, days))

    total = db.scalar(select(func.count(Equipment.id)).where(and_(*conditions))) or 0
    sort_column = SORT_COLUMNS.get(sort_by, Equipment.name)
    direction = sort_column.desc() if order == "desc" else sort_column.asc()
    items = list(db.scalars(select(Equipment).where(and_(*conditions)).order_by(direction, Equipment.id)
                            .offset((page - 1) * page_size).limit(page_size)).all())
    due_map = due_dates_for(db, [e.id for e in items])
    admin = is_admin(user)
    return [to_out(e, urgency_for(e, due_map, today, days), admin) for e in items], total


def categories(db: Session) -> list[str]:
    seen: "OrderedDict[str, str]" = OrderedDict()
    for (name,) in db.execute(select(Equipment.category).where(Equipment.is_archived.is_(False))
                              .order_by(Equipment.category)).all():
        seen.setdefault(name.strip().lower(), name.strip())
    return sorted(seen.values(), key=str.lower)


def detail_out(db: Session, eq: Equipment, user: User) -> EquipmentDetailOut:
    today, days, admin = gym_today(), alert_days(db), is_admin(user)
    base = to_out(eq, urgency_for(eq, due_dates_for(db, [eq.id]), today, days), admin).model_dump()

    recent: list[MaintenanceOut] = []
    if user.role.name in (ROLE_ADMIN, "Receptionist"):
        jobs = db.scalars(select(EquipmentMaintenance).where(EquipmentMaintenance.equipment_id == eq.id)
                          .options(selectinload(EquipmentMaintenance.equipment),
                                   selectinload(EquipmentMaintenance.creator))
                          .order_by(EquipmentMaintenance.scheduled_date.desc(), EquipmentMaintenance.id.desc())
                          .limit(5)).all()
        recent = [job_out(j, today, admin) for j in jobs]

    total_cost = repair_cost = None
    if admin:
        done = (EquipmentMaintenance.equipment_id == eq.id, EquipmentMaintenance.status == "completed")
        total_cost = Decimal(db.scalar(select(func.coalesce(func.sum(EquipmentMaintenance.cost), 0)).where(*done)) or 0)
        repair_cost = Decimal(db.scalar(select(func.coalesce(func.sum(EquipmentMaintenance.cost), 0)).where(
            *done, EquipmentMaintenance.maintenance_type == "repair")) or 0)
    return EquipmentDetailOut(**base, open_jobs=count_open_jobs(db, eq.id), recent_maintenance=recent,
                              maintenance_cost_total=total_cost, repair_cost_total=repair_cost)


# ------------------------------------------------------------------ writing
def create_equipment(db: Session, data: EquipmentCreate, actor: User, ip: Optional[str]) -> Equipment:
    eq = Equipment(
        equipment_code=f"TMP-{uuid.uuid4().hex[:15]}",  # replaced below, once the id is known
        name=data.name, category=data.category, brand_model=data.brand_model, quantity=data.quantity,
        purchase_date=data.purchase_date, purchase_price=data.purchase_price,
        condition_status=data.condition_status, location=data.location, status=data.status,
        last_maintenance_date=data.last_maintenance_date, next_maintenance_date=data.next_maintenance_date,
        notes=data.notes)
    db.add(eq)
    db.flush()
    eq.equipment_code = f"EQ-{eq.id:04d}"
    log_action(db, user_id=actor.id, action="equipment.create", entity_type="equipment",
               entity_id=eq.id, new=_snapshot(eq), ip=ip)
    db.commit()
    db.refresh(eq)
    return eq


def update_equipment(db: Session, equipment_id: int, data: EquipmentUpdate, actor: User,
                     ip: Optional[str]) -> Equipment:
    eq = lock_equipment(db, equipment_id)
    changes = data.model_dump(exclude_unset=True)
    for field in changes:
        if field in REQUIRED_ON_UPDATE and changes[field] is None:
            raise BadRequestError(f"'{field}' cannot be empty")
    if "status" in changes and eq.status == "under_maintenance":
        raise BadRequestError("A maintenance job is in progress. Complete or cancel it to change the status")

    old = _snapshot(eq)
    for field in EDITABLE:
        if field in changes:
            setattr(eq, field, changes[field])
    if "status" in changes:
        eq.status = changes["status"]
    db.flush()
    log_action(db, user_id=actor.id, action="equipment.update", entity_type="equipment",
               entity_id=eq.id, old=old, new=_snapshot(eq), ip=ip)
    db.commit()
    db.refresh(eq)
    return eq


def set_archived(db: Session, equipment_id: int, archived: bool, actor: User, ip: Optional[str]) -> Equipment:
    """Archiving hides an item. Nothing is ever deleted, so its maintenance history stays."""
    eq = lock_equipment(db, equipment_id)
    if eq.is_archived == archived:
        raise BadRequestError("This item is already archived" if archived else "This item is not archived")
    if archived and count_open_jobs(db, eq.id, "in_progress"):
        raise BadRequestError("A maintenance job is in progress. Complete or cancel it before archiving")
    eq.is_archived = archived
    log_action(db, user_id=actor.id, action="equipment.archive" if archived else "equipment.restore",
               entity_type="equipment", entity_id=eq.id,
               old={"is_archived": not archived}, new={"is_archived": archived}, ip=ip)
    db.commit()
    db.refresh(eq)
    return eq


def report_damage(db: Session, equipment_id: int, description: str, actor: User, ip: Optional[str]) -> Equipment:
    """Any staff member can flag a broken item. It also opens a 'repair' job so it shows up in reminders."""
    eq = lock_equipment(db, equipment_id)
    if eq.is_archived:
        raise BadRequestError("This item is archived")
    if eq.status == "damaged":
        raise BadRequestError("This item is already reported as damaged")
    if eq.status == "under_maintenance":
        raise BadRequestError("This item is already being serviced")
    old_status = eq.status
    eq.status = "damaged"
    job = EquipmentMaintenance(equipment_id=eq.id, maintenance_type="repair", status="scheduled",
                               scheduled_date=gym_today(), description=f"Damage reported: {description}",
                               created_by=actor.id)
    db.add(job)
    db.flush()
    log_action(db, user_id=actor.id, action="equipment.report_damage", entity_type="equipment",
               entity_id=eq.id, old={"status": old_status},
               new={"status": "damaged", "repair_job_id": job.id, "description": description}, ip=ip)
    db.commit()
    db.refresh(eq)
    return eq


# ------------------------------------------------------------------ reports
def inventory_report(db: Session) -> InventoryReport:
    today, days = gym_today(), alert_days(db)
    items = list(db.scalars(select(Equipment).where(Equipment.is_archived.is_(False))).all())
    due_map = due_dates_for(db, [e.id for e in items])

    def tally(key_of) -> list[CountRow]:
        groups: "OrderedDict[str, list]" = OrderedDict()
        for e in sorted(items, key=lambda e: key_of(e).lower()):
            group = groups.setdefault(key_of(e).strip().lower(), [key_of(e).strip(), 0, 0])
            group[1] += 1
            group[2] += e.quantity
        return [CountRow(name=n, records=r, quantity=q) for n, r, q in groups.values()]

    levels = [urgency_for(e, due_map, today, days).level for e in items]
    done = EquipmentMaintenance.status == "completed"
    cost_total = Decimal(db.scalar(select(func.coalesce(func.sum(EquipmentMaintenance.cost), 0)).where(done)) or 0)
    repair_total = Decimal(db.scalar(select(func.coalesce(func.sum(EquipmentMaintenance.cost), 0)).where(
        done, EquipmentMaintenance.maintenance_type == "repair")) or 0)
    live = (Equipment.is_archived.is_(False),)
    open_jobs = db.scalar(select(func.count(EquipmentMaintenance.id)).join(
        Equipment, Equipment.id == EquipmentMaintenance.equipment_id).where(
        *live, EquipmentMaintenance.status.in_(OPEN_JOB_STATUSES))) or 0
    overdue_jobs = db.scalar(select(func.count(EquipmentMaintenance.id)).join(
        Equipment, Equipment.id == EquipmentMaintenance.equipment_id).where(
        *live, EquipmentMaintenance.status == "scheduled", EquipmentMaintenance.scheduled_date < today)) or 0

    return InventoryReport(
        records=len(items), total_quantity=sum(e.quantity for e in items),
        archived_records=db.scalar(select(func.count(Equipment.id)).where(Equipment.is_archived.is_(True))) or 0,
        total_value=sum((inventory_value(e.purchase_price, e.quantity) for e in items), Decimal("0.00")),
        by_status=tally(lambda e: e.status), by_condition=tally(lambda e: e.condition_status),
        by_category=tally(lambda e: e.category),
        urgent_count=levels.count("urgent"), soon_count=levels.count("soon"),
        open_jobs=open_jobs, overdue_jobs=overdue_jobs,
        maintenance_cost_total=cost_total.quantize(Decimal("0.01")),
        repair_cost_total=repair_total.quantize(Decimal("0.01")))


def export_csv(db: Session, include_archived: bool) -> str:
    today, days = gym_today(), alert_days(db)
    stmt = select(Equipment).order_by(Equipment.equipment_code)
    if not include_archived:
        stmt = stmt.where(Equipment.is_archived.is_(False))
    items = list(db.scalars(stmt).all())
    due_map = due_dates_for(db, [e.id for e in items])

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Code", "Name", "Category", "Brand / model", "Quantity", "Condition", "Status",
                     "Location", "Purchase date", "Price per item", "Total value", "Last maintenance",
                     "Next maintenance", "Attention", "Archived"])
    for e in items:
        urgency = urgency_for(e, due_map, today, days)
        writer.writerow([csv_safe(v) for v in (
            e.equipment_code, e.name, e.category, e.brand_model, e.quantity, e.condition_status, e.status,
            e.location, e.purchase_date, e.purchase_price if e.purchase_price is not None else "",
            inventory_value(e.purchase_price, e.quantity), e.last_maintenance_date, e.next_maintenance_date,
            urgency.message if urgency.level != "ok" else "", "yes" if e.is_archived else "no")])
    return "\ufeff" + buffer.getvalue()
