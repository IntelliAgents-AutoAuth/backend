from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from sqlalchemy.orm import Session
from schemas.auth import EHR as EHRSchema
from models.ehr import EHR
from models.user import User
from core.security import get_current_user
from api.deps import get_db

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("/", response_model=List[EHRSchema])
async def list_cases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all cases assigned to the authenticated user."""
    user_cases = db.query(EHR).filter(
        EHR.assigned_to == current_user.email
    ).all()
    return user_cases


@router.get("/{case_id}", response_model=EHRSchema)
async def get_case(
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fetch full details of a specific EHR record by case_id.
    Ensures the case belongs to the authenticated user.
    """
    db_case = db.query(EHR).filter(EHR.case_id == case_id).first()
    
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found"
        )
    
    # Ownership/Permission check
    if db_case.assigned_to != current_user.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this case"
        )
    
    return db_case
