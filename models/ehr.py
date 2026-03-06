"""
EHR Table Model
Location: backend/models/ehr.py
"""

import json
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime
from db.base_class import Base


class EHR(Base):
    __tablename__ = "ehrs"

    # ── PA Case Tracking ──────────────────────
    case_id             = Column(String,   primary_key=True)        # PA-YYYYMMDD-XXXX
    status              = Column(String,   nullable=False, default="DRAFT")
    priority            = Column(String,   nullable=False, default="ROUTINE")  # ROUTINE / URGENT / EMERGENT
    created_at          = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at          = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
                                           onupdate=lambda: datetime.now(timezone.utc))
    audit_log           = Column(Text,     nullable=False, default="[]")       # JSON array
    assigned_to         = Column(String,   nullable=True)                      # User email

    # ── Patient Demographics ──────────────────
    patient_id          = Column(String,   nullable=False)
    patient_name        = Column(String)
    date_of_birth       = Column(String)
    gender              = Column(String)

    # ── Insurance / Payer ─────────────────────
    insurance_company   = Column(String,   nullable=False)
    member_id           = Column(String)
    group_number        = Column(String)
    plan_name           = Column(String)

    # ── Clinical — Diagnosis ──────────────────
    icd10_code          = Column(String)
    diagnosis           = Column(String)
    diagnosis_date      = Column(String)

    # ── Clinical — Procedure ──────────────────
    cpt_code            = Column(String,   nullable=False)
    procedure_name      = Column(String)
    procedure_date      = Column(String)
    place_of_service    = Column(String)   # INPATIENT / OUTPATIENT / OFFICE

    # ── Ordering Physician ────────────────────
    physician_name      = Column(String)
    physician_npi       = Column(String)
    physician_specialty = Column(String)
    physician_phone     = Column(String)
    facility_name       = Column(String)

    # ── Lab Results ───────────────────────────
    lab_results         = Column(Text, default="{}")                # JSON object

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────
    def get_audit_log(self) -> list:
        return json.loads(self.audit_log or "[]")

    def get_lab_results(self) -> dict:
        return json.loads(self.lab_results or "{}")

    def to_dict(self) -> dict:
        return {
            "case_id":            self.case_id,
            "status":             self.status,
            "priority":           self.priority,
            "created_at":         self.created_at.isoformat() if self.created_at else None,
            "updated_at":         self.updated_at.isoformat() if self.updated_at else None,
            "patient_id":         self.patient_id,
            "patient_name":       self.patient_name,
            "date_of_birth":      self.date_of_birth,
            "gender":             self.gender,
            "insurance_company":  self.insurance_company,
            "member_id":          self.member_id,
            "group_number":       self.group_number,
            "plan_name":          self.plan_name,
            "icd10_code":         self.icd10_code,
            "diagnosis":          self.diagnosis,
            "diagnosis_date":     self.diagnosis_date,
            "cpt_code":           self.cpt_code,
            "procedure_name":     self.procedure_name,
            "procedure_date":     self.procedure_date,
            "place_of_service":   self.place_of_service,
            "physician_name":     self.physician_name,
            "physician_npi":      self.physician_npi,
            "physician_specialty":self.physician_specialty,
            "physician_phone":    self.physician_phone,
            "facility_name":      self.facility_name,
            "lab_results":        self.get_lab_results(),
            "audit_log":          self.get_audit_log(),
            "assigned_to":        self.assigned_to,
        }
