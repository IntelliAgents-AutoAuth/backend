import os
from pydantic_settings import BaseSettings

# Calculate the base directory (backend folder)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Settings(BaseSettings):
    PROJECT_NAME: str = "IntelliAgents Backend"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = f"sqlite:///{os.path.join(BASE_DIR, 'data', 'autoauth.db')}"
    
    # JWT Settings
    SECRET_KEY: str = "your-secret-key-change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    class Config:
        case_sensitive = True

settings = Settings()
