from sqlalchemy.orm import Session
from models.cases import Case
from schemas.cases import CaseCreate
from constants.cases import CaseStatus

import datetime
from sqlalchemy import func

def generate_case_id(db: Session):
    """
    Generate a case ID in the format PA-YYYYMMDD-XXXXX.
    Counts cases created today to determine the next number.
    """
    today = datetime.date.today()
    date_str = today.strftime("%Y%m%d")
    prefix = f"PA-{date_str}-"
    
    # Count how many cases were created today
    count = db.query(Case).filter(Case.case_id.like(f"{prefix}%")).count()
    new_serial = count + 1
    
    return f"{prefix}{new_serial:05d}"

def create_case(db: Session, case_in: CaseCreate, created_by: str):
    """Create a new case with an auto-generated ID and draft status."""
    case_id = generate_case_id(db)
    db_case = Case(
        case_id=case_id,
        patient_id=case_in.patient_id,
        status=CaseStatus.DRAFT.value,
        created_by=created_by,
        insurance_company=case_in.insurance_company or "",
        icd10_code=case_in.icd10_code or "",
        cpt_code=case_in.cpt_code or "",
        audit_log=[] 
    )
    db.add(db_case)
    db.commit()
    db.refresh(db_case)
    return db_case

def get_case(db: Session, case_id: str):
    """Get a case by its ID."""
    return db.query(Case).filter(Case.case_id == case_id).first()

def get_cases(db: Session, skip: int = 0, limit: int = 100):
    """Get a list of cases."""
    return db.query(Case).offset(skip).limit(limit).all()
