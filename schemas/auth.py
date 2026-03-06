from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class LoginRequest(BaseModel):
    """Request body for login endpoint."""
    username: str
    password: str

class UserInfo(BaseModel):
    name: str
    email: str
    role: str

class Token(BaseModel):
    """Response body for token."""
    access_token: str
    token_type: str = "bearer"
    user: Optional[UserInfo] = None

class Case(BaseModel):
    """Schema for a case."""
    case_id: str
    status: str
    priority: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    audit_log: str
    patient_id: str
    patient_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    insurance_company: str
    member_id: Optional[str] = None
    group_number: Optional[str] = None
    plan_name: Optional[str] = None
    icd10_code: Optional[str] = None
    diagnosis: Optional[str] = None
    diagnosis_date: Optional[str] = None
    cpt_code: str
    procedure_name: Optional[str] = None
    procedure_date: Optional[str] = None
    place_of_service: Optional[str] = None
    physician_name: Optional[str] = None
    physician_npi: Optional[str] = None
    physician_specialty: Optional[str] = None
    physician_phone: Optional[str] = None
    facility_name: Optional[str] = None
    lab_results: str
    assigned_to: Optional[str] = None

    class Config:
        from_attributes = True
