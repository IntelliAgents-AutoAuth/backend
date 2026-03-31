"""
IntelliAgents Backend — FastAPI Entry Point
===========================================

This is the main initialization file for the IntelliAgents backend. It sets up 
the core infrastructure required for the AI agents to operate, including 
database connections, observability, and administrative interfaces.

Key Components:
---------------
1. **Bootstrapping**: Handles critical Windows-specific environment settings 
   (Phoenix working directory) and observability setup.
2. **Database Management**: Automatically runs migrations and ensures that the 
   SQL schema is up-to-date.
3. **Mock Data Seeding**: Populates the database with initial patient/case 
   data for immediate testing and demonstration.
4. **API Routing**: Mounts the versioned API router (v1) which contains all 
   business logic and orchestrator endpoints.
5. **Admin Dashboard**: Configures 'SQLAdmin', a web-based interface for 
   mentors/staff to view raw database records (Users, Cases, EHRs).
"""

import os

# CRITICAL: Set PHOENIX_WORKING_DIR before any other imports to fix Windows PermissionErrors
backend_dir = os.path.dirname(os.path.abspath(__file__))
px_data_dir = os.path.join(backend_dir, "data", "phoenix")
os.makedirs(px_data_dir, exist_ok=True)
os.environ["PHOENIX_WORKING_DIR"] = px_data_dir

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
# 1. Observability (Tracing & Logging)
from utils.logger import setup_observability
setup_observability()

# 2. Database Schema & Migration Management
from api.v1.api import api_router
from core.config import settings
from db import Base, engine
from sqladmin import Admin, ModelView
from models.user import User
from models.ehr_records import EHR
from models.cases import Case

# Ensure existing tables are updated to the latest schema
from scripts import migrate
migrate()

# Create any missing tables (e.g., on first run)
Base.metadata.create_all(bind=engine)

# Seed the database with high-quality mock data for the demo
from scripts import seed_db
seed_db()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Admin integration
class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.full_name, User.email, User.role, User.is_active]
    column_searchable_list = [User.full_name, User.email]
    column_sortable_list = [User.id]
    form_excluded_columns = [User.hashed_password]
    can_create = False
    can_edit = False
    icon = "fa-solid fa-user"

class CaseAdmin(ModelView, model=Case):
    column_list = [Case.case_id, Case.patient_id, Case.status, Case.created_by, Case.created_at]
    column_searchable_list = [Case.case_id, Case.patient_id]
    column_sortable_list = [Case.created_at]
    icon = "fa-solid fa-folder-medical"

class EHRAdmin(ModelView, model=EHR):
    column_list = [EHR.patient_id, EHR.patient_first_name, EHR.patient_last_name, EHR.insurance_company, EHR.created_at]
    column_searchable_list = [EHR.patient_id, EHR.patient_first_name, EHR.patient_last_name]
    column_sortable_list = [EHR.created_at]
    icon = "fa-solid fa-hospital-user"

admin = Admin(app, engine)
admin.add_view(UserAdmin)
admin.add_view(CaseAdmin)
admin.add_view(EHRAdmin)

# Set all CORS enabled origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
def root():
    return {"message": "Welcome to IntelliAgents Backend API (DB Configured)"}
