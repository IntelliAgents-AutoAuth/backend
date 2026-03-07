from enum import Enum

class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PENDING_REVIEW = "PENDING_REVIEW"
    DENIED = "DENIED"

class CasePriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    EMERGENT = "EMERGENT"

class PlaceOfService(str, Enum):
    INPATIENT = "INPATIENT"
    OUTPATIENT = "OUTPATIENT"
    OFFICE = "OFFICE"
