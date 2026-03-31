"""
Standalone test script for the Policy Eligibility Agent.

Run from the backend directory:
    python tests/test_eligibility_agent.py
"""

import os
import sys

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


# ─────────────────────────────────────────
# TEST 1 — eligibility_checker tool (no LLM)
# ─────────────────────────────────────────

def test_eligibility_checker_tool():
    print("\n" + "=" * 60)
    print("TEST 1: eligibility_checker tool (pure Python, no LLM)")
    print("=" * 60)
    from tools.eligibility_checker import format_ehr_for_eligibility

    mock_ehr = {
        "patient_id": "PAT-001",
        "patient_first_name": "John",
        "patient_last_name": "Doe",
        "patient_dob": "1965-03-12",
        "patient_gender": "M",
        "payer_name": "Aetna",
        "member_id": "AET-12345",
        "policy_number": "POL-98765",
        "group_number": "GRP-001",
        "plan_name": "Gold PPO",
        "physician_name": "Dr. Smith",
        "physician_npi": "1234567890",
        "physician_specialty": "Cardiology",
        "facility_name": "City Heart Hospital",
        "primary_icd10_code": "I50.9",
        "primary_diagnosis": "Heart Failure",
        "cpt_code": "75563",
        "procedure_name": "Cardiac MRI",
        "lab_results": {"BNP": "420 pg/mL", "Creatinine": "1.2 mg/dL"},
        "lvef_percent": 35.0,
        "bnp_level": 420.0,
        "lvef_below_40": True,
        "soap_subjective": "Patient reports shortness of breath.",
        "soap_assessment": "Dilated cardiomyopathy with reduced EF.",
        "clinical_justification": "Cardiac MRI required for pre-surgical planning.",
        "treatment_failed": True,
        "treatment_duration_weeks": 12,
        "auto_approval_triggered": False,
    }

    result = format_ehr_for_eligibility(mock_ehr)
    print(result)
    print("\n✅ eligibility_checker tool working correctly.")
    return result


# ─────────────────────────────────────────
# TEST 2 — ehr_fetcher tool (DB required)
# ─────────────────────────────────────────

def test_ehr_fetcher_tool():
    print("\n" + "=" * 60)
    print("TEST 2: ehr_fetcher (requires DB connection)")
    print("=" * 60)
    from tools.ehr_fetcher import fetch_extracted_data_by_case

    case_id = "PA-20260309-00002"
    print(f"Fetching EHR for case_id: {case_id}")
    result = fetch_extracted_data_by_case(case_id)
    if result:
        print(f"✅ EHR found: {list(result.keys())}")
    else:
        print(f"⚠️  No EHR found for case_id={case_id!r}. Make sure the case exists.")
    return result


# ─────────────────────────────────────────
# TEST 3 — Full eligibility agent run (LLM)
# ─────────────────────────────────────────

def test_run_eligibility_check():
    print("\n" + "=" * 60)
    print("TEST 3: Full Eligibility Agent Run (requires GOOGLE_API_KEY)")
    print("=" * 60)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(backend_dir, ".env"))

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GOOGLE_API_KEY not found in .env — skipping LLM test.")
        return

    from agents import run_eligibility_check

    case_id = "PA-20260309-00002"
    print(f"Running eligibility check for case: {case_id}")

    try:
        result = run_eligibility_check({
            "case_id":  case_id,
            "pdf_path": None,
        })
        print("\n--- RESULT ---")
        print(f"Eligible : {result['eligible']}")
        print(f"Verdict  : {result['verdict']}")
        print(f"Reason   : {result['reason']}")
        print("✅ Eligibility agent ran successfully.")
    except Exception as e:
        print(f"❌ Agent run failed: {e}")
        import traceback; traceback.print_exc()


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

if __name__ == "__main__":
    print("Starting Eligibility Agent Tests...")

    test_eligibility_checker_tool()   # always runs (no LLM / DB needed)
    test_ehr_fetcher_tool()           # needs DB
    test_run_eligibility_check()      # needs DB + GOOGLE_API_KEY

    print("\n" + "=" * 60)
    print("All tests completed.")
    print("=" * 60)
