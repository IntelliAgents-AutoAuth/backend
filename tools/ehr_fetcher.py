"""EHR fetcher utilities.

This module provides helpers to fetch EHR-related data from the local database.
"""

import os
from typing import Any, Dict, Optional

from langchain_core.tools import tool
from crud.crud_extracted_data import get_extracted_data
from db.session import SessionLocal
from schemas.extracted_data import ExtractedData as ExtractedDataSchema


def fetch_extracted_data_by_case(case_id: str) -> Optional[Dict[str, Any]]:
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
                if file_path and os.path.exists(file_path) and file_path.lower().endswith(".pdf"):
                    try:
                        print(f"[ehr_fetcher] Extracting text from uploaded file: {file_path}")
                        upload_data["extracted_text"] = extract_raw_text(file_path)
                    except Exception as e:
                        print(f"[ehr_fetcher] Failed to extract text from {file_path}: {e}")
                        upload_data["extracted_text"] = f"ERROR: Could not extract text. {e}"
                
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
