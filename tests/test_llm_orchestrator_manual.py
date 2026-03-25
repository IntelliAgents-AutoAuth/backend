import sys
import os
import asyncio
import logging

# Add backend to path (robustly)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

print(f"DEBUG: BASE_DIR is {BASE_DIR}")
print(f"DEBUG: sys.path[0] is {sys.path[0]}")

from orchestrator.case_orchestrator import CaseOrchestrator
from db.session import SessionLocal
from crud import crud_case

async def run_manual_test(case_id: str):
    """
    Runs the real orchestrator flow for a given case_id.
    This will call the real Gemini API and update your local database.
    """
    print(f"\n--- Starting Manual Test for Case: {case_id} ---")
    
    orchestrator = CaseOrchestrator(case_id)
    
    # Trigger the flow
    # Common triggers: "CASE_CREATED", "DOCUMENTS_UPLOADED", "STAFF_APPROVED"
    trigger = "CASE_CREATED" 
    
    try:
        await orchestrator.run(trigger)
        print(f"\n✅ Orchestration flow complete for {case_id}.")
        print("Check the console logs above to see the AI's 'Thinking' and decisions.")
        print("You can also check the 'audit_log' column in your 'cases' database table.")
    except Exception as e:
        print(f"\n❌ Orchestration failed: {e}")

if __name__ == "__main__":
    # 1. Look in your database (autoauth.db) for a valid case_id
    # 2. Replace 'PA-20260325-0001' with that ID below
    TARGET_CASE_ID = "PA-20260325-0001" 
    
    if len(sys.argv) > 1:
        TARGET_CASE_ID = sys.argv[1]
        
    asyncio.run(run_manual_test(TARGET_CASE_ID))
