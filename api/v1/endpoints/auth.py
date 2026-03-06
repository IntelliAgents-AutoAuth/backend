from fastapi import APIRouter, HTTPException, status
from schemas.auth import LoginRequest, Token
from core.security import create_access_token, verify_password
from db.session import SessionLocal
from models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=Token)
async def login(credentials: LoginRequest):
    """
    Login endpoint that authenticates user against the database and returns a JWT token.

    Args:
        credentials: Login credentials — username is the user's email, password is plain text

    Returns:
        Token object with access_token and token_type

    Raises:
        HTTPException: 401 Unauthorized if credentials are invalid
    """
    db = SessionLocal()
    try:
        # Look up user by email
        print(f"DEBUG: Attempting login for email: {credentials.username}")
        db_user = db.query(User).filter(User.email == credentials.username).first()

        if not db_user:
            print(f"DEBUG: User not found: {credentials.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        password_verified = verify_password(credentials.password, db_user.hashed_password)
        print(f"DEBUG: Password verification for {credentials.username}: {password_verified}")

        if not password_verified:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not db_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Inactive user",
                headers={"WWW-Authenticate": "Bearer"},
            )

        access_token, _ = create_access_token(data={
            "sub": db_user.email,
            "user_id": db_user.id,
<<<<<<< Updated upstream
            "role": db_user.role,
=======
            "role": db_user.role.value if hasattr(db_user.role, 'value') else db_user.role
>>>>>>> Stashed changes
        })

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "name": db_user.full_name,
                "email": db_user.email,
                "role": db_user.role.value if hasattr(db_user.role, 'value') else db_user.role
            }
        }
    finally:
        db.close()
