from fastapi import APIRouter
from api.v1.test_routes import router as test_router

api_router = APIRouter()


        # below line is written for testing purpose only 
api_router.include_router(test_router, prefix="/test", tags=["Test Routes"])
