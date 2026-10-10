"""Aggregate API routers for the application factory.

Mounts the live route modules under ``backend/routes/`` plus health.
URL contracts are unchanged. Business logic still lives in those modules
and catalogue/pdf helpers; Phase 2 only establishes the registration path.
"""
from fastapi import APIRouter

from app.api.routes import health as routes_health
from routes import access as routes_access
from routes import auth as routes_auth
from routes import catalogue as routes_catalogue
from routes import dashboard as routes_dashboard
from routes import kyds as routes_kyds
from routes import llm_key as routes_llm_key
from routes import pdf as routes_pdf
from routes import upload as routes_upload

api_router = APIRouter()
api_router.include_router(routes_health.router)
api_router.include_router(routes_auth.router)
api_router.include_router(routes_kyds.router)
api_router.include_router(routes_llm_key.router)
api_router.include_router(routes_catalogue.router)
api_router.include_router(routes_pdf.router)
api_router.include_router(routes_upload.router)
api_router.include_router(routes_dashboard.router)
api_router.include_router(routes_access.router)
