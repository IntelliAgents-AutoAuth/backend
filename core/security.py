from datetime import datetime, timedelta, timezone
from typing import Optional,List
from jose import JWTError, jwt, JWTError, ExpiredSignatureError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from core.config import settings
import hashlib
import hmac
from sqlalchemy.orm import Session
from api.deps import get_db
from models.user import User
from constants import UserRole

# Import the logger functions from utils.logger
from utils.logger import (
    log_login_success,
    log_login_failed,
    log_logout,
    log_token_expired
)
# OAuth2 scheme for retrieving token from Authorization header
# This tells FastAPI that the frontend will provide a token to access protected routes.
# `tokenUrl` is just documentation for OpenAPI, it doesn't do the token creation here. 
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


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
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        
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
        # ---- LOGGING: TOKEN EXPIRED ----
        # We explicitly catch expiration so we can tell the user they need to log in again.
        # Decode without verifying expiration just to extract the user email for the log.
        try:
            expired_payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], options={"verify_exp": False})
            email = expired_payload.get("sub", "Unknown")
            log_token_expired(username=email)
        except Exception:
            pass # If it completely fails to decode, ignore.
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired after 8 hours. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        # Any other token error (tampered signature, malformed token) is blocked.
        raise credentials_exception



def verify_password(plain_password: str, hashed_password: str, username: str = None) -> bool:
    """Verify a plain password against a hashed password using SHA256 with salt."""
    is_valid = False
    try:
        # Split the stored hash to get salt and hash
        if '$' in hashed_password:
            salt, stored_hash = hashed_password.split('$', 1)
            computed_hash = hashlib.sha256((salt + plain_password).encode()).hexdigest()
            is_valid = hmac.compare_digest(computed_hash, stored_hash)
    except Exception:
        pass
        
    # Fallback for plaintext comparison (shouldn't happen)
    if not is_valid:
        is_valid = (plain_password == hashed_password)

    # ---- LOGGING: LOGIN FAILED ----
    # Log if the password verification fails and we have the username.
    if not is_valid and username:
        log_login_failed(username=username, reason="Invalid credentials during password verification")

    return is_valid

def get_password_hash(password: str) -> str:
    """Hash a password using SHA256 with a salt."""
    import secrets
    # Generate a random salt
    salt = secrets.token_hex(16)
    # Hash password with salt
    hash_obj = hashlib.sha256((salt + password).encode()).hexdigest()
    # Return salt$hash format
    return f"{salt}${hash_obj}"

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> tuple:
    """Create a JWT access token and return token with expiry time."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )

    # ---- LOGGING: LOGIN SUCCESS ----
    # When a token is successfully created, it implies a successful login.
    username = data.get("sub")
    if username:
        log_login_success(username=username)

    return encoded_jwt, expire

def decode_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def process_logout(token: str) -> bool:
    """
    Helper function to process user logout from a route.
    It decodes the token to get the user information and logs the logout event.
    Eventually, token blacklisting logic could be added here.
    """
    try:
        # Decode without verifying expiration to ensure we can log even if it just expired
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], options={"verify_exp": False})
        email = payload.get("sub", "Unknown")
        
        # ---- LOGGING: LOGOUT ----
        log_logout(username=email)
        return True
    except Exception:
        # If token is invalid, we might not be able to reliably identify the user to log logout
        return False


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
    
