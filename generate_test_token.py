import time
from jose import jwt
from datetime import datetime, timedelta

# MUST MATCH core/config.py and security.py!
ALGORITHM = "HS256"
SECRET_KEY = "YOUR_SUPER_SECRET_KEY"  # Replace if you have a real one in config

def create_demo_token(email: str, expires_in_minutes: int = 8 * 60):
    expire = datetime.utcnow() + timedelta(minutes=expires_in_minutes)
    to_encode = {"exp": expire, "sub": email}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    print(f"\n--- DEMO TOKEN FOR {email} ---")
    print(f"Expires in {expires_in_minutes} minutes")
    print("-" * 50)
    print(encoded_jwt)
    print("-" * 50)
    print("Copy the token above and use it in Postman as a Bearer Token!\n")

if __name__ == "__main__":
    create_demo_token("testuser@intelliagents.com")
