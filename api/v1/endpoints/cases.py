from fastapi import APIRouter, Depends
from typing import List
from schemas.auth import Case
from core.security import get_current_user

router = APIRouter(prefix="/cases", tags=["cases"])

# Mock case data keyed by username
MOCK_CASES = {
    "sai@example.com": [
        {
            "case_id": 1,
            "patient_name": "John Doe",
            "procedure": "Appendectomy",
            "status": "APPROVED",
            "created_at": "2026-01-15T10:00:00Z",
        },
        {
            "case_id": 2,
            "patient_name": "Jane Smith",
            "procedure": "Knee Replacement",
            "status": "DENIED",
            "created_at": "2025-12-22T14:30:00Z",
        },
    ],
    "admin@example.com": [
        {
            "case_id": 10,
            "patient_name": "Alice Johnson",
            "procedure": "Hip Surgery",
            "status": "APPROVED",
            "created_at": "2026-02-01T09:15:00Z",
        }
    ],
}

@router.get("/", response_model=List[Case])
async def list_cases(current_user=Depends(get_current_user)):
    """Return all cases for the authenticated user."""
    email = current_user.email
    user_cases = MOCK_CASES.get(email, [])
    return user_cases

@router.post("/", response_model=Case)
async def create_case(payload: dict, current_user=Depends(get_current_user)):
    """Initialize a new case."""
    email = current_user.email
    if email not in MOCK_CASES:
        MOCK_CASES[email] = []
    
    import random
    from datetime import datetime
    
    new_case = {
        "case_id": random.randint(1000, 9999),
        "patient_name": payload.get("patientName", "TBD"),
        "procedure": f"CPT: {payload.get('cptCode', 'N/A')} ({payload.get('insuranceName', 'TBD')})",
        "status": "PROCESSING",
        "created_at": datetime.now()
    }
    
    MOCK_CASES[email].append(new_case)
    return new_case
