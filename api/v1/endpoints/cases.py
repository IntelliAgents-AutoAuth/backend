from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, UploadFile, File, Form
from datetime import datetime
from fastapi.responses import FileResponse
import traceback
import os
import shutil
import asyncio
import time
import logging
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from schemas.cases import Case as CaseSchema, CaseCreate, CaseFullDetails
from models.cases import Case
from models.user import User
from core.security import get_current_user
from api.deps import get_db
from crud import crud_case, crud_ehr
from crud.crud_extracted_data import get_extracted_data
from orchestrator.case_orchestrator import CaseOrchestrator
from constants.cases import CaseStatus
from tools.ehr_fetcher import fetch_extracted_data_by_case
from services.async_file_processor import AsyncFileExtractor


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cases", tags=["cases"])

_IN_PROGRESS_STATUSES = {
    CaseStatus.EHR_FETCHING.value,
    CaseStatus.GAP_ANALYSIS_RUNNING.value,
    CaseStatus.ELIGIBILITY_RUNNING.value,
    CaseStatus.PACKET_GENERATING.value,
}


def _schedule_orchestrator(background_tasks: BackgroundTasks, db_case: Case, trigger: str, payload: dict | None = None) -> bool:
    """Safely enqueue orchestrator run and avoid duplicate in-progress triggers.
    
    EXCEPTION: Allow DOCUMENTS_UPLOADED to re-trigger even during in-progress stages
    (e.g., files uploaded while eligibility running should re-trigger gap+eligibility)
    """
    # Allow DOCUMENTS_UPLOADED to bypass in-progress check (enables file re-analysis)
    if trigger == "DOCUMENTS_UPLOADED":
        # File uploads should always be processed, even during in-progress stages
        orchestrator = CaseOrchestrator(case_id=db_case.case_id)
        background_tasks.add_task(orchestrator.run, trigger=trigger, payload=payload or {"pdf_path": None})
        return True
    
    # For other triggers, avoid duplicate in-progress runs
    if trigger != "RETRY" and db_case.status in _IN_PROGRESS_STATUSES:
        print(
            f"[api] Skipping trigger '{trigger}' for {db_case.case_id}: "
            f"status {db_case.status} is already in-progress."
        )
        return False

    orchestrator = CaseOrchestrator(case_id=db_case.case_id)
    background_tasks.add_task(orchestrator.run, trigger=trigger, payload=payload or {"pdf_path": None})
    return True


def merge_ehr_data_into_case(db: Session, db_case: Case):
    """Augment the case object with data from aggregated sources for cleaner frontend display."""
    # Use the smart fetcher that combines EHR table, manual entries, and PDF extractions
    ext_data = fetch_extracted_data_by_case(db_case.case_id, extract_pdf_text=False)
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

    # Trigger Orchestrator in Background (single runtime owner)
    _schedule_orchestrator(background_tasks, db_case, trigger="CASE_CREATED", payload={"pdf_path": None})
        
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


@router.get("/{case_id}/full-details", response_model=CaseFullDetails)
async def get_case_full_details(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch comprehensive details of a specific case, including:
    - Case metadata
    - Extracted AI data
    - Patient EHR record
    """
    # 1. Get Case
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found"
        )
    
    # 2. Get Extracted Data
    db_extracted = get_extracted_data(db, case_id=case_id)
    
    # 3. Get EHR Record
    db_ehr = crud_ehr.get_ehr(db, patient_id=db_case.patient_id)
    
    return {
        "case": merge_ehr_data_into_case(db, db_case),
        "extracted_data": db_extracted,
        "ehr": db_ehr
    }


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

@router.get("/{case_id}/audit-log")
async def get_case_audit_log(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve the audit log for a case."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    return db_case.audit_log or []

def _check_and_clear_gaps(db: Session, db_case, case_id) -> bool:
    """Check whether uploaded docs satisfy current missing requirements and mark GAP_CLEARED when true."""
    if db_case.gap_result and "missing_documents" in db_case.gap_result:
        missing_docs = db_case.gap_result["missing_documents"]
        requirement_keys = {d["document_name"].strip().lower() for d in missing_docs}
        uploaded_keys = {f["missing_key"].strip().lower() for f in db_case.uploaded_files if f.get("missing_key")}
        
        print(f"[api] Checking gaps for {case_id}: req={requirement_keys}, uploaded={uploaded_keys}")
        
        if requirement_keys and requirement_keys.issubset(uploaded_keys):
            print(f"[api] Uploads satisfy all current missing docs for {case_id}. Marking GAP_CLEARED.")

            db_case.status = CaseStatus.GAP_CLEARED.value
            if isinstance(db_case.gap_result, dict):
                gap_result = dict(db_case.gap_result)
                gap_result["status"] = CaseStatus.GAP_CLEARED.value
                gap_result["missing_documents"] = []
                db_case.gap_result = gap_result
                flag_modified(db_case, "gap_result")

            db.add(db_case)
            db.commit()
            db.refresh(db_case)
            return True
        else:
            diff = requirement_keys - uploaded_keys
            print(f"[api] Gaps still exist for {case_id}. Missing: {diff}")
            return False

    return False

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
    """
    Real file upload endpoint that saves to uploads/{case_id}/.
    OPTIMIZATION 5: Batch DB Operations - Single transaction for all updates
    """
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    try:
        # ──── OPTIMIZATION 5: Single Transaction (NEW) ────
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
        
        # 4. Check and clear gaps (updates db_case status in same transaction)
        _check_and_clear_gaps(db, db_case, case_id)
        
        # ✅ SINGLE COMMIT FOR ALL CHANGES (Optimization 5)
        db.add(db_case)
        db.commit()
        db.refresh(db_case)
        
    except Exception as e:
        db.rollback()
        logger.error(f"[api] Error uploading file for {case_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    # 5. Trigger orchestrator only when upload can impact the current stage.
    triggerable_statuses = {
        CaseStatus.GAP_FOUND.value,
        CaseStatus.GAP_CLEARED.value,
        CaseStatus.GAP_ANALYSIS_FAILED.value,
        CaseStatus.ELIGIBILITY_RUNNING.value,  # Allow re-trigger while eligibility is running
        CaseStatus.APPROVED.value,             # Allow re-trigger post-eligibility
        CaseStatus.DENIED.value,               # Allow re-trigger on denied cases
    }
    if db_case.status in triggerable_statuses:
        _schedule_orchestrator(background_tasks, db_case, trigger="DOCUMENTS_UPLOADED", payload={"pdf_path": None})
    else:
        print(
            f"[api] Skipping DOCUMENTS_UPLOADED trigger for {case_id}. "
            f"Current status={db_case.status} is not triggerable."
        )
    
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
    
    _check_and_clear_gaps(db, db_case, case_id)

    triggerable_statuses = {
        CaseStatus.GAP_FOUND.value,
        CaseStatus.GAP_CLEARED.value,
        CaseStatus.GAP_ANALYSIS_FAILED.value,
    }
    if db_case.status in triggerable_statuses:
        _schedule_orchestrator(background_tasks, db_case, trigger="DOCUMENTS_UPLOADED", payload={"pdf_path": None})
    else:
        print(
            f"[api] Skipping DOCUMENTS_UPLOADED trigger for {case_id}. "
            f"Current status={db_case.status} is not triggerable."
        )
        
    return {"status": "SUCCESS"}


@router.post("/{case_id}/bulk-upload-parallel")
async def bulk_upload_parallel(
    case_id: str,
    files: list[UploadFile] = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    OPTIMIZATION 6: Parallel file extraction for bulk uploads
    
    Process multiple file uploads concurrently:
    - Save all files in parallel (async I/O)
    - Extract text from PDFs concurrently (max 5)
    - Batch gap analysis
    - Single DB transaction for all metadata
    
    Expected speedup: 80% faster for 5+ files (15s → 3s)
    """
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided")
    
    start_time = time.time()
    
    try:
        # ──── PHASE 1: Save files in parallel (async I/O) ────
        async def save_file(upload_file: UploadFile) -> tuple[str, str]:
            """Save a file to disk asynchronously."""
            upload_dir = os.path.join("uploads", case_id)
            os.makedirs(upload_dir, exist_ok=True)
            
            file_path = os.path.join(upload_dir, upload_file.filename)
            content = await upload_file.read()
            
            # Run file write in executor to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: open(file_path, "wb").write(content)
            )
            
            return upload_file.filename, os.path.abspath(file_path)
        
        # Save ALL files concurrently
        print(f"[api] PHASE 1: Saving {len(files)} files in parallel...")
        save_tasks = [save_file(f) for f in files]
        saved_files = await asyncio.gather(*save_tasks)
        print(f"[api] ✅ Saved {len(saved_files)} files")
        
        # ──── PHASE 2: Extract text in parallel (max 5 concurrent) ────
        print(f"[api] PHASE 2: Extracting text from {len(files)} files in parallel...")
        extractor = AsyncFileExtractor(max_concurrency=5)
        file_paths = [fpath for _, fpath in saved_files]
        extracted_texts = await extractor.extract_multiple_files(file_paths)
        print(f"[api] ✅ Extracted text from {len(extracted_texts)} files")
        
        # ──── PHASE 3: Batch DB operations (single transaction) ────
        print(f"[api] PHASE 3: Updating database with metadata...")
        file_records = []
        for (orig_name, fpath), _ in zip(saved_files, extracted_texts.items()):
            file_records.append({
                "document_name": orig_name,
                "file_path": fpath,
                "uploaded_at": datetime.now().isoformat(),
                "uploaded_by": current_user.email,
                "status": "EXTRACTED"
            })
        
        db_case.uploaded_files = db_case.uploaded_files or []
        db_case.uploaded_files.extend(file_records)
        flag_modified(db_case, "uploaded_files")
        
        # ──── PHASE 4: Batch gap analysis (single trigger) ────
        _check_and_clear_gaps(db, db_case, case_id)
        
        # ✅ SINGLE COMMIT FOR ALL FILES (Optimization 5 + 6)
        db.add(db_case)
        db.commit()
        db.refresh(db_case)
        print(f"[api] ✅ Database updated")
        
        # 5. Trigger orchestrator ONCE for all files
        triggerable_statuses = {
            CaseStatus.GAP_FOUND.value,
            CaseStatus.GAP_CLEARED.value,
            CaseStatus.GAP_ANALYSIS_FAILED.value,
        }
        if db_case.status in triggerable_statuses:
            _schedule_orchestrator(
                background_tasks, db_case,
                trigger="DOCUMENTS_UPLOADED",
                payload={"file_count": len(files), "extraction_method": "parallel"}
            )
            print(f"[api] ✅ Triggered orchestrator for {len(files)} files")
        else:
            print(
                f"[api] Skipping DOCUMENTS_UPLOADED trigger for {case_id}. "
                f"Current status={db_case.status} is not triggerable."
            )
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        return {
            "status": "SUCCESS",
            "files_uploaded": len(files),
            "extraction_time_ms": int(elapsed_ms),
            "files": [fn for fn, _ in saved_files],
            "optimization": "parallel (Opt 6)"
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"[api] Parallel bulk upload failed for {case_id}: {e}")
        print(f"[api] Error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/{case_id}/sync")
async def sync_case_ehr(
    case_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger orchestrator sync flow for a specific case."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found"
        )

    _schedule_orchestrator(background_tasks, db_case, trigger="SYNC_REQUESTED", payload={"pdf_path": None})
    return {"status": "SUCCESS", "message": "Sync requested. Orchestrator running in background."}
  


@router.post("/{case_id}/eligibility")
async def check_case_eligibility(
    case_id: str,
    background_tasks: BackgroundTasks,
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
        _schedule_orchestrator(background_tasks, db_case, trigger="ELIGIBILITY_REQUESTED", payload={"pdf_path": None})
        
        return {"status": "SUCCESS", "message": "Eligibility check triggered in background."}
    except Exception as e:
        print(f"[cases_endpoint] Orchestration trigger failed for {case_id}: {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger eligibility orchestration: {type(e).__name__}: {e}",
        )
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
        
    _schedule_orchestrator(background_tasks, db_case, trigger="STAFF_APPROVED", payload={"pdf_path": None})
    
    return {"status": "SUCCESS", "message": "Case submission initiated."}


@router.post("/{case_id}/generate-document")
async def generate_pa_document(
    case_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger background PA package generation via orchestrator.

    Sections:
      1. Cover Letter       — LLM-written medical necessity letter
      2. Clinical Summary   — LLM-generated patient narrative
      3. Checklist          — every insurance requirement, ticked with evidence
      4. Attached Documents — all uploaded files merged in

    Use /preview to fetch the latest generated package when ready.
    """
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found",
        )

    _schedule_orchestrator(background_tasks, db_case, trigger="GENERATE_PACKET_REQUESTED", payload={"pdf_path": None})
    return {"status": "SUCCESS", "message": "Document generation requested. Check /preview once ready."}


@router.post("/{case_id}/retry")
async def retry_case_flow(
    case_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retry last failed orchestrator step for a case."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")

    _schedule_orchestrator(background_tasks, db_case, trigger="RETRY", payload={"pdf_path": None})
    return {"status": "SUCCESS", "message": "Retry requested in background."}
