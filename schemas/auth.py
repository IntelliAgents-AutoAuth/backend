from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class LoginRequest(BaseModel):
    """Request body for login endpoint."""
    username: str
    password: str

class Token(BaseModel):
    """Response body for token."""
    access_token: str
    token_type: str = "bearer"

