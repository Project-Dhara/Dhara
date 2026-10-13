"""Compatibility process entry for ``uvicorn main:app``.

Application construction lives in ``app.main``. This module only loads
environment variables and re-exports ``app`` so existing ``run.sh``,
``start.sh``, and Docker commands keep working.
"""
from dotenv import load_dotenv

load_dotenv()

from app.main import app  # noqa: E402

__all__ = ["app"]
