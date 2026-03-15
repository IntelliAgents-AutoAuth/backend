from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Any, Dict

class CaseCreate(BaseModel):
    """Schema for creating a new case."""
    patient_id: str
    insurance_company: Optional[str] = None
    icd10_code: Optional[str] = None
    cpt_code: Optional[str] = None

class Case(BaseModel):
    """Schema for a case response."""
    case_id: str
    patient_id: str
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    insurance_company: Optional[str] = None
    cpt_code: Optional[str] = None
    icd10_code: Optional[str] = None
    gap_result: Optional[Dict[str, Any]] = None
    total_required: Optional[int] = None
    total_matched: Optional[int] = None
    total_missing: Optional[int] = None
    gap_percentage: Optional[float] = None
    uploaded_files: Optional[List[Dict[str, Any]]] = None
    # EHR Fields (Merged from ExtractedData)
    patient_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    physician_name: Optional[str] = None
    physician_npi: Optional[str] = None
    physician_specialty: Optional[str] = None
    facility_name: Optional[str] = None
    diagnosis: Optional[str] = None
    procedure_name: Optional[str] = None
    lab_results: Optional[Dict[str, Any]] = None
    audit_log: List[Dict[str, Any]]

    class Config:
        from_attributes = True

# Alias for compatibility if needed
EHR = Case
