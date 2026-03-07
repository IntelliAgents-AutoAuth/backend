from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from sqlalchemy.orm import Session
from schemas.cases import Case as CaseSchema, CaseCreate
from models.cases import Case
from models.user import User
from core.security import get_current_user
from api.deps import get_db
from crud import crud_case

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("/", response_model=CaseSchema)
async def create_new_case(
    case_in: CaseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new case with automatic ID and draft status."""
    return crud_case.create_case(db, case_in=case_in, created_by=current_user.email)


@router.get("/", response_model=List[CaseSchema])
async def list_cases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all cases."""
    # Note: Depending on requirements, we might filter by created_by here
    return crud_case.get_cases(db)


@router.get("/{case_id}", response_model=CaseSchema)
async def get_case_details(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch details of a specific case."""
    db_case = crud_case.get_case(db, case_id=case_id)
    if not db_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case with ID {case_id} not found"
        )
    return db_case
