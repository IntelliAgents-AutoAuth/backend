"""
Standalone test for the PA Document Generator.

Run from backend directory:
    python tests/test_pa_document.py
"""

import os
import sys

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


def test_pdf_generator_no_llm():
    """Build a PDF with static content — no LLM or DB needed."""
    print("\n" + "=" * 60)
    print("TEST 1: PDF Generator (no LLM, static content)")
    print("=" * 60)

    from services.pdf_generator import generate_pa_pdf

    mock_content = {
        "ehr": {
            "patient_first_name": "John",
            "patient_last_name": "Smith",
            "patient_dob": "1968-03-15",
            "payer_name": "United Healthcare",
            "member_id": "UHC-887612",
            "policy_number": "UHC-POL-2026-001",
            "physician_name": "Dr. Ramesh Kumar",
            "physician_npi": "1234567890",
            "physician_specialty": "Cardiology",
            "facility_name": "City Heart Institute",
            "primary_icd10_code": "I42.0",
            "cpt_code": "75563",
        },
        "cover_letter": (
            "Dear Prior Authorization Review Team,\n\n"
            "We are writing to request prior authorization for a Cardiac MRI with contrast "
            "(CPT 75563) for our patient John Smith, DOB March 15, 1968. The patient presents "
            "with Dilated Cardiomyopathy (ICD-10: I42.0) with LVEF of 32%, significantly below "
            "the 35% threshold. BNP levels are elevated at 450 pg/mL, indicating severe "
            "cardiac dysfunction. This procedure is medically necessary to guide treatment "
            "planning and assess candidacy for advanced cardiac therapies.\n\n"
            "Sincerely,\nDr. Ramesh Kumar, MD\nCity Heart Institute"
        ),
        "clinical_summary": (
            "## Diagnosis\nDilated Cardiomyopathy (ICD-10: I42.0)\n\n"
            "## Patient History\nJohn Smith is a 58-year-old male with a 3-year history of "
            "heart failure. He has been managed with optimal medical therapy including "
            "ACE inhibitors and beta-blockers.\n\n"
            "## Reason for Procedure\nCardiac MRI is required to precisely quantify LVEF, "
            "characterize myocardial fibrosis, and assess viability prior to CRT device "
            "evaluation.\n\n"
            "## Supporting Evidence\n- LVEF: 32% (echocardiogram, Jan 2026)\n"
            "- BNP: 450 pg/mL (elevated)\n- 12-week trial of optimal medical therapy: no improvement"
        ),
        "checklist": [
            {"item": "LVEF documented below 35%",           "met": True,  "evidence": "LVEF = 32% on echocardiogram January 2026"},
            {"item": "BNP level documented",                 "met": True,  "evidence": "BNP = 450 pg/mL"},
            {"item": "Cardiology physician order",           "met": True,  "evidence": "Ordered by Dr. Ramesh Kumar, NPI 1234567890"},
            {"item": "Prior medication trial documented",    "met": True,  "evidence": "12-week ACE inhibitor + beta-blocker trial with no improvement"},
            {"item": "Clinical justification letter",        "met": True,  "evidence": "Included as cover letter in this package"},
            {"item": "Lab results (metabolic panel)",        "met": True,  "evidence": "Metabolic panel: Normal"},
            {"item": "ICD-10 diagnosis code",                "met": True,  "evidence": "I42.0 — Dilated Cardiomyopathy"},
            {"item": "Facility accreditation",               "met": False, "evidence": "Facility accreditation certificate not on file"},
        ],
    }

    output_path = generate_pa_pdf(
        case_id="TEST-CASE-001",
        content=mock_content,
        uploaded_file_paths=[],
    )

    print(f"\n[OK] PDF generated successfully!")
    print(f"   Path: {output_path}")

    if os.path.exists(output_path):
        size_kb = os.path.getsize(output_path) / 1024
        print(f"   Size: {size_kb:.1f} KB")
    return output_path


def test_full_pa_generation():
    """Full flow -- requires GOOGLE_API_KEY + DB with a real case."""
    print("\n" + "=" * 60)
    print("TEST 2: Full PA Generation (LLM + DB)")
    print("=" * 60)

    from dotenv import load_dotenv
    load_dotenv(os.path.join(backend_dir, ".env"))
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("[SKIP] GOOGLE_API_KEY not set -- skipping full LLM test.")
        return

    from agents import generate_pa_content
    from services.pdf_generator import generate_pa_pdf

    case_id = "PA-20260309-00002"
    print(f"Generating for case: {case_id}")

    try:
        content = generate_pa_content(case_id=case_id, pdf_path=None)
        output_path = generate_pa_pdf(case_id=case_id, content=content)
        print(f"\n[OK] Full PA PDF generated!")
        print(f"   Path: {output_path}")
        print(f"   Cover Letter (first 100 chars): {content['cover_letter'][:100]}...")
        print(f"   Checklist items: {len(content['checklist'])}")
    except Exception as e:
        print(f"[FAIL] Failed: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    print("PA Document Generator Tests")
    test_pdf_generator_no_llm()
    test_full_pa_generation()
    print("\n" + "=" * 60)
    print("Done.")
    print("=" * 60)
