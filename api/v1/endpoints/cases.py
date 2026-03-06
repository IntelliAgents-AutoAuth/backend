from fastapi import APIRouter, Depends
from typing import List
from sqlalchemy.orm import Session
from schemas.auth import Case as CaseSchema
from models.case import Case
from models.user import User
from core.security import get_current_user
from api.deps import get_db

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("/", response_model=List[CaseSchema])
async def list_cases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all cases assigned to the authenticated user."""
    user_cases = db.query(Case).filter(
        Case.assigned_to == current_user.email
    ).all()
    return user_cases
