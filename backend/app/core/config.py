"""Centralized application settings (environment-driven).

Today: ``DATABASE_URL``, ``JWT_SECRET``, GCS flags, MCP auth, and related
values are read via ``os.environ`` in catalogue, auth, and MCP modules.
``backend/config.py`` is prompt/template configuration, not settings.
Phase 2+ will gather operational settings here without hardcoding secrets.
"""
