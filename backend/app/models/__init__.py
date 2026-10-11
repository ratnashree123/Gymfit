"""Import every model here so SQLAlchemy knows about all tables and relationships."""
from app.models.attendance import Attendance
from app.models.equipment import Equipment, EquipmentMaintenance
from app.models.fitness import MemberProgress, WorkoutExercise, WorkoutPlan
from app.models.member import Member
from app.models.membership import Invoice, Membership, MembershipPlan, Payment
from app.models.system import AuditLog, GymSetting, Notification
from app.models.user import Role, StaffProfile, User

__all__ = [
    "Attendance", "AuditLog", "Equipment", "EquipmentMaintenance", "GymSetting",
    "Invoice", "Member", "MemberProgress", "Membership", "MembershipPlan",
    "Notification", "Payment", "Role", "StaffProfile", "User",
    "WorkoutExercise", "WorkoutPlan",
]
