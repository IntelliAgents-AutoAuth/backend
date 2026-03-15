"""EHR fetcher utilities.

This module provides helpers to fetch EHR-related data from the local database.
"""

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
        
        # 1. Get structured data from EHR
        db_obj = get_extracted_data(db, case_id)
        result = {}
        if db_obj:
            result = ExtractedDataSchema.from_orm(db_obj).model_dump()

        # 2. Get files manually uploaded or fields entered by user
        db_case = get_case(db, case_id)
        if db_case and db_case.uploaded_files:
            result["user_uploaded_files"] = db_case.uploaded_files
            
            # 3. Flatten manual field entries into the record
            for upload in db_case.uploaded_files:
                field_key = upload.get("missing_key")
                field_val = upload.get("field_value")
                
                # If it's a field value (non-file), add it to the main record
                if field_key and field_val is not None:
                    # Clean the key (lower case, underscores)
                    clean_key = field_key.lower().replace(" ", "_")
                    result[clean_key] = field_val
                    print(f"[ehr_fetcher] Injected manual field: {clean_key} = {field_val}")

        return result if result else None

# Tool for use in LangChain agents
ehr_fetcher = tool(fetch_extracted_data_by_case)
