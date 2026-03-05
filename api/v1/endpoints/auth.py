from fastapi import APIRouter, HTTPException, status
from schemas.auth import LoginRequest, Token
from services.auth import authentication_service
from core.security import create_access_token
from db.session import SessionLocal
from models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=Token)
async def login(credentials: LoginRequest):
    """
    Login endpoint that authenticates user and returns JWT token with user info.

    Args:
        credentials: Login credentials with username and password

    Returns:
        Token object with access_token, user_id, role, and expires_at

    Raises:
        HTTPException: 401 Unauthorized if credentials are invalid
    """
    user = authentication_service.authenticate_user(
        credentials.username,
        credentials.password
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user details from database
    db = SessionLocal()
    try:
        db_user = db.query(User).filter(User.email == user["email"]).first()
        if not db_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Create JWT token
        access_token, expires_at = create_access_token(data={"sub": user["username"]})

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": db_user.id,
            "role": db_user.role,
            "expires_at": expires_at
        }
    finally:
        db.close()
