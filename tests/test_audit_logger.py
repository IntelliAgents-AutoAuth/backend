import sys
import os
import asyncio
import json

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.logger import log_event
from db.session import SessionLocal
from crud import crud_case

async def test_logger():
    print("--- Starting Audit Logger Test ---")
    db = SessionLocal()
    
    # 1. Create a dummy case or find an existing one
    case_id = "TEST-LOG-001"
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        from schemas.cases import CaseCreate
        from models.user import User
        # We need a user for created_by
        # Let's just create a minimal case manually if crud_case requires more setup
        from models.cases import Case
        db_case = Case(
            case_id=case_id,
            patient_id="PAT-001",
            status="DRAFT",
            created_by="admin@example.com",
            audit_log=[]
        )
        db.add(db_case)
        db.commit()
        db.refresh(db_case)
        print(f"Created test case: {case_id}")

    # 2. Log some events
    print("Logging events...")
    log_event(
        case_id=case_id,
        agent_name="TEST_AGENT",
        event="TEST_STARTED",
        status="RUNNING",
        message="Verification test started"
    )
    
    log_event(
        case_id=case_id,
        agent_name="TEST_AGENT",
        event="TEST_COMPLETED",
        status="SUCCESS",
        message="Verification test completed successfully",
        duration_ms=500,
        metadata={"test_key": "test_value"}
    )

    # 3. Verify logs in DB
    db.refresh(db_case)
    print(f"Audit Log contents: {json.dumps(db_case.audit_log, indent=2)}")
    
    if len(db_case.audit_log) >= 2:
        print("✅ SUCCESS: Logs found in database.")
    else:
        print("❌ FAILED: Logs not found or incomplete.")

    print("--- Audit Logger Test Completed ---")

if __name__ == "__main__":
    asyncio.run(test_logger())
