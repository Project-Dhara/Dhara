"""Grouping service — PDF propose/apply + catalogue table matching."""
from __future__ import annotations

from app.services.grouping.matching import (
    build_group_name,
    match_tables_to_metadata,
)
from app.services.grouping.pdf_grouping import (
    apply_proposal_to_db,
    propose_groups,
    propose_groups_from_table_dicts,
)

__all__ = [
    "apply_proposal_to_db",
    "build_group_name",
    "match_tables_to_metadata",
    "propose_groups",
    "propose_groups_from_table_dicts",
]
