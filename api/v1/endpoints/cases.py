from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, UploadFile, File, Form
from datetime import datetime
from fastapi.responses import FileResponse
import traceback
import os
import shutil
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
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
from orchestrator.case_orchestrator import CaseOrchestrator
from services.pdf_generator import generate_pa_pdf
from constants.cases import CaseStatus
from tools.ehr_fetcher import fetch_extracted_data_by_case


router = APIRouter(prefix="/cases", tags=["cases"])


def merge_ehr_data_into_case(db: Session, db_case: Case):
    """Augment the case object with data from aggregated sources for cleaner frontend display."""
    # Use the smart fetcher that combines EHR table, manual entries, and PDF extractions
    ext_data = fetch_extracted_data_by_case(db_case.case_id)
    if not ext_data:
        return db_case
    
    # Map fields from dict to Case object
    db_case.patient_name = f"{ext_data.get('patient_first_name') or ''} {ext_data.get('patient_last_name') or ''}".strip() or None
    db_case.date_of_birth = str(ext_data.get("patient_dob")) if ext_data.get("patient_dob") else None
    db_case.gender = ext_data.get("patient_gender")
    db_case.physician_name = ext_data.get("physician_name")
    db_case.physician_npi = ext_data.get("physician_npi")
    db_case.physician_specialty = ext_data.get("physician_specialty")
    db_case.facility_name = ext_data.get("facility_name")
    db_case.diagnosis = ext_data.get("primary_diagnosis") or ext_data.get("diagnosis")
    
    # Lab results mapping
    db_case.lab_results = ext_data.get("lab_results")
    
    # Fallback for empty case fields
    if not db_case.cpt_code:
        db_case.cpt_code = ext_data.get("cpt_code")
    if not db_case.icd10_code:
        db_case.icd10_code = ext_data.get("primary_icd10_code") or ext_data.get("icd10_code")
        
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

    # 2. Trigger Orchestrator in Background (Asynchronous)
    orchestrator = CaseOrchestrator(case_id=db_case.case_id)
    background_tasks.add_task(
        orchestrator.run,
        trigger="CASE_CREATED",
        payload={"pdf_path": None}
    )
        
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


@router.get("/{case_id}/timeline")
async def get_case_timeline(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns full audit log timeline for a case."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")

    return {
        "case_id":  case_id,
        "status":   db_case.status,
        "timeline": db_case.audit_log or []
    }


def _check_and_clear_gaps(db_case, case_id, db, background_tasks):
    """Shared heuristic to check if gaps are cleared and trigger eligibility."""
    if db_case.gap_result and "missing_documents" in db_case.gap_result:
        missing_docs = db_case.gap_result["missing_documents"]
        requirement_keys = {d["document_name"].strip().lower() for d in missing_docs}
        uploaded_keys = {f["missing_key"].strip().lower() for f in db_case.uploaded_files if f.get("missing_key")}
        
        print(f"[api] Checking gaps for {case_id}: req={requirement_keys}, uploaded={uploaded_keys}")
        
        if requirement_keys and requirement_keys.issubset(uploaded_keys):
            print(f"[api] SUCCESS: All gaps cleared for {case_id}. Auto-triggering Eligibility.")
            db_case.status = "GAP_CLEARED"
            
            gap_res = dict(db_case.gap_result)
            gap_res["status"] = "GAP_CLEARED"
            gap_res["missing_documents"] = []
            db_case.gap_result = gap_res
            
            db.commit()
            
            # Note: Eligibility is now triggered via CaseOrchestrator in the calling endpoint
        else:
            diff = requirement_keys - uploaded_keys
            print(f"[api] Gaps still exist for {case_id}. Missing: {diff}")

@router.post("/{case_id}/upload-file")
async def upload_case_file(
    case_id: str,
    background_tasks: BackgroundTasks,
    document_name: str = Form(...),
    missing_key: str = Form(...),
    field_value: str = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Real file upload endpoint that saves to uploads/{case_id}/."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    file_path = None
    if file:
        # 1. Create directory: uploads/{case_id}/
        upload_dir = os.path.join("uploads", case_id)
        os.makedirs(upload_dir, exist_ok=True)
        
        # 2. Save file
        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Convert to absolute path for the agent to find it easily
        file_path = os.path.abspath(file_path)
        print(f"[api] File saved to: {file_path}")

    # 3. Update Case metadata
    # Use list() to ensure we have a fresh copy, avoiding reference issues
    files = list(db_case.uploaded_files) if db_case.uploaded_files else []
    files.append({
        "document_name": document_name,
        "file_path": file_path,
        "field_value": field_value,
        "missing_key": missing_key,
        "uploaded_at": datetime.now().isoformat(),
        "uploaded_by": current_user.email,
        "status": "UPLOADED"
    })
    db_case.uploaded_files = files
    # Explicitly tell SQLAlchemy the field has changed
    flag_modified(db_case, "uploaded_files")
    
    db.commit()
    db.refresh(db_case)
    
    # 4. Check if all gaps cleared and trigger orchestrator
    _check_and_clear_gaps(db_case, case_id, db, background_tasks)
    
    # If gaps are now cleared, the orchestrator handles the next steps
    if db_case.status == CaseStatus.GAP_CLEARED.value:
        orchestrator = CaseOrchestrator(case_id=case_id)
        background_tasks.add_task(orchestrator.run, trigger="DOCUMENTS_UPLOADED")
    
    return {"status": "SUCCESS", "file_path": file_path}


@router.post("/{case_id}/upload")
async def upload_case_document(
    case_id: str,
    file_info: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Legacy metadata-only upload (kept for compatibility)."""
    return {"status": "DEPRECATED", "message": "Use /upload-file for real uploads."}

@router.post("/{case_id}/bulk-upload")
async def bulk_upload_case_documents(
    case_id: str,
    payload: list[dict],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bulk document upload to prevent race conditions."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    files = db_case.uploaded_files or []
    for info in payload:
        files.append({
            "document_name": info.get("document_name"),
            "file_path": info.get("file_path"),
            "field_value": info.get("field_value"),
            "missing_key": info.get("missing_key"),
            "uploaded_at": datetime.now().isoformat(),
            "uploaded_by": current_user.email,
            "status": "UPLOADED"
        })
    db_case.uploaded_files = files
    db.commit()
    db.refresh(db_case)
    
    _check_and_clear_gaps(db_case, case_id, db, background_tasks)
    
    # If gaps are now cleared, the orchestrator handles the next steps
    if db_case.status == CaseStatus.GAP_CLEARED.value:
        orchestrator = CaseOrchestrator(case_id=case_id)
        background_tasks.add_task(orchestrator.run, trigger="DOCUMENTS_UPLOADED")
        
    return {"status": "SUCCESS"}


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
        print(f"[cases_endpoint] Triggering eligibility via orchestrator for: {case_id}...")
        orchestrator = CaseOrchestrator(case_id=case_id)
        # We use DOCUMENTS_UPLOADED as the trigger because that's the logic 
        # that flows into eligibility in the current orchestrator.
        background_tasks.add_task(orchestrator.run, trigger="DOCUMENTS_UPLOADED")
        
        return {"status": "SUCCESS", "message": "Eligibility check triggered in background."}
    except Exception as e:
        print(f"[cases_endpoint] Orchestration trigger failed for {case_id}: {e}")
        traceback.print_exc()
@router.get("/{case_id}/preview")
async def preview_pa_package(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Finds and serves the latest generated PA PDF for a case.
    """
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")
        
    # cases.py is in backend/api/v1/endpoints/, so 4 levels up to reach backend root
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    output_dir = os.path.join(backend_dir, "uploads", "generated")
    
    # Auto-create if it doesn't exist to avoid 404
    os.makedirs(output_dir, exist_ok=True)
 
    # Find files starting with PA_{case_id}_
    files = [f for f in os.listdir(output_dir) if f.startswith(f"PA_{case_id}_") and f.endswith(".pdf")]
    if not files:
        raise HTTPException(status_code=404, detail="No generated PA package found for this case. Ensure content has been generated first.")
        
    # Sort by timestamp (descending) to get the latest
    files.sort(reverse=True)
    latest_file = os.path.join(output_dir, files[0])
    
    return FileResponse(
        path=latest_file,
        media_type="application/pdf",
        filename=os.path.basename(latest_file)
    )


@router.post("/{case_id}/submit")
async def submit_case_to_payer(
    case_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Triggers the final submission flow (Staff Approval -> Submitted -> Tracking).
    """
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")
        
    # Only allow submission if packet is ready
    if db_case.status not in [CaseStatus.PACKET_READY.value, CaseStatus.PENDING_APPROVAL.value]:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Case status must be PACKET_READY or PENDING_APPROVAL. Current: {db_case.status}"
        )
        
    orchestrator = CaseOrchestrator(case_id=case_id)
    background_tasks.add_task(orchestrator.run, trigger="STAFF_APPROVED")
    
    return {"status": "SUCCESS", "message": "Case submission initiated."}


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
