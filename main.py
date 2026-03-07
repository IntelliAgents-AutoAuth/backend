from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from api.v1.api import api_router
from core.config import settings
from db.base import Base
from db.session import engine
from sqladmin import Admin, ModelView
from models.user import User
from models.ehr_records import EHR
from models.cases import Case
from models.extracted_data import ExtractedData

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize DB with mock data
from scripts.seeder import seed_db
from db.session import SessionLocal
with SessionLocal() as db:
    seed_db(db)

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

class ExtractedDataAdmin(ModelView, model=ExtractedData):
    column_list = [ExtractedData.case_id, ExtractedData.patient_id, ExtractedData.confidence_overall, ExtractedData.created_at]
    column_searchable_list = [ExtractedData.case_id, ExtractedData.patient_id]
    column_sortable_list = [ExtractedData.created_at]
    icon = "fa-solid fa-microscope"

admin = Admin(app, engine)
admin.add_view(UserAdmin)
admin.add_view(CaseAdmin)
admin.add_view(EHRAdmin)
admin.add_view(ExtractedDataAdmin)

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
