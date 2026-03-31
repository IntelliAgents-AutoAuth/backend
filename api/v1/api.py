"""
API Router (v1) — Central Dispatcher
====================================

This file serves as the main entry point for all version 1 (v1) API routes. 
It aggregates multiple specialized routers (Auth, Cases, Payer, Test) into 
a single 'api_router' that is then mounted by the main FastAPI application.

Structure:
----------
- /auth: Authentication and user management.
- /cases: Core Prior Authorization logic, case management, and agents.
- /payer: Simulation of insurance payer endpoints and submissions.
- /test: Debugging and diagnostic routes (for development only).
"""

from fastapi import APIRouter
from api.v1.endpoints.auth import router as auth_router
from api.v1.endpoints.cases import router as cases_router
from api.v1.endpoints.payer import router as payer_router
from api.v1.test_routes import router as test_router

api_router = APIRouter()

# Include auth routes
api_router.include_router(auth_router)
# Include cases routes
api_router.include_router(cases_router)
# Include payer/provider routes
api_router.include_router(payer_router)

        # below line is written for testing purpose only 
api_router.include_router(test_router, prefix="/test", tags=["Test Routes"])
