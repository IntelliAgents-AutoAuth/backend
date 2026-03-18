from sqlalchemy import Column, String, Float, Boolean, Text, DateTime, JSON, ForeignKey, Date, Integer
from datetime import datetime, timezone
from db.base_class import Base

class ExtractedData(Base):
    __tablename__ = "extracted_data"

    # Primary Key and Foreign Key
    case_id                   = Column(String(30), ForeignKey("cases.case_id", ondelete="CASCADE"), primary_key=True)

    # ── From EHR (filled at Step 3) ────────────────────────
    patient_id                = Column(String(50),  nullable=True)
    patient_first_name        = Column(String(100), nullable=True)
    patient_last_name         = Column(String(100), nullable=True)
    patient_dob               = Column(Date,        nullable=True)
    patient_gender            = Column(String(20),  nullable=True)

    payer_name                = Column(String(150), nullable=True)
    member_id                 = Column(String(100), nullable=True)
    policy_number             = Column(String(100), nullable=True)
    group_number              = Column(String(100), nullable=True)
    plan_name                 = Column(String(150), nullable=True)

    physician_name            = Column(String(150), nullable=True)
    physician_npi             = Column(String(20),  nullable=True)
    physician_specialty       = Column(String(100), nullable=True)
    facility_name             = Column(String(150), nullable=True)

    primary_icd10_code        = Column(String(20),  nullable=True)
    primary_diagnosis         = Column(String(255), nullable=True)
    cpt_code                  = Column(String(20),  nullable=True)

    lab_results               = Column(JSON,         nullable=True)
    bnp_level                 = Column(Float,        nullable=True)

    # ── From Uploaded Docs (filled at Step 6) ──────────────
    soap_subjective           = Column(Text,         nullable=True)
    soap_objective            = Column(Text,         nullable=True)
    soap_assessment           = Column(Text,         nullable=True)
    soap_plan                 = Column(Text,         nullable=True)
    clinical_justification    = Column(Text,         nullable=True)

    medication_name           = Column(String(150), nullable=True)
    treatment_duration_weeks  = Column(Integer,      nullable=True)
    treatment_failed          = Column(Boolean,      nullable=True)

    lvef_percent              = Column(Float,        nullable=True)
    lvef_from_echo            = Column(Float,        nullable=True)
    echo_date                 = Column(Date,         nullable=True)
    echo_report_summary       = Column(Text,         nullable=True)

    # ── Calculated by Extraction Agent ─────────────────────
    lvef_below_40             = Column(Boolean,      nullable=True)
    bypass_condition_met      = Column(Boolean,      nullable=True)
    bypass_reason             = Column(Text,         nullable=True)
    auto_approval_triggered   = Column(Boolean,      nullable=True)
    confidence_overall        = Column(Float,        nullable=True)

    # ── Timestamps ─────────────────────────────────────────
    ehr_filled_at             = Column(DateTime,     nullable=True)
    ai_filled_at              = Column(DateTime,     nullable=True)
    created_at                = Column(DateTime,     nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at                = Column(DateTime,     nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
