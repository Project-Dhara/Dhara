"""Shared constants for PDF confidence / LLM validation."""
from __future__ import annotations

import re

CLASSIFICATION_FIELDS = ("domain", "subject", "entity", "table_type", "geography", "time_period", "frequency", "unit")

# Standardized human_review_reason values, in table-level tie-break priority
# order (most specific/actionable first). Field- and column-level reasons are
# never coerced to this priority -- each keeps its own reason; this ordering
# is only used to pick ONE reason for the table-level rollup when several
# different reasons are present underneath it.
#
# ADDED: "column_alignment_mismatch" -- deterministic post-LLM check when
# reconstructed cells clearly don't match their column (e.g. up/down under
# States/UTs, S.No. glued to a name, measure columns mostly empty). Higher
# priority than generic uncertain_extraction so the UI surfaces it first.
REVIEW_REASONS = (
    "garbled_extracted_value",
    "column_alignment_mismatch",
    "conflicting_extraction",
    "uncertain_extraction",
    "uncertain_semantic_role",
    "uncertain_concept",
    "ambiguous_column",
    "uncertain_title",
)
_REASON_PRIORITY = {reason: i for i, reason in enumerate(REVIEW_REASONS)}

# Private-use-area glyphs (icon fonts with no real Unicode mapping -- e.g. the
# trend-arrow symbols seen in this PDF's SDG tables) and common mojibake
# sequences from a text/encoding mismatch. Matches the kind of corruption
# described in the "garbled_extracted_value" case, not just any odd character.
_GARBLED_RE = re.compile("[\ue000-\uf8ff\ufffd]|[\u00c0-\u00ff][\u0080-\u00bf]")

# ADDED: tokens that belong in Direction/Trend columns, used to detect when
# those values landed in the wrong column after LLM reconstruction.
_DIRECTION_TOKENS = frozenset({"up", "down", "↑", "↓"})
_NUMERIC_DATA_TYPES = frozenset({
    "integer", "int", "decimal", "float", "double", "number", "numeric",
    "percentage", "percent", "pct",
})
_EMPTY_TOKENS = frozenset({"", "null", "none", "na", "n/a", "-", "–", "—", "."})
