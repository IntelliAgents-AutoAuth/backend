from fastapi import APIRouter, Depends, HTTPException
import json
import asyncio
import random
from datetime import datetime, timezone
from typing import List
from sqlalchemy.orm import Session
from schemas.auth import Case as CaseSchema, CaseCreate
from models.case import Case
from models.user import User
from core.security import get_current_user
from api.deps import get_db
from mock_data.ehrData import MOCK_EHR_CASES

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("/", response_model=CaseSchema)
async def create_case(
    case_in: CaseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new DRAFT case."""
    now = datetime.now(timezone.utc)
    case_id = f"PA-{now.strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    
    new_case = Case(
        case_id=case_id,
        status="DRAFT",
        priority="ROUTINE",
        patient_id=case_in.patientName,
        cpt_code=case_in.cptCode,
        insurance_company=case_in.insuranceName,
        assigned_to=current_user.email,
        audit_log=json.dumps([
            {"timestamp": now.isoformat(), "action": "CREATED", "user": current_user.email}
        ])
    )
    
    db.add(new_case)
    db.commit()
    db.refresh(new_case)
    return new_case


@router.get("/", response_model=List[CaseSchema])
async def list_cases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all cases assigned to the authenticated user. Seeds from mock data if DB is empty."""
    # Seed mock data if cases table is empty
    if db.query(Case).count() == 0:
        for mock_case in MOCK_EHR_CASES:
            case_data = mock_case.copy()
            # Assign explicitly to current user so it displays on their dashboard
            case_data["assigned_to"] = current_user.email
            new_case = Case(**case_data)
            db.add(new_case)
        db.commit()

    user_cases = db.query(Case).filter(
        Case.assigned_to == current_user.email
    ).all()
    return user_cases


@router.get("/{case_id}", response_model=CaseSchema)
async def get_case(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a single case by its ID"""
    db_case = db.query(Case).filter(
        Case.case_id == case_id,
        Case.assigned_to == current_user.email
    ).first()
    
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")
        
    return db_case


@router.post("/{case_id}/sync", response_model=CaseSchema)
async def sync_ehr(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sync a case with EHR system data (Mock File 1)."""
    db_case = db.query(Case).filter(
        Case.case_id == case_id,
        Case.assigned_to == current_user.email
    ).first()
    
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")
        
    audit_log = db_case.get_audit_log()
    
    # Log: Query started
    audit_log.append({"timestamp": datetime.now(timezone.utc).isoformat(), "action": "ehr_query_started", "user": "SYSTEM"})
    db_case.audit_log = json.dumps(audit_log)
    db.commit()
    
    # Simulated query delay
    await asyncio.sleep(2.5)
    
    mock_data = MOCK_EHR_CASES[0]
    
    db_case.patient_name = mock_data.get("patient_name")
    db_case.date_of_birth = mock_data.get("date_of_birth")
    db_case.gender = mock_data.get("gender")
    db_case.insurance_company = mock_data.get("insurance_company")
    db_case.member_id = mock_data.get("member_id")
    db_case.group_number = mock_data.get("group_number")
    db_case.plan_name = mock_data.get("plan_name")
    db_case.icd10_code = mock_data.get("icd10_code")
    db_case.diagnosis = mock_data.get("diagnosis")
    db_case.diagnosis_date = mock_data.get("diagnosis_date")
    db_case.procedure_name = mock_data.get("procedure_name")
    db_case.procedure_date = mock_data.get("procedure_date")
    db_case.place_of_service = mock_data.get("place_of_service")
    db_case.physician_name = mock_data.get("physician_name")
    db_case.physician_npi = mock_data.get("physician_npi")
    db_case.physician_specialty = mock_data.get("physician_specialty")
    db_case.physician_phone = mock_data.get("physician_phone")
    db_case.facility_name = mock_data.get("facility_name")
    db_case.lab_results = mock_data.get("lab_results", "{}")
    db_case.status = "EHR_RETRIEVED"
    
    # Log: Query completed
    audit_log.append({"timestamp": datetime.now(timezone.utc).isoformat(), "action": "ehr_query_completed", "user": "SYSTEM"})
    db_case.audit_log = json.dumps(audit_log)
    
    db.commit()
    db.refresh(db_case)
    return db_case
