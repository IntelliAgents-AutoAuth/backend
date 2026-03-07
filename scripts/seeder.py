from sqlalchemy.orm import Session
from models.user import User
from models.ehr_records import EHR
from mock_data.data import MOCK_USERS
from mock_data.ehr_records import MOCK_EHR_RECORDS
from core.security import get_password_hash

def seed_db(db: Session) -> None:
    """
    Seeds the database with mock users and EHR records if they don't already exist.
    """
    # Seed users
    for user_data in MOCK_USERS.values():
        user = db.query(User).filter(User.email == user_data["email"]).first()
        if not user:
            db_obj = User(
                email=user_data["email"],
                hashed_password=get_password_hash(user_data["password"]),
                full_name=user_data["full_name"] if "full_name" in user_data else user_data.get("name"),
                role=user_data["role"],
                is_active=True
            )
            db.add(db_obj)
    db.commit()
    print("[OK] Successfully seeded database with mock users.")

    # Seed records from EHR data
    for record_data in MOCK_EHR_RECORDS:
        db_record = db.query(EHR).filter(EHR.patient_id == record_data["patient_id"]).first()
        if not db_record:
            db_obj = EHR(**record_data)
            db.add(db_obj)
        else:
            # Update existing record with new data
            for key, value in record_data.items():
                setattr(db_record, key, value)
    db.commit()
    print("[OK] Successfully seeded database with EHR records.")
