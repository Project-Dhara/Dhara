"""Approved NCO occupation aliases for search enrichment.

Revision ID: 005_nco_occupation_aliases
Revises: 004_dataset_id_counters
Create Date: 2026-10-30

Additive only — CREATE TABLE IF NOT EXISTS.
These rows are curated synonyms. Steward Verify mappings stay in nco_value_aliases.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "005_nco_occupation_aliases"
down_revision: Union[str, None] = "004_dataset_id_counters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS nco_occupation_aliases (
                normalized_alias TEXT NOT NULL,
                nco_code TEXT NOT NULL,
                alias_text TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'alias',
                source TEXT NOT NULL DEFAULT 'curated',
                PRIMARY KEY (normalized_alias, nco_code)
            )
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS nco_occupation_aliases"))
