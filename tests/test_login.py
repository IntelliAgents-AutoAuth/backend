import sys
import json
from db.session import SessionLocal
from models.user import User

# Test with database users
db = SessionLocal()
users = db.query(User).all()
print("Database Users:")
for user in users:
    print(f"  ID: {user.id}, Email: {user.email}, Role: {user.role}")
db.close()
