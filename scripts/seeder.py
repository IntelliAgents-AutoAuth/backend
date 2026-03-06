from sqlalchemy.orm import Session
from models.user import User
from models.ehr import EHR
from mock_data.data import MOCK_USERS
from mock_data.ehrData import MOCK_EHR_CASES
from core.security import get_password_hash

def seed_db(db: Session) -> None:
    """
    Seeds the database with mock users and EHR cases if they don't already exist.
    """
    # Seed users
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

    # Seed cases from EHR data
    for case_data in MOCK_EHR_CASES:
        db_case = db.query(EHR).filter(EHR.case_id == case_data["case_id"]).first()
        if not db_case:
            db_obj = EHR(**case_data)
            db.add(db_obj)
        else:
            # Update existing case with new data
            for key, value in case_data.items():
                setattr(db_case, key, value)
    db.commit()
    print("[OK] Successfully seeded database with EHR cases.")
