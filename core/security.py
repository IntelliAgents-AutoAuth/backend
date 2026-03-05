from typing import List, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError, ExpiredSignatureError
from sqlalchemy.orm import Session

from core.config import settings
from api.deps import get_db
from models.user import User
from constants.roles import UserRole

# This tells FastAPI that the frontend will provide a token to access protected routes.
# `tokenUrl` is just documentation for OpenAPI, it doesn't do the token creation here. 
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ALGORITHM = "HS256"
# Make sure SECRET_KEY is defined in your config.py so it matches what Hareesh uses!
SECRET_KEY = getattr(settings, "SECRET_KEY", "YOUR_SUPER_SECRET_KEY")

def verify_and_get_token_data(token: str = Depends(oauth2_scheme)):
    """
    PROTECTED ROUTE GATEKEEPER:
    Whenever a user visits a protected route (e.g., /api/cases/dashboard), 
    FastAPI will extract the token from the Authorization header and pass it here.
    We validate the token signature and check if it has expired. If anything is wrong,
    we block access and return a 401 error.
    """ 
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or token is missing",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # 1. jwt.decode automatically checks the 'exp' (expiration) claim on the token.
        # If the token is older than the 8 hours Hareesh set, it raises ExpiredSignatureError.
        # 2. It also checks the signature using the SECRET_KEY to ensure it wasn't tampered with.
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        email: str = payload.get("sub")
        user_id: int = payload.get("user_id")
        role: str = payload.get("role")
        
        if email is None or user_id is None or role is None:
            raise credentials_exception
            
        # Token is valid and not expired. We return the extracted data.
        return {
            "email": email,
            "user_id": user_id,
            "role": role
        }
        
    except ExpiredSignatureError:
        # We explicitly catch expiration so we can tell the user they need to log in again.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired after 8 hours. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        # Any other token error (tampered signature, malformed token) is blocked.
        raise credentials_exception

def get_current_user(token_data: dict = Depends(verify_and_get_token_data), db: Session = Depends(get_db)):
    """
    Fetches the full User object from the database using the user_id extracted from the token.
    If the user does not exist in the database, it restricts access.
    """
    user_id = token_data.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in the database."
        )
        
    if getattr(user, "is_active", None) is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
        
    return user


class RoleChecker:
    """
    Role-Based Access Control (RBAC) Dependency.
    Checks if the current authenticated user has one of the allowed roles.
    """
    def __init__(self, allowed_roles: List[UserRole]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: User = Depends(get_current_user)):
        user_role = getattr(user, "role", None) 
        
        if user_role not in [role.value for role in self.allowed_roles] and user_role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have enough permissions to perform this action"
            )
        
        return user
