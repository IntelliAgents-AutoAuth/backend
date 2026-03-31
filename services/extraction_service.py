"""
EHR Extraction Service

Populates the extracted_data table with EHR records when a new case is created.
"""

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from crud.crud_ehr import get_ehr
from crud.crud_extracted_data import create_extracted_data, get_extracted_data
from crud.crud_case import get_case
from schemas.extracted_data import ExtractedDataCreate


def fill_extracted_data_from_ehr(db: Session, patient_id: str, case_id: str) -> None:
    """
    Look up the EHR record for *patient_id* and create an ExtractedData row
    linked to *case_id*.  Does nothing if the EHR record cannot be found or if
    an ExtractedData row already exists for this case.
    """
    # Skip if already populated
    if get_extracted_data(db, case_id):
        return

    ehr = get_ehr(db, patient_id)
    if not ehr:
        # Fallback for demo data: Allow PA- prefix to match PT- records
        if patient_id.startswith("PA-"):
            fallback_id = "PT-" + patient_id[3:]
            print(f"[extraction_service] ID {patient_id} not found. Trying fallback: {fallback_id}")
            ehr = get_ehr(db, fallback_id)
            
    if not ehr:
        print(f"[extraction_service] No EHR record found for patient_id={patient_id!r}")
        return

    payload = ExtractedDataCreate(
        case_id=case_id,
        patient_id=ehr.patient_id,
        patient_first_name=ehr.patient_first_name,
        patient_last_name=ehr.patient_last_name,
        patient_dob=ehr.date_of_birth,
        patient_gender=ehr.gender,
        payer_name=ehr.insurance_company,
        member_id=ehr.member_id,
        policy_number=ehr.policy_number,
        group_number=ehr.group_number,
        plan_name=ehr.plan_name,
        physician_name=ehr.physician_name,
        physician_npi=ehr.physician_npi,
        physician_specialty=ehr.physician_specialty,
        facility_name=ehr.facility_name,
        primary_icd10_code=ehr.icd10_code,
        primary_diagnosis=ehr.diagnosis,
        cpt_code=ehr.cpt_code,
        lab_results=ehr.lab_results,
        ehr_filled_at=datetime.now(timezone.utc),
    )

    print(f"[extraction_service] --- Data Extraction Started for {case_id} ---")
    create_extracted_data(db, payload)

    # ─────────────────────────────────────────────────────────
    # SYNC TO CASE (Crucial for Orchestrator & Agents)
    # ─────────────────────────────────────────────────────────
    db_case = get_case(db, case_id)
    if db_case:
        updated = False
        if not db_case.insurance_company and ehr.insurance_company:
            db_case.insurance_company = ehr.insurance_company
            updated = True
        if not db_case.cpt_code and ehr.cpt_code:
            db_case.cpt_code = ehr.cpt_code
            updated = True
        if not db_case.icd10_code and ehr.icd10_code:
            db_case.icd10_code = ehr.icd10_code
            updated = True
        if not db_case.patient_name and (ehr.patient_first_name or ehr.patient_last_name):
            db_case.patient_name = f"{ehr.patient_first_name} {ehr.patient_last_name}".strip()
            updated = True
            
        if updated:
            db.add(db_case)
            db.commit()
            print(f"[extraction_service] Synced EHR metadata to Case {case_id}")

    print(f"[extraction_service] --- Data Extraction Completed for {case_id} ---")
