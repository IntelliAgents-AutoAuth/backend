import os
import sys

# Ensure the backend directory is in sys.path for local imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

from tools.ehr_fetcher import ehr_fetcher
from tools.pdf_extractor import pdf_extractor
from agents.gap_analysis_agent import run_gap_analysis

def test_ehr_fetcher():
    print("\n--- Testing ehr_fetcher ---")
    case_id = "CASE_001"
    result = ehr_fetcher.invoke({"case_id": case_id})
    print(f"Result for {case_id}:")
    print(result)
    return result

def test_pdf_extractor():
    print("\n--- Testing pdf_extractor ---")
    # Using the default test PDF path we configured earlier
    default_dir = os.path.join("policy-pdfs", "aetna")
    default_filename = "test_doc.pdf"
    pdf_path = os.path.join(backend_dir, default_dir, default_filename)
    
    if os.path.exists(pdf_path):
        print(f"Extracting from: {pdf_path}")
        result = pdf_extractor.invoke({"pdf_path": pdf_path})
        print(f"Extracted Text (first 200 chars):")
        print(result[:200] + "...")
    else:
        print(f"PDF not found at {pdf_path}, skipping extraction test.")
        result = None
    return result

def test_run_gap_analysis():
    print("\n--- Testing run_gap_analysis (Full Agent Run) ---")
    print("Note: This requires a valid GOOGLE_API_KEY in .env")
    try:
        case_id = "CASE_001"
        result = run_gap_analysis(case_id=case_id)
        print("Final Agent Response:")
        print(result)
    except Exception as e:
        print(f"Agent run failed (likely missing/invalid API key): {e}")

if __name__ == "__main__":
    print("Starting Gap Analysis Tests...")
    
    # 1. Test EHR Fetcher
    test_ehr_fetcher()
    
    # 2. Test PDF Extractor
    test_pdf_extractor()
    
    
    print("\nTests completed.")
