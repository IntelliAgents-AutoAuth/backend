from typing import Optional
from core.security import verify_password, get_password_hash

# Mock user database - in production this would be a real database
# Passwords are hashed lazily when first accessed
_MOCK_USERS_DB = None

def get_mock_users_db():
    global _MOCK_USERS_DB
    if _MOCK_USERS_DB is None:
        _MOCK_USERS_DB = {
            "testuser": {
                "username": "testuser",
                "email": "test@example.com",
                "hashed_password": get_password_hash("password123"),
                "is_active": True,
            },
            "admin": {
                "username": "admin",
                "email": "admin@example.com",
                "hashed_password": get_password_hash("admin123"),
                "is_active": True,
            }
        }
    return _MOCK_USERS_DB

# This will be populated on first use
MOCK_USERS_DB = {}


class AuthenticationService:
    """Service for handling authentication operations."""

    @staticmethod
    def authenticate_user(username: str, password: str) -> Optional[dict]:
        """
        Authenticate a user with username and password.

        Args:
            username: The username to authenticate
            password: The plain text password

        Returns:
            User dict if authentication successful, None if failed
        """
        users_db = get_mock_users_db()
        user = users_db.get(username)
        if not user:
            return None

        # Verify the plaintext password against the hashed password
        if not verify_password(password, user["hashed_password"]):
            return None

        if not user["is_active"]:
            return None

        # Return user data without password
        return {
            "username": user["username"],
            "email": user["email"],
            "is_active": user["is_active"]
        }

    @staticmethod
    def get_user(username: str) -> Optional[dict]:
        """Get a user by username."""
        users_db = get_mock_users_db()
        user = users_db.get(username)
        if user:
            return {
                "username": user["username"],
                "email": user["email"],
                "is_active": user["is_active"]
            }
        return None

    @staticmethod
    def create_user(username: str, email: str, password: str) -> dict:
        """Create a new user (mock implementation)."""
        users_db = get_mock_users_db()
        if username in users_db:
            raise ValueError(f"User {username} already exists")

        user = {
            "username": username,
            "email": email,
            "hashed_password": get_password_hash(password),
            "is_active": True,
        }
        users_db[username] = user
        return {
            "username": user["username"],
            "email": user["email"],
            "is_active": user["is_active"]
        }

authentication_service = AuthenticationService()
