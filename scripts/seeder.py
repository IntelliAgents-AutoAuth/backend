from sqlalchemy.orm import Session
from models.user import User
from mock_data.data import MOCK_USERS
from core.security import get_password_hash

def seed_db(db: Session) -> None:
    """
    Seeds the database with mock users if they don't already exist.
    Passwords are hashed using bcrypt before storing.
    """
    for key, user_data in MOCK_USERS.items():
        user = db.query(User).filter(User.email == user_data["email"]).first()
        if not user:
            db_obj = User(
                email=user_data["email"],
                hashed_password=get_password_hash(user_data["password"]),
                full_name=user_data["name"],
                role=user_data["role"],
                is_active=True
            )
            db.add(db_obj)
    db.commit()
    print("[OK] Successfully seeded database with mock users.")
