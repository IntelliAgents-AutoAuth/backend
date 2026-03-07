from fastapi import APIRouter, HTTPException, status
from schemas.auth import LoginRequest, Token
from core.security import create_access_token
from mock_data.data import MOCK_USERS

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=Token)
async def login(credentials: LoginRequest):
    user_data = None
    for key, mock_user in MOCK_USERS.items():
        if mock_user["email"] == credentials.username:
            user_data = mock_user
            break

    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.password != user_data["password"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, _ = create_access_token(data={
        "sub": user_data["email"],
        "user_id": 1, # Mock ID
        "role": user_data["role"].value if hasattr(user_data["role"], 'value') else user_data["role"]
    })

    #   if not db_user:
    #         print(f"DEBUG: Auto-registering new user: {credentials.username}")
    #         db_user = User(
    #             email=credentials.username,
    #             hashed_password=get_password_hash(credentials.password),
    #             full_name=credentials.username.split("@")[0],
    #             role=UserRole.PA_COORDINATOR,
    #             is_active=True
    #         )
    #         db.add(db_user)
    #         db.commit()
    #         db.refresh(db_user)
    #         password_verified = True
    #     else:
    #         password_verified = verify_password(
    #             credentials.password, 
    #             db_user.hashed_password, 
    #             username=credentials.username
    #         )
    #         print(f"DEBUG: Password verification for {credentials.username}: {password_verified}")

    #     if not password_verified:
    #         raise HTTPException(
    #             status_code=status.HTTP_401_UNAUTHORIZED,
    #             detail="Invalid credentials",
    #             headers={"WWW-Authenticate": "Bearer"},
    #         )

    #     if not db_user.is_active:
    #         raise HTTPException(
    #             status_code=status.HTTP_401_UNAUTHORIZED,
    #             detail="Inactive user",
    #             headers={"WWW-Authenticate": "Bearer"},
    #         )

    #     access_token, _ = create_access_token(data={
    #         "sub": db_user.email,
    #         "user_id": db_user.id,
    #         "role": db_user.role.value if hasattr(db_user.role, 'value') else db_user.role
    #     })

    #     return {
    #         "access_token": access_token,
    #         "token_type": "bearer",
    #         "user": {
    #             "name": db_user.full_name,
    #             "email": db_user.email,
    #             "role": db_user.role.value if hasattr(db_user.role, 'value') else db_user.role
    #         }

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "name": user_data["name"],
            "email": user_data["email"],
            "role": user_data["role"].value if hasattr(user_data["role"], 'value') else user_data["role"]
        }
    }
