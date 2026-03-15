from fastapi import APIRouter, Depends, HTTPException, status
import traceback
from typing import List
from sqlalchemy.orm import Session
from schemas.cases import Case as CaseSchema, CaseCreate
from models.cases import Case
from models.user import User
from core.security import get_current_user
from api.deps import get_db
from crud import crud_case
from services.extraction_service import fill_extracted_data_from_ehr
from agents.gap_analysis_agent import run_gap_analysis


router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CaseSchema)
async def create_new_case(
    case_in: CaseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new case with automatic ID and draft status."""
    db_case = crud_case.create_case(db, case_in=case_in, created_by=current_user.email)
    
    # Trigger EHR fetch immediately after creation
    try:
        fill_extracted_data_from_ehr(
            db,
            patient_id=db_case.patient_id,
            case_id=db_case.case_id
        )
        # Also trigger Gap Analysis
        print(f"[cases_endpoint] Triggering Gap Analysis for case: {db_case.case_id}...")
        gap_result = run_gap_analysis({
            "case_id": db_case.case_id,
            "patient_name": f"Patient {db_case.patient_id}", # We might want real name here
            "pdf_path": None # Uses default
        })
        print(f"[cases_endpoint] Gap Analysis triggered. Result output: {gap_result.get('output', 'No output')[:100]}...")
    except Exception as e:
        print(f"[cases_endpoint] Failed to trigger initial processing for case {db_case.case_id}: {e}")
        traceback.print_exc()
        
    return db_case


@router.get("", response_model=List[CaseSchema])
async def list_cases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all cases."""
    # Note: Depending on requirements, we might filter by created_by here
    return crud_case.get_cases(db)


@router.get("/{case_id}", response_model=CaseSchema)
async def get_case_details(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch details of a specific case."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found"
        )
    return db_case

@router.post("/{case_id}/sync", response_model=CaseSchema)
async def sync_case_ehr(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger EHR data fetch for a specific case."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found"
        )
    
    try:
        fill_extracted_data_from_ehr(
            db,
            patient_id=db_case.patient_id,
            case_id=db_case.case_id
        )
        # Also trigger Gap Analysis during sync
        print(f"[cases_endpoint] Manually triggering Gap Analysis sync for case: {case_id}...")
        gap_result = run_gap_analysis({
            "case_id": case_id,
            "patient_name": f"Patient {db_case.patient_id}",
            "pdf_path": None
        })
        print(f"[cases_endpoint] Sync Gap Analysis result: {gap_result.get('output', 'No output')[:100]}...")
    except Exception as e:
        print(f"[cases_endpoint] Sync failed for {case_id}: {e}")
        traceback.print_exc()
        # We don't necessarily want to fail the request if sync fails, 
        # but let's return a 500 for now to help debugging
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch EHR data: {type(e).__name__}: {e}"
        )
        
    return db_case
