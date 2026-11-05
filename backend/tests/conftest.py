"""Shared pytest bootstrap — required env before the app is imported."""
from __future__ import annotations

import os

# Must run before test modules import ``main`` / ``app.main``.
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://dhara:dhara_local_password@localhost:5432/dhara",
)
