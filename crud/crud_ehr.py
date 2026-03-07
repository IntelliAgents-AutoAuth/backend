from sqlalchemy.orm import Session
from models.ehr_records import EHR

def get_ehr(db: Session, patient_id: str):
    """
    Fetch a single EHR record by patient_id.
    """
    return db.query(EHR).filter(EHR.patient_id == patient_id).first()
