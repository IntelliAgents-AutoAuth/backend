
import os
import sys
import json

# Ensure backend root is on sys.path
backend_dir = r"c:\Users\teja9\OneDrive\Desktop\IntelliAgents\backend"
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from tools.ehr_fetcher import fetch_extracted_data_by_case
from db.session import SessionLocal
from crud.crud_case import get_case

def test_fetcher():
    case_id = "PA-20260330-00066"
    print(f"--- Testing EHR Fetcher for {case_id} ---")
    
    data = fetch_extracted_data_by_case(case_id, extract_pdf_text=False)
    if not data:
        print("FAILED: No data found for case.")
        # Try to find any active case
        with SessionLocal() as db:
            from models.case import Case
            latest = db.query(Case).order_by(Case.created_at.desc()).first()
            if latest:
                print(f"Trying latest case: {latest.case_id}")
                case_id = latest.case_id
                data = fetch_extracted_data_by_case(case_id, extract_pdf_text=False)
    
    if data:
        print(f"SUCCESS: Data retrieved.")
        print(f"Payer Name: {data.get('payer_name')}")
        print(f"Insurance Company: {data.get('insurance_company')}")
        print(f"CPT Code: {data.get('cpt_code')}")
        print(f"Keys found: {list(data.keys())[:10]}...")
    else:
        print("FAILED: No data found for any case.")

if __name__ == "__main__":
    test_fetcher()
