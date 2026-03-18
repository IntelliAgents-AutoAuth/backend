from enum import Enum

class CaseStatus(str, Enum):
    DRAFT                  = "DRAFT"
    EHR_FETCHING           = "EHR_FETCHING"
    EHR_FETCHED            = "EHR_FETCHED"
    GAP_ANALYSIS_RUNNING   = "GAP_ANALYSIS_RUNNING"
    GAP_FOUND              = "GAP_FOUND"
    GAP_CLEARED            = "GAP_CLEARED"
    ELIGIBILITY_RUNNING    = "ELIGIBILITY_RUNNING"
    ELIGIBLE               = "ELIGIBLE"
    NOT_ELIGIBLE           = "NOT_ELIGIBLE"
    PACKET_GENERATING      = "PACKET_GENERATING"
    PACKET_READY           = "PACKET_READY"
    PENDING_APPROVAL       = "PENDING_APPROVAL"
    SUBMITTED              = "SUBMITTED"
    TRACKING               = "TRACKING"
    APPROVED               = "APPROVED"
    DENIED                 = "DENIED"
    FAILED                 = "FAILED"
    GAP_ANALYSIS_FAILED    = "GAP_ANALYSIS_FAILED"  # Keeping this as fallback

class CasePriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    EMERGENT = "EMERGENT"

class PlaceOfService(str, Enum):
    INPATIENT = "INPATIENT"
    OUTPATIENT = "OUTPATIENT"
    OFFICE = "OFFICE"
