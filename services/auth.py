from typing import Optional
from core.security import verify_password, get_password_hash

from typing import Optional
from sqlalchemy.orm import Session
from crud.crud_user import get_user_by_email
from core.security import verify_password, get_password_hash
from models.user import User

class AuthenticationService:
    """Service for handling authentication operations."""

    @staticmethod
    def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
        """
        Authenticate a user with username and password against the database.
        """
        user = get_user_by_email(db, email=username)
        if not user:
            return None

        if not verify_password(password, user.hashed_password, username=username):
            return None

        if not user.is_active:
            return None

        return user

authentication_service = AuthenticationService()
