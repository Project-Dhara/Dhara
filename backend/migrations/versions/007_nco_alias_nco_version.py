"""Add nco_version to nco_value_aliases for version-dependent steward mappings.

Revision ID: 007_nco_alias_nco_version
Revises: 006_llm_base_url_model
Create Date: 2026-04-09

Additive only — ALTER TABLE ADD COLUMN IF NOT EXISTS.
Does NOT clear or rewrite alias rows.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "007_nco_alias_nco_version"
down_revision: Union[str, None] = "006_llm_base_url_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "ALTER TABLE nco_value_aliases "
            "ADD COLUMN IF NOT EXISTS nco_version TEXT DEFAULT '2015'"
        )
    )
    conn.execute(
        text(
            "UPDATE nco_value_aliases "
            "SET nco_version = '2015' "
            "WHERE nco_version IS NULL"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("ALTER TABLE nco_value_aliases DROP COLUMN IF EXISTS nco_version"))
