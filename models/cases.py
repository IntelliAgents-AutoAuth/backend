from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Integer, Float
from datetime import datetime, timezone
from db.base_class import Base
from constants.cases import CaseStatus

class Case(Base):
    __tablename__ = "cases"
    case_id           = Column(String(30), primary_key=True)
    patient_name      = Column(String(150), nullable=True)
    patient_id        = Column(String(50), nullable=False)
    status            = Column(String(30), nullable=False, default=CaseStatus.DRAFT.value)
    created_by        = Column(String(50), ForeignKey("user.email"), nullable=False)
    created_at        = Column(DateTime,   nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at        = Column(DateTime,   nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    insurance_company = Column(String(150), nullable=True)
    cpt_code          = Column(String(20),  nullable=True)
    icd10_code        = Column(String(20),  nullable=True)
    gap_result        = Column(JSON,         nullable=True)
    total_required   = Column(Integer,      nullable=True)
    total_matched    = Column(Integer,      nullable=True)
    total_missing    = Column(Integer,      nullable=True)
    gap_percentage    = Column(Float,        nullable=True)
    eligibility_result = Column(JSON,         nullable=True)
    eligibility_verdict = Column(String(30),  nullable=True)
    uploaded_files    = Column(JSON,         nullable=True)
    audit_log         = Column(JSON,         nullable=False, default=list)
