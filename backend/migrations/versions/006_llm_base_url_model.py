"""Add base_url and model columns to llm_api_keys for self-hosted / Ollama.

Revision ID: 006_llm_base_url_model
Revises: 005_nco_occupation_aliases
Create Date: 2026-11-23

Additive only — ALTER TABLE ADD COLUMN IF NOT EXISTS.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "006_llm_base_url_model"
down_revision: Union[str, None] = "005_nco_occupation_aliases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS base_url TEXT"))
    conn.execute(text("ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS model TEXT"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("ALTER TABLE llm_api_keys DROP COLUMN IF EXISTS model"))
    conn.execute(text("ALTER TABLE llm_api_keys DROP COLUMN IF EXISTS base_url"))
