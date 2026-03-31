import asyncio
import os
import sys
import shutil
import json

# Add backend to path before local imports
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from db.session import SessionLocal
import models.user  # Fix ForeignKey error
import models.ehr_records
from constants.cases import CaseStatus
from schemas.cases import CaseCreate
from crud import crud_case
from orchestrator.case_orchestrator import CaseOrchestrator

# --- Phoenix Instrumentation ---
try:
    from phoenix.otel import register
    from openinference.instrumentation.langchain import LangChainInstrumentor

    tracer_provider = register(endpoint="http://127.0.0.1:6006/v1/traces")
    LangChainInstrumentor().instrument(tracer_provider=tracer_provider, skip_dep_check=True)
    print("[observability] LangChain instrumentation connected to existing Phoenix dashboard at :6006.")
except Exception as e:
    print(f"[observability] Skipping Phoenix configuration: {e}")
# -------------------------------

async def test_orchestrator_flow():
    db = SessionLocal()
    case_id = "TEST-ORCH-001"
    
    # 1. Cleanup existing test case
    existing = crud_case.get_case(db, case_id=case_id)
    if existing:
        from models.cases import Case
        db.query(Case).filter(Case.case_id == case_id).delete()
        db.commit()
    
    print(f"--- Starting Orchestrator Test for {case_id} ---")
    
    # 2. Create Case
    case_in = CaseCreate(
        case_id=case_id,
        patient_id="P001",
        insurance_provider="Aetna",
        cpt_code="93452",
        icd10_code="I25.10"
    )
    db_case = crud_case.create_case(db, case_in=case_in, created_by="test@example.com")
    print(f"Case created. Initial status: {db_case.status}")
    
    # 3. Trigger Orchestrator
    orchestrator = CaseOrchestrator(case_id=case_id)
    print("\n--- [STAGE 1] Triggering CASE_CREATED (Gap Analysis) ---")
    await orchestrator.run(trigger="CASE_CREATED")
    
    # Refresh and check status
    db.refresh(db_case)
    print(f"Status after CASE_CREATED: {db_case.status}")
    
    # 4. Handle GAP Analysis Result
    if db_case.status == CaseStatus.GAP_FOUND.value:
        print("\n--- [STAGE 1.5] GAP FOUND! Proceeding to upload patient docs ---")
        
        # Copy from patient_docs to uploads/TEST-ORCH-001
        source_dir = os.path.join(backend_dir, "patient_docs")
        target_dir = os.path.join(backend_dir, "uploads", case_id)
        
        os.makedirs(target_dir, exist_ok=True)
        docs_found = False
        if os.path.exists(source_dir):
            for root_dir, _, files in os.walk(source_dir):
                for file in files:
                    if file.lower().endswith(".pdf"):
                        src_file = os.path.join(root_dir, file)
                        dst_file = os.path.join(target_dir, file)
                        shutil.copy2(src_file, dst_file)
                        print(f"Copied {file} to uploads directory.")
                        docs_found = True
        
        if not docs_found:
            print("WARNING: No PDFs found in patient_docs to copy!")
        
        # Manually force case status to GAP_CLEARED and trigger next stage
        db_case.status = CaseStatus.GAP_CLEARED.value
        db.add(db_case)
        db.commit()
        
        print("\n--- [STAGE 2] Triggering DOCUMENTS_UPLOADED (Eligibility) ---")
        await orchestrator.run(trigger="DOCUMENTS_UPLOADED")
        db.refresh(db_case)
        print(f"Status after DOCUMENTS_UPLOADED: {db_case.status}")
    
    # 5. Review Packet Status
    if db_case.status == CaseStatus.PENDING_APPROVAL.value:
        print("\n--- [STAGE 3] PA Packet Generated! Triggering STAFF_APPROVED (Submit to Payer) ---")
        await orchestrator.run(trigger="STAFF_APPROVED")
        db.refresh(db_case)
        print(f"Status after STAFF_APPROVED: {db_case.status}")
    elif db_case.status == CaseStatus.NOT_ELIGIBLE.value:
        print(f"Case was deemed NOT_ELIGIBLE. Halting flow.")
    else:
        print(f"Orchestrator halted unexpectedly at status: {db_case.status}")

    db.close()
    
    print("\n[observability] Flow complete. Flushing E2E traces to Phoenix dashboard...")
    await asyncio.sleep(4)

if __name__ == "__main__":
    asyncio.run(test_orchestrator_flow())
