from enum import Enum

class UserRole(str, Enum):
    PA_COORDINATOR = "PA_COORDINATOR"
    PHYSICIAN = "PHYSICIAN"
    ADMIN = "ADMIN"
