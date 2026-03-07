from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, Dict, Any

class EHRBase(BaseModel):
    patient_id: str
    patient_first_name: str
    patient_last_name: str
    date_of_birth: str
    gender: str
    insurance_company: str
    member_id: Optional[str] = None
    policy_number: Optional[str] = None
    group_number: Optional[str] = None
    plan_name: Optional[str] = None
    icd10_code: Optional[str] = None
    diagnosis: Optional[str] = None
    cpt_code: Optional[str] = None
    procedure_name: Optional[str] = None
    physician_name: Optional[str] = None
    physician_npi: Optional[str] = None
    physician_specialty: Optional[str] = None
    facility_name: Optional[str] = None
    lab_results: Dict[str, Any] = {}

class EHRCreate(EHRBase):
    pass

class EHRUpdate(EHRBase):
    patient_id: Optional[str] = None
    patient_first_name: Optional[str] = None
    patient_last_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    insurance_company: Optional[str] = None

class EHR(EHRBase):
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
