from pydantic import BaseModel, ConfigDict
from datetime import datetime, date
from typing import Optional, List, Any, Dict

class ExtractedDataBase(BaseModel):
    patient_id: Optional[str] = None
    patient_first_name: Optional[str] = None
    patient_last_name: Optional[str] = None
    patient_dob: Optional[date] = None
    patient_gender: Optional[str] = None
    payer_name: Optional[str] = None
    member_id: Optional[str] = None
    policy_number: Optional[str] = None
    group_number: Optional[str] = None
    plan_name: Optional[str] = None
    physician_name: Optional[str] = None
    physician_npi: Optional[str] = None
    physician_specialty: Optional[str] = None
    facility_name: Optional[str] = None
    primary_icd10_code: Optional[str] = None
    primary_diagnosis: Optional[str] = None
    cpt_code: Optional[str] = None
    lab_results: Optional[Dict[str, Any]] = None
    bnp_level: Optional[float] = None
    soap_subjective: Optional[str] = None
    soap_objective: Optional[str] = None
    soap_assessment: Optional[str] = None
    soap_plan: Optional[str] = None
    clinical_justification: Optional[str] = None
    medication_name: Optional[str] = None
    treatment_duration_weeks: Optional[int] = None
    treatment_failed: Optional[bool] = None
    lvef_percent: Optional[float] = None
    lvef_from_echo: Optional[float] = None
    echo_date: Optional[date] = None
    echo_report_summary: Optional[str] = None
    lvef_below_40: Optional[bool] = None
    bypass_condition_met: Optional[bool] = None
    bypass_reason: Optional[str] = None
    auto_approval_triggered: Optional[bool] = None
    confidence_overall: Optional[float] = None
    ehr_filled_at: Optional[datetime] = None
    ai_filled_at: Optional[datetime] = None

class ExtractedDataCreate(ExtractedDataBase):
    case_id: str

class ExtractedDataUpdate(ExtractedDataBase):
    pass

class ExtractedData(ExtractedDataBase):
    case_id: str
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
