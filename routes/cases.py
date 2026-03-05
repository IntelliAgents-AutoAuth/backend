from fastapi import APIRouter, Depends
from typing import List
from api.schemas import Case
from core.security import get_current_user

router = APIRouter(prefix="/cases", tags=["cases"])

# Mock case data keyed by username
MOCK_CASES = {
    "testuser": [
        {
            "case_id": 1,
            "patient_name": "John Doe",
            "procedure": "Appendectomy",
            "status": "active",
            "created_at": "2026-01-15T10:00:00Z",
        },
        {
            "case_id": 2,
            "patient_name": "Jane Smith",
            "procedure": "Knee Replacement",
            "status": "closed",
            "created_at": "2025-12-22T14:30:00Z",
        },
    ],
    "admin": [
        {
            "case_id": 10,
            "patient_name": "Alice Johnson",
            "procedure": "Hip Surgery",
            "status": "active",
            "created_at": "2026-02-01T09:15:00Z",
        }
    ],
}

@router.get("/", response_model=List[Case])
async def list_cases(current_user: dict = Depends(get_current_user)):
    """Return all active cases for the authenticated user."""
    username = current_user["username"]
    user_cases = MOCK_CASES.get(username, [])
    # filter only active cases
    active_cases = [case for case in user_cases if case.get("status") == "active"]
    return active_cases
