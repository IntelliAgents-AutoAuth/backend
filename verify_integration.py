
import os
import sys
import json

backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from tools.ehr_fetcher import fetch_extracted_data_by_case
from db.session import SessionLocal
from models.cases import Case

def verify_file_integration(case_id: str):
    print(f"\n--- Verifying File Integration for Case: {case_id} ---")
    
    with SessionLocal() as db:
        db_case = db.query(Case).filter(Case.case_id == case_id).first()
        if not db_case:
            print(f"Error: Case {case_id} not found.")
            return

        print(f"Case Status: {db_case.status}")
        print(f"Uploaded Files Count: {len(db_case.uploaded_files) if db_case.uploaded_files else 0}")
        
    result = fetch_extracted_data_by_case(case_id)
    if result and "user_uploaded_files" in result:
        uploads = result["user_uploaded_files"]
        print(f"Processed Uploads in EHR: {len(uploads)}")
        for up in uploads:
            name = up.get("document_name") or up.get("file_path")
            has_text = "extracted_text" in up and len(up["extracted_text"]) > 0
            text_preview = up.get("extracted_text", "")[:100] + "..." if has_text else "NONE"
            print(f"  - File: {name}")
            print(f"    Extracted Text: {has_text} (Preview: {text_preview})")
    else:
        print("No user_uploaded_files found in extracted data.")

if __name__ == "__main__":
    # Use an existing case ID if possible
    case_id = "PA-20260309-00002" 
    verify_file_integration(case_id)
