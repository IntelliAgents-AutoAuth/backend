"""
Unified Database & CRUD Module — Persistence Architecture
==========================================================

This module is the central interface for all database interactions in the 
IntelliAgents platform. It handles the 'Plumbing' of connection pooling 
and provides a clean API for CRUD (Create, Read, Update, Delete) operations.

Key Patterns:
-------------
1. **Engine Setup**: Manages the SQLAlchemy engine for the local SQLite 
   database. It includes a specific Pragma for the connection to enable 
   Foreign Key constraints in SQLite.
2. **Session Management**: Provides 'SessionLocal' for high-performance 
   synchronous DB access within FastAPI dependencies and AI agents.
3. **Circular Import Prevention**: Models are imported locally within 
   functions. This is a critical architectural decision that allows models 
   to reference each other without causing Python import errors.
4. **Smart Case ID Generation**: Implements a sequence-based ID generator 
   (PA-YYYYMMDD-XXXXX) that is human-readable and sorts chronologically.
"""

from typing import Any
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from core.config import settings
from constants import CaseStatus
from .base import Base

# ─────────────────────────────────────────────────────────────────────────────
# 1. ENGINE & SESSION CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False}
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. USER CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_user_by_email(db: Session, email: str):
    """Fetch a user record from the database by email."""
    from models.user import User
    return db.query(User).filter(User.email == email).first()

# ─────────────────────────────────────────────────────────────────────────────
# 3. CASE CRUD
# ─────────────────────────────────────────────────────────────────────────────

def generate_case_id(db: Session):
    """
    Generate a case ID in the format PA-YYYYMMDD-XXXXX.
    Finds the max sequence number for today to determine the next number.
    """
    from models.cases import Case
    import datetime
    today = datetime.date.today()
    date_str = today.strftime("%Y%m%d")
    prefix = f"PA-{date_str}-"
    
    max_case = db.query(Case).filter(Case.case_id.like(f"{prefix}%")).order_by(Case.case_id.desc()).first()
    
    if max_case:
        try:
            last_serial = int(max_case.case_id.split("-")[-1])
            new_serial = last_serial + 1
        except (ValueError, IndexError):
            new_serial = 1
    else:
        new_serial = 1
    
    return f"{prefix}{new_serial:05d}"

def create_case(db: Session, case_in: Any, created_by: str):
    """Create a new case with an auto-generated ID and draft status."""
    from models.cases import Case
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
    from models.cases import Case
    return db.query(Case).filter(Case.case_id == case_id).first()

def get_cases(db: Session, skip: int = 0, limit: int = 100):
    """Get a list of cases."""
    from models.cases import Case
    return db.query(Case).offset(skip).limit(limit).all()

# ─────────────────────────────────────────────────────────────────────────────
# 4. EHR CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_ehr(db: Session, patient_id: str):
    """Fetch a single EHR record by patient_id."""
    from models.ehr_records import EHR
    return db.query(EHR).filter(EHR.patient_id == patient_id).first()

# ─────────────────────────────────────────────────────────────────────────────
# 5. EXTRACTED DATA CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_extracted_data(db: Session, case_id: str):
    from models.extracted_data import ExtractedData
    return db.query(ExtractedData).filter(ExtractedData.case_id == case_id).first()

def create_extracted_data(db: Session, obj_in: Any):
    from models.extracted_data import ExtractedData
    db_obj = ExtractedData(**obj_in.model_dump())
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def update_extracted_data(db: Session, db_obj: Any, obj_in: Any):
    obj_data = db_obj.to_dict() if hasattr(db_obj, 'to_dict') else {c.name: getattr(db_obj, c.name) for c in db_obj.__table__.columns}
    update_data = obj_in.model_dump(exclude_unset=True)
    for field in obj_data:
        if field in update_data:
            setattr(db_obj, field, update_data[field])
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj
