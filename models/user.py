from sqlalchemy import Boolean, Column, Integer, String
from db.base import Base

from constants import UserRole

class User(Base):
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False) # e.g., UserRole.PA_COORDINATOR, UserRole.PHYSICIAN
    is_active = Column(Boolean(), default=True)
