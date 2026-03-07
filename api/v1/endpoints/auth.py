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

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "name": user_data["name"],
            "email": user_data["email"],
            "role": user_data["role"].value if hasattr(user_data["role"], 'value') else user_data["role"]
        }
    }
