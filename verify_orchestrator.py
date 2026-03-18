import asyncio
import os
import sys
import json
from db.session import SessionLocal
from constants.cases import CaseStatus
from schemas.cases import CaseCreate
from crud import crud_case
from orchestrator.case_orchestrator import CaseOrchestrator

# Add backend to path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

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
    print("Triggering CASE_CREATED...")
    await orchestrator.run(trigger="CASE_CREATED")
    
    # Refresh and check status
    db.refresh(db_case)
    print(f"Final status after CASE_CREATED: {db_case.status}")
    
    if db_case.status in [CaseStatus.GAP_FOUND.value, CaseStatus.GAP_CLEARED.value]:
        print("✅ Orchestrator successfully reached Gap Analysis stage.")
    else:
        print(f"❌ Unexpected status: {db_case.status}")

    db.close()

if __name__ == "__main__":
    asyncio.run(test_orchestrator_flow())
