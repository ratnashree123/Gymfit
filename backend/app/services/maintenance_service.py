"""Maintenance jobs: schedule, start, complete, cancel, history, reminders.

A finished (completed or cancelled) job is history: it can never be changed or deleted.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.exceptions import BadRequestError, NotFoundError
from app.models import Equipment, EquipmentMaintenance, User
from app.schemas.equipment import (
    MaintenanceCancel, MaintenanceComplete, MaintenanceCreate, MaintenanceOut, MaintenanceStart,
    MaintenanceUpdate, ReminderItem, RemindersOut,
)
from app.services import equipment_service
from app.services.audit_service import log_action
from app.services.equipment_rules import UNSET, can_transition, next_due_after_completion, next_equipment_status
from app.utils.dates import gym_today

LOADERS = (selectinload(EquipmentMaintenance.equipment), selectinload(EquipmentMaintenance.creator))


def _snapshot(job: EquipmentMaintenance) -> dict:
    return {"equipment_id": job.equipment_id, "maintenance_type": job.maintenance_type,
            "status": job.status, "scheduled_date": job.scheduled_date,
            "performed_date": job.performed_date, "cost": job.cost, "performed_by": job.performed_by}


def get_job(db: Session, job_id: int) -> EquipmentMaintenance:
    job = db.scalar(select(EquipmentMaintenance).where(EquipmentMaintenance.id == job_id).options(*LOADERS))
    if job is None:
        raise NotFoundError("Maintenance job not found")
    return job


def job_response(db: Session, job_id: int, user: User) -> MaintenanceOut:
    return equipment_service.job_out(get_job(db, job_id), gym_today(), equipment_service.is_admin(user))


def _lock_job_and_equipment(db: Session, job_id: int) -> tuple[EquipmentMaintenance, Equipment]:
    job = db.get(EquipmentMaintenance, job_id)
    if job is None:
        raise NotFoundError("Maintenance job not found")
    eq = equipment_service.lock_equipment(db, job.equipment_id)
    db.refresh(job)  # read the job again now that nobody else can change this item
    return job, eq


def _require_open(job: EquipmentMaintenance, new_status: Optional[str] = None) -> None:
    if job.status in ("completed", "cancelled"):
        raise BadRequestError(f"This job is {job.status}. Finished jobs are kept as history and cannot be changed")
    if new_status is not None and not can_transition(job.status, new_status):
        raise BadRequestError(f"A {job.status.replace('_', ' ')} job cannot become {new_status.replace('_', ' ')}")


def _other_in_progress(db: Session, equipment_id: int, job_id: int) -> bool:
    return bool(db.scalar(select(func.count(EquipmentMaintenance.id)).where(
        EquipmentMaintenance.equipment_id == equipment_id, EquipmentMaintenance.status == "in_progress",
        EquipmentMaintenance.id != job_id)))


def _equipment_snapshot(eq: Equipment) -> dict:
    return {"status": eq.status, "condition_status": eq.condition_status,
            "last_maintenance_date": eq.last_maintenance_date, "next_maintenance_date": eq.next_maintenance_date}


# ------------------------------------------------------------------ jobs
def create_job(db: Session, equipment_id: int, data: MaintenanceCreate, actor: User, ip: Optional[str]) -> EquipmentMaintenance:
    eq = equipment_service.lock_equipment(db, equipment_id)
    if eq.is_archived:
        raise BadRequestError("This item is archived. Restore it before scheduling maintenance")
    job = EquipmentMaintenance(equipment_id=eq.id, maintenance_type=data.maintenance_type, status="scheduled",
                               scheduled_date=data.scheduled_date, description=data.description,
                               performed_by=data.performed_by, created_by=actor.id)
    db.add(job)
    db.flush()
    log_action(db, user_id=actor.id, action="maintenance.create", entity_type="maintenance",
               entity_id=job.id, new=_snapshot(job), ip=ip)
    db.commit()
    return get_job(db, job.id)


def update_job(db: Session, job_id: int, data: MaintenanceUpdate, actor: User, ip: Optional[str]) -> EquipmentMaintenance:
    job, _eq = _lock_job_and_equipment(db, job_id)
    _require_open(job)
    changes = data.model_dump(exclude_unset=True)
    for field in ("maintenance_type", "scheduled_date"):
        if field in changes and changes[field] is None:
            raise BadRequestError(f"'{field}' cannot be empty")
    if "maintenance_type" in changes and job.status != "scheduled":
        raise BadRequestError("The type of a job that has already started cannot be changed")
    old = _snapshot(job)
    for field, value in changes.items():
        setattr(job, field, value)
    db.flush()
    log_action(db, user_id=actor.id, action="maintenance.update", entity_type="maintenance",
               entity_id=job.id, old=old, new=_snapshot(job), ip=ip)
    db.commit()
    return get_job(db, job.id)


def start_job(db: Session, job_id: int, data: MaintenanceStart, actor: User, ip: Optional[str]) -> EquipmentMaintenance:
    job, eq = _lock_job_and_equipment(db, job_id)
    _require_open(job, "in_progress")
    if eq.is_archived:
        raise BadRequestError("This item is archived. Restore it before starting maintenance")
    old_job, old_eq = _snapshot(job), _equipment_snapshot(eq)
    eq.status = next_equipment_status(job.maintenance_type, job.status, "in_progress", False, eq.status)
    job.status = "in_progress"
    if data.performed_by:
        job.performed_by = data.performed_by
    log_action(db, user_id=actor.id, action="maintenance.start", entity_type="maintenance", entity_id=job.id,
               old={**old_job, "equipment": old_eq}, new={**_snapshot(job), "equipment": _equipment_snapshot(eq)}, ip=ip)
    db.commit()
    return get_job(db, job.id)


def complete_job(db: Session, job_id: int, data: MaintenanceComplete, actor: User, ip: Optional[str]) -> EquipmentMaintenance:
    job, eq = _lock_job_and_equipment(db, job_id)
    _require_open(job, "completed")
    performed = data.performed_date or gym_today()
    provided = data.next_maintenance_date if "next_maintenance_date" in data.model_fields_set else UNSET
    if provided is not UNSET and provided is not None and provided < performed:
        raise BadRequestError("The next maintenance date cannot be before the date this job was done")

    old_job, old_eq = _snapshot(job), _equipment_snapshot(eq)
    other = _other_in_progress(db, eq.id, job.id)
    eq.status = next_equipment_status(job.maintenance_type, job.status, "completed", other, eq.status)
    if eq.last_maintenance_date is None or performed > eq.last_maintenance_date:
        eq.last_maintenance_date = performed
    eq.next_maintenance_date = next_due_after_completion(eq.next_maintenance_date, performed,
                                                         job.maintenance_type, provided)
    if data.condition_after:
        eq.condition_status = data.condition_after

    job.status, job.performed_date, job.cost = "completed", performed, data.cost
    if data.performed_by:
        job.performed_by = data.performed_by
    if data.notes:
        job.description = f"{job.description} | Result: {data.notes}" if job.description else f"Result: {data.notes}"
    log_action(db, user_id=actor.id, action="maintenance.complete", entity_type="maintenance", entity_id=job.id,
               old={**old_job, "equipment": old_eq}, new={**_snapshot(job), "equipment": _equipment_snapshot(eq)}, ip=ip)
    db.commit()
    return get_job(db, job.id)


def cancel_job(db: Session, job_id: int, data: MaintenanceCancel, actor: User, ip: Optional[str]) -> EquipmentMaintenance:
    job, eq = _lock_job_and_equipment(db, job_id)
    _require_open(job, "cancelled")
    old_job, old_eq = _snapshot(job), _equipment_snapshot(eq)
    other = _other_in_progress(db, eq.id, job.id)
    eq.status = next_equipment_status(job.maintenance_type, job.status, "cancelled", other, eq.status)
    job.status = "cancelled"
    if data.reason:
        job.description = f"{job.description} | Cancelled: {data.reason}" if job.description else f"Cancelled: {data.reason}"
    log_action(db, user_id=actor.id, action="maintenance.cancel", entity_type="maintenance", entity_id=job.id,
               old={**old_job, "equipment": old_eq},
               new={**_snapshot(job), "equipment": _equipment_snapshot(eq), "reason": data.reason}, ip=ip)
    db.commit()
    return get_job(db, job.id)


# ------------------------------------------------------------------ history
def list_jobs(db: Session, user: User, *, equipment_id: Optional[int], status: Optional[str],
              maintenance_type: Optional[str], overdue: bool, search: Optional[str],
              date_from: Optional[date], date_to: Optional[date], order: str, page: int, page_size: int):
    today, admin = gym_today(), equipment_service.is_admin(user)
    conditions = []
    if equipment_id is not None:
        conditions.append(EquipmentMaintenance.equipment_id == equipment_id)
    if status:
        conditions.append(EquipmentMaintenance.status == status)
    if maintenance_type:
        conditions.append(EquipmentMaintenance.maintenance_type == maintenance_type)
    if overdue:
        conditions += [EquipmentMaintenance.status == "scheduled", EquipmentMaintenance.scheduled_date < today]
    if date_from:
        conditions.append(EquipmentMaintenance.scheduled_date >= date_from)
    if date_to:
        conditions.append(EquipmentMaintenance.scheduled_date <= date_to)
    if search and search.strip():
        pattern = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append(or_(Equipment.name.ilike(pattern, escape="\\"),
                              Equipment.equipment_code.ilike(pattern, escape="\\")))
    if date_from and date_to and date_to < date_from:
        raise BadRequestError("'date_to' must not be before 'date_from'")

    def joined(stmt):
        stmt = stmt.join(Equipment, Equipment.id == EquipmentMaintenance.equipment_id)
        return stmt.where(*conditions) if conditions else stmt

    total = db.scalar(joined(select(func.count(EquipmentMaintenance.id)))) or 0
    total_cost = None
    if admin:
        total_cost = Decimal(db.scalar(joined(select(func.coalesce(func.sum(EquipmentMaintenance.cost), 0))
                                              .where(EquipmentMaintenance.status == "completed"))) or 0
                             ).quantize(Decimal("0.01"))
    date_order = EquipmentMaintenance.scheduled_date.asc() if order == "asc" else EquipmentMaintenance.scheduled_date.desc()
    id_order = EquipmentMaintenance.id.asc() if order == "asc" else EquipmentMaintenance.id.desc()
    jobs = db.scalars(joined(select(EquipmentMaintenance)).options(*LOADERS)
                      .order_by(date_order, id_order).offset((page - 1) * page_size).limit(page_size)).all()
    return [equipment_service.job_out(j, today, admin) for j in jobs], total, total_cost


# ------------------------------------------------------------------ reminders
def reminders(db: Session, days_override: Optional[int]) -> RemindersOut:
    today, days = gym_today(), equipment_service.alert_days(db, days_override)
    items = list(db.scalars(select(Equipment).where(Equipment.is_archived.is_(False))).all())
    due_map = equipment_service.due_dates_for(db, [e.id for e in items])

    urgent, soon = [], []
    for eq in items:
        u = equipment_service.urgency_for(eq, due_map, today, days)
        if u.level == "ok":
            continue
        entry = ReminderItem(equipment=equipment_service.brief(eq), level=u.level, code=u.code,
                             message=u.message, due_date=u.due_date)
        (urgent if u.level == "urgent" else soon).append(entry)

    # damaged items first, then the longest-overdue; soon items by due date
    urgent.sort(key=lambda r: (r.code != "damaged", r.due_date or date.max, r.equipment.id))
    soon.sort(key=lambda r: (r.due_date or date.max, r.equipment.id))
    return RemindersOut(alert_days=days, urgent_count=len(urgent), soon_count=len(soon), urgent=urgent, soon=soon)
