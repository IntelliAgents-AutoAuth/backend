from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from core.config import settings
import hashlib
import hmac

# OAuth2 scheme for retrieving token from Authorization header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password using SHA256 with salt."""
    try:
        # Split the stored hash to get salt and hash
        if '$' in hashed_password:
            salt, stored_hash = hashed_password.split('$', 1)
            computed_hash = hashlib.sha256((salt + plain_password).encode()).hexdigest()
            return hmac.compare_digest(computed_hash, stored_hash)
    except Exception:
        pass
    # Fallback for plaintext comparison (shouldn't happen)
    return plain_password == hashed_password

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


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Dependency to retrieve the current authenticated user from the token."""
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username: str = payload.get("sub")
    return {"username": username}
