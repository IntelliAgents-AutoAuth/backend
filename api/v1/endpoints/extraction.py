from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from api.deps import get_db
from core.security import get_current_user
from models.user import User
from services import extraction_service
from schemas.extracted_data import ExtractedData as ExtractedDataSchema

router = APIRouter(prefix="/extraction", tags=["extraction"])

class ExtractionFromEHR(BaseModel):
    patient_id: str
    case_id: str

@router.post("/from-ehr", response_model=ExtractedDataSchema)
async def extract_from_ehr(
    data_in: ExtractionFromEHR,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch patient details from EHR and pre-populate the Extracted Data for a case.
    """
    db_extracted = extraction_service.fill_extracted_data_from_ehr(
        db, 
        patient_id=data_in.patient_id, 
        case_id=data_in.case_id
    )
    if not db_extracted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"EHR record for patient {data_in.patient_id} not found."
        )
    return db_extracted
