from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from schemas.auth import LoginRequest, Token
from core.security import create_access_token, verify_password
from api.deps import get_db
from crud.crud_user import get_user_by_email
from utils.logger import log_login_failed
router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=Token)
async def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db, email=credentials.username)

    if not user:
        log_login_failed(username=credentials.username, reason="User not found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(credentials.password, user.hashed_password, username=credentials.username):
        # verify_password handles the log_login_failed call for "Invalid credentials"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, _ = create_access_token(data={
        "sub": user.email,
        "user_id": user.id,
        "role": user.role # Enum or String from DB
    })

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }
