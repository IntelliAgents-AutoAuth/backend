from fastapi import APIRouter, Depends
from core.security import verify_and_get_token_data

router = APIRouter()

@router.get("/test-protected")
def test_protected_route(user_email: str = Depends(verify_and_get_token_data)):
    """
    This is a test route to verify that our security.py logic works.
    If the JWT token is missing, invalid, or expired, this route will return a 401 error.
    If the token is valid, it will return the user's email.
    """
    return {
        "status": "success", 
        "message": "You have successfully accessed a protected route!", 
        "user_email": user_email
    }
