"""Catalogue routes — split across extract/publish/browse/standards modules."""
from fastapi import APIRouter

from app.api.routes.catalogue_browse import router as browse_router
from app.api.routes.catalogue_extract import router as extract_router
from app.api.routes.catalogue_publish import router as publish_router
from app.api.routes.catalogue_standards import router as standards_router

router = APIRouter()
router.include_router(extract_router)
router.include_router(publish_router)
router.include_router(browse_router)
router.include_router(standards_router)
