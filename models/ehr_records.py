from sqlalchemy import Column, String, Text, DateTime, JSON
from datetime import datetime, timezone
from db.base_class import Base

class EHR(Base):
    __tablename__ = "ehr_records"

    # Primary Key
    patient_id          = Column(String,   primary_key=True)

    # Patient Demographics
    patient_first_name  = Column(String,   nullable=False)
    patient_last_name   = Column(String,   nullable=False)
    date_of_birth       = Column(String,   nullable=False)
    gender              = Column(String,   nullable=False)

    # Insurance
    insurance_company   = Column(String,   nullable=False)
    member_id           = Column(String,   nullable=True)
    policy_number       = Column(String,   nullable=True)
    group_number        = Column(String,   nullable=True)
    plan_name           = Column(String,   nullable=True)

    # Clinical
    icd10_code          = Column(String,   nullable=True)
    diagnosis           = Column(String,   nullable=True)
    cpt_code            = Column(String,   nullable=True)
    procedure_name      = Column(String,   nullable=True)

    # Physician
    physician_name      = Column(String,   nullable=True)
    physician_npi       = Column(String,   nullable=True)
    physician_specialty = Column(String,   nullable=True)
    facility_name       = Column(String,   nullable=True)

    # Lab Results
    lab_results         = Column(JSON,     default=dict)

    # Timestamps
    created_at          = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at          = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "patient_id": self.patient_id,
            "patient_first_name": self.patient_first_name,
            "patient_last_name": self.patient_last_name,
            "date_of_birth": self.date_of_birth,
            "gender": self.gender,
            "insurance_company": self.insurance_company,
            "member_id": self.member_id,
            "policy_number": self.policy_number,
            "group_number": self.group_number,
            "plan_name": self.plan_name,
            "icd10_code": self.icd10_code,
            "diagnosis": self.diagnosis,
            "cpt_code": self.cpt_code,
            "procedure_name": self.procedure_name,
            "physician_name": self.physician_name,
            "physician_npi": self.physician_npi,
            "physician_specialty": self.physician_specialty,
            "facility_name": self.facility_name,
            "lab_results": self.lab_results,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
