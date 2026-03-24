"""EHR fetcher utilities.

This module provides helpers to fetch EHR-related data from the local database.
"""

import os
from typing import Any, Dict, Optional

from langchain_core.tools import tool
from crud.crud_extracted_data import get_extracted_data
from db.session import SessionLocal
from schemas.extracted_data import ExtractedData as ExtractedDataSchema

# Base directory for the backend
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fetch_extracted_data_by_case(case_id: str, extract_pdf_text: bool = True) -> Optional[Dict[str, Any]]:
    """Query the `extracted_data` table for a given case_id.

    Args:
        case_id: The case identifier to look up.

    Returns:
        A dict containing the extracted data for the case, or None if not found.
    """

    with SessionLocal() as db:
        from crud.crud_case import get_case
        from tools.pdf_extractor import extract_raw_text
        
        # 1. Get structured data from EHR
        db_obj = get_extracted_data(db, case_id)
        result = {}
        if db_obj:
            result = ExtractedDataSchema.from_orm(db_obj).model_dump()

        # 2. Get files manually uploaded or fields entered by user
        db_case = get_case(db, case_id)
        if db_case and db_case.uploaded_files:
            processed_uploads = []
            for upload in db_case.uploaded_files:
                # Create a copy to avoid mutating the database object directly if it's persistent
                upload_data = dict(upload)
                
                # Extract text if it's a PDF
                file_path = upload_data.get("file_path") or upload_data.get("path")
                if file_path and not os.path.exists(file_path):
                    # Smart Fallback: Look in common directories if the specified path doesn't exist
                    print(f"[ehr_fetcher] File not found at {file_path}. Searching in backend directories...")
                    filename_only = os.path.basename(file_path)
                    doc_name_slug = (upload_data.get("document_name") or "").lower().replace(" ", "_")
                    
                    search_dirs = [
                        os.path.join(backend_dir, "patient_docs"),
                        os.path.join(backend_dir, "uploads"),
                    ]
                    
                    found_path = None
                    for sdir in search_dirs:
                        if not os.path.exists(sdir): continue
                        for root, _, files in os.walk(sdir):
                            for f in files:
                                # Match by exact filename OR starting with the document name slug
                                if f.lower() == filename_only.lower() or (doc_name_slug and f.lower().startswith(doc_name_slug)):
                                    found_path = os.path.join(root, f)
                                    break
                            if found_path: break
                        if found_path: break
                    
                    if found_path:
                        file_path = found_path
                        print(f"[ehr_fetcher] Found fallback file: {file_path}")

                if extract_pdf_text and file_path and os.path.exists(file_path) and file_path.lower().endswith(".pdf"):
                    try:
                        print(f"[ehr_fetcher] Extracting text from uploaded file: {file_path}")
                        extracted_text = extract_raw_text(file_path)
                        upload_data["extracted_text"] = extracted_text
                        print(f"[ehr_fetcher] Successfully extracted {len(extracted_text)} chars from {os.path.basename(file_path)}")
                    except Exception as e:
                        print(f"[ehr_fetcher] Failed to extract text from {file_path}: {e}")
                        upload_data["extracted_text"] = f"ERROR: Extraction failed - {str(e)}"
                elif extract_pdf_text:
                    # Provide specific reasons why extraction was skipped
                    if not file_path:
                        upload_data["extracted_text"] = "SKIPPED: No file path provided in upload metadata."
                    elif not os.path.exists(file_path):
                        upload_data["extracted_text"] = f"SKIPPED: File path does not exist on server: {file_path}"
                    elif not file_path.lower().endswith(".pdf"):
                        upload_data["extracted_text"] = f"SKIPPED: File type not supported for extraction: {os.path.splitext(file_path)[1]}"
                    else:
                        upload_data["extracted_text"] = "SKIPPED: Unknown reason (check logs)."
                else:
                    upload_data["extracted_text"] = "SKIPPED: API read mode (extract_pdf_text=False)"
                
                processed_uploads.append(upload_data)
                
                # 3. Flatten manual field entries into the record
                field_key = upload_data.get("missing_key")
                field_val = upload_data.get("field_value")
                
                # If it's a field value (non-file), add it to the main record
                if field_key and field_val is not None:
                    # Clean the key (lower case, underscores)
                    clean_key = field_key.lower().replace(" ", "_")
                    result[clean_key] = field_val
                    print(f"[ehr_fetcher] Injected manual field: {clean_key} = {field_val}")

            result["user_uploaded_files"] = processed_uploads

        return result if result else None

# Tool for use in LangChain agents
ehr_fetcher = tool(fetch_extracted_data_by_case)
