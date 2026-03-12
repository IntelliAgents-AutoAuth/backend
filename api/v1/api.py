from fastapi import APIRouter
from api.v1.endpoints.auth import router as auth_router
from api.v1.endpoints.cases import router as cases_router
from api.v1.test_routes import router as test_router

api_router = APIRouter()

# Include auth routes
api_router.include_router(auth_router)
# Include cases routes
api_router.include_router(cases_router)

        # below line is written for testing purpose only 
api_router.include_router(test_router, prefix="/test", tags=["Test Routes"])