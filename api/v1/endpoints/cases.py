from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse
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
from agents.eligibility_agent import run_eligibility_check
from agents.pa_document_agent import generate_pa_content
from services.pdf_generator import generate_pa_pdf


router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CaseSchema)
async def create_new_case(
    case_in: CaseCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new case with automatic ID and draft status."""
    db_case = crud_case.create_case(db, case_in=case_in, created_by=current_user.email)
    
    # 1. Trigger EHR fetch immediately (Synchronous, fast)
    try:
        fill_extracted_data_from_ehr(
            db,
            patient_id=db_case.patient_id,
            case_id=db_case.case_id
        )
    except Exception as e:
        print(f"[cases_endpoint] Failed to fetch EHR data for case {db_case.case_id}: {e}")
        traceback.print_exc()

    # 2. Trigger Gap Analysis in Background (Asynchronous, slow/LLM)
    # We pass properties needed for the agent
    agent_props = {
        "case_id": db_case.case_id,
        "patient_name": f"Patient {db_case.patient_id}",
        "pdf_path": None # Uses default if not provided
    }
    
    print(f"[cases_endpoint] Scheduling background Gap Analysis for: {db_case.case_id}...")
    background_tasks.add_task(run_gap_analysis, agent_props)
        
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


@router.post("/{case_id}/eligibility")
async def check_case_eligibility(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run the Eligibility Agent for a specific case.

    Fetches the patient's EHR record and compares it against the policy PDF
    to determine whether the patient is eligible for the claim.

    Returns:
        {
            "case_id": str,
            "eligible": bool,
            "verdict": "ELIGIBLE" | "NOT_ELIGIBLE",
            "reason": str
        }
    """
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found",
        )

    try:
        print(f"[cases_endpoint] Running eligibility check for case: {case_id}...")
        result = run_eligibility_check({
            "case_id": case_id,
            "pdf_path": None,  # uses default policy PDF
        })
        print(
            f"[cases_endpoint] Eligibility result for {case_id}: "
            f"{result.get('verdict')} — {result.get('reason', '')[:80]}..."
        )
        return result
    except Exception as e:
        print(f"[cases_endpoint] Eligibility check failed for {case_id}: {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Eligibility check failed: {type(e).__name__}: {e}",
        )


@router.post("/{case_id}/generate-document")
async def generate_pa_document(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a complete Prior Authorization PDF package for a case.

    Sections:
      1. Cover Letter       — LLM-written medical necessity letter
      2. Clinical Summary   — LLM-generated patient narrative
      3. Checklist          — every insurance requirement, ticked with evidence
      4. Attached Documents — all uploaded files merged in

    Returns the PDF as a file download.
    """
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found",
        )

    # Resolve uploaded file paths stored on the case
    uploaded_paths = []
    if db_case.uploaded_files:
        import os
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )))
        for f in db_case.uploaded_files:
            path = f.get("path") or f.get("file_path") or ""
            if path and os.path.exists(path):
                uploaded_paths.append(path)

    try:
        print(f"[cases_endpoint] Generating PA document for case: {case_id}...")

        # 1. LLM generates content
        content = generate_pa_content(case_id=case_id, pdf_path=None)

        # 2. PDF builder assembles the package
        pdf_path = generate_pa_pdf(
            case_id=case_id,
            content=content,
            uploaded_file_paths=uploaded_paths,
        )

        print(f"[cases_endpoint] PA document ready: {pdf_path}")
        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            filename=f"PA_Package_{case_id}.pdf",
        )
    except Exception as e:
        print(f"[cases_endpoint] Document generation failed for {case_id}: {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document generation failed: {type(e).__name__}: {e}",
        )
