from sqlalchemy.orm import Session
from datetime import datetime, timezone, date
from typing import Optional
import json

from crud import crud_ehr, crud_extracted_data
from schemas.extracted_data import ExtractedDataCreate, ExtractedDataUpdate
from models.extracted_data import ExtractedData

def fill_extracted_data_from_ehr(db: Session, patient_id: str, case_id: str):
    """
    Fetches details from EHR and populates/updates ExtractedData for a given case.
    """
    # 1. Fetch EHR Record
    db_ehr = crud_ehr.get_ehr(db, patient_id=patient_id)
    if not db_ehr:
        return None

    # 2. Prepare Data Mapping
    # Convert string date to date object if needed (EHR model uses String for DOB, ExtractedData uses Date)
    dob = None
    if db_ehr.date_of_birth:
        try:
            dob = datetime.strptime(db_ehr.date_of_birth, "%Y-%m-%d").date()
        except ValueError:
            pass

    # Extract BNP level from lab_results JSON if it exists
    bnp_level = None
    if db_ehr.lab_results and isinstance(db_ehr.lab_results, dict):
        bnp_info = db_ehr.lab_results.get("BNP", {})
        if isinstance(bnp_info, dict):
            val = bnp_info.get("value")
            if val:
                try:
                    bnp_level = float(val)
                except ValueError:
                    pass

    # 3. Create or Update ExtractedData
    existing_data = crud_extracted_data.get_extracted_data(db, case_id=case_id)
    
    extraction_in = {
        "patient_id": db_ehr.patient_id,
        "patient_first_name": db_ehr.patient_first_name,
        "patient_last_name": db_ehr.patient_last_name,
        "patient_dob": dob,
        "patient_gender": db_ehr.gender,
        "payer_name": db_ehr.insurance_company,
        "member_id": db_ehr.member_id,
        "policy_number": db_ehr.policy_number,
        "group_number": db_ehr.group_number,
        "plan_name": db_ehr.plan_name,
        "physician_name": db_ehr.physician_name,
        "physician_npi": db_ehr.physician_npi,
        "physician_specialty": db_ehr.physician_specialty,
        "facility_name": db_ehr.facility_name,
        "primary_icd10_code": db_ehr.icd10_code,
        "primary_diagnosis": db_ehr.diagnosis,
        "cpt_code": db_ehr.cpt_code,
        "lab_results": db_ehr.lab_results,
        "bnp_level": bnp_level,
        "ehr_filled_at": datetime.now(timezone.utc)
    }

    if existing_data:
        update_schema = ExtractedDataUpdate(**extraction_in)
        return crud_extracted_data.update_extracted_data(db, db_obj=existing_data, obj_in=update_schema)
    else:
        extraction_in["case_id"] = case_id
        create_schema = ExtractedDataCreate(**extraction_in)
        return crud_extracted_data.create_extracted_data(db, obj_in=create_schema)
