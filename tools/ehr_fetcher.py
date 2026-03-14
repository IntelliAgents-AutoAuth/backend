"""EHR fetcher utilities.

This module provides helpers to fetch EHR-related data from the local database.
"""

from typing import Any, Dict, Optional

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
        db_obj = get_extracted_data(db, case_id)
        if not db_obj:
            return None

        # Use the Pydantic schema to serialize the SQLAlchemy model cleanly.
        return ExtractedDataSchema.from_orm(db_obj).model_dump()
