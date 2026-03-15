from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from datetime import datetime
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
from crud.crud_extracted_data import get_extracted_data
from services.extraction_service import fill_extracted_data_from_ehr
from agents.gap_analysis_agent import run_gap_analysis
from agents.eligibility_agent import run_eligibility_check
from agents.pa_document_agent import generate_pa_content
from services.pdf_generator import generate_pa_pdf


router = APIRouter(prefix="/cases", tags=["cases"])


def merge_ehr_data_into_case(db: Session, db_case: Case):
    """Augment the case object with data from extracted_data table for cleaner frontend display."""
    ext_data = get_extracted_data(db, db_case.case_id)
    if not ext_data:
        return db_case
    
    # Map fields from ExtractedData to Case (Pydantic schema handles display)
    db_case.patient_name = f"{ext_data.patient_first_name or ''} {ext_data.patient_last_name or ''}".strip() or None
    # Handle date conversion if needed, otherwise just pass through
    db_case.date_of_birth = str(ext_data.patient_dob) if ext_data.patient_dob else None
    db_case.gender = ext_data.patient_gender
    db_case.physician_name = ext_data.physician_name
    db_case.physician_npi = ext_data.physician_npi
    db_case.physician_specialty = ext_data.physician_specialty
    db_case.facility_name = ext_data.facility_name
    db_case.diagnosis = ext_data.primary_diagnosis
    
    # Lab results mapping
    db_case.lab_results = ext_data.lab_results
    
    # Fallback for empty case fields
    if not db_case.cpt_code:
        db_case.cpt_code = ext_data.cpt_code
    if not db_case.icd10_code:
        db_case.icd10_code = ext_data.primary_icd10_code
        
    return db_case



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
    
    print(f"[api] Scheduling Background Analysis: {db_case.case_id}")
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
    return merge_ehr_data_into_case(db, db_case)

@router.get("/{case_id}/gap-analysis")
async def get_case_gap_analysis(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve the stored Gap Analysis result for a case."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found"
        )
    
    return db_case.gap_result or {"status": "NOT_STARTED", "message": "Analysis in progress or not yet triggered."}


@router.post("/{case_id}/upload")
async def upload_case_document(
    case_id: str,
    file_info: dict, # Expected: {"document_name": "...", "file_path": "...", "missing_key": "..."}
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Simulate document upload by adding info to the case record."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found"
        )
    
    files = db_case.uploaded_files or []
    files.append({
        "document_name": file_info.get("document_name"),
        "file_path": file_info.get("file_path"),
        "field_value": file_info.get("field_value"), # New: store actual data value if it's not a file
        "missing_key": file_info.get("missing_key"), # The ID/Key of the missing doc this satisfies
        "uploaded_at": datetime.now().isoformat(),
        "uploaded_by": current_user.email,
        "status": "UPLOADED"
    })
    
    db_case.uploaded_files = files
    db.add(db_case)
    db.commit()
    db.refresh(db_case)
    
    return {"status": "SUCCESS", "message": f"Document '{file_info.get('document_name')}' uploaded."}


@router.post("/{case_id}/sync", response_model=CaseSchema)
async def sync_case_ehr(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger EHR data fetch and Gap Analysis for a specific case."""
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
        print(f"[api] Manually Triggering Sync: {case_id}")
        await run_gap_analysis({
            "case_id": case_id,
            "patient_name": f"Patient {db_case.patient_id}",
            "pdf_path": None
        })
        
        # Refresh case record to get updated gap fields
        db.refresh(db_case)
        
    except Exception as e:
        print(f"[cases_endpoint] Sync failed for {case_id}: {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch EHR data: {type(e).__name__}: {e}"
        )
        
    return merge_ehr_data_into_case(db, db_case)
  


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
