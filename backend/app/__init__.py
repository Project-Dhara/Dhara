"""Application package for the backend architecture.

Phase 2: ``app.main.create_app`` builds the FastAPI app; ``backend/main.py``
re-exports it for ``uvicorn main:app``. Live domain handlers remain under
``routes/``, ``catalogue/``, ``pdf/``, ``data_ingestion/``, etc.
"""
