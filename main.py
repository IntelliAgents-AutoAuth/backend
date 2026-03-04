from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from api.v1.api import api_router
from core.config import settings
from db.base import Base
from db.session import engine
from sqladmin import Admin, ModelView
from models.user import User

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize DB with mock data
from mock.seeder import seed_db
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
    icon = "fa-solid fa-user"

admin = Admin(app, engine)
admin.add_view(UserAdmin)

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
