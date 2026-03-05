from fastapi import APIRouter
from api.v1.endpoints.auth import router as auth_router
from api.v1.endpoints.cases import router as cases_router

api_router = APIRouter()

# Include auth routes
api_router.include_router(auth_router)
# Include cases routes
api_router.include_router(cases_router)
