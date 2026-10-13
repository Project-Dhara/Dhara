"""
Metadata generation from Excel facts and KYDS responses.

Thin re-export facade — implementation lives in excel_facts, nmds_llm,
sdg_llm, and definitions_llm.
"""

from __future__ import annotations

from app.services.metadata.excel_facts import (
    ROW_DIM_HINTS,
    ROW_LABEL_HEADERS,
    SERIAL_NAME_HINTS,
    _detect_header_rows,
    _flatten_headers,
    _heuristic_structure,
    _looks_like_data_row,
    extract_excel_facts,
    extract_facts_from_tables,
    heuristic_structure,
    looks_like_data_row,
    prepare_kyds_for_llm,
)
from app.services.metadata.nmds_llm import (
    METADATA_FIELDS,
    generate_metadata_with_llm,
    parse_llm_metadata_output,
)
from app.services.metadata.sdg_llm import (
    SDG_FIELD_CODES,
    SDG_METADATA_FIELDS,
    generate_sdg_metadata_with_llm,
    parse_llm_sdg_metadata_output,
)
from app.services.metadata.definitions_llm import fill_classification_definitions

__all__ = [
    "METADATA_FIELDS",
    "ROW_DIM_HINTS",
    "ROW_LABEL_HEADERS",
    "SDG_FIELD_CODES",
    "SDG_METADATA_FIELDS",
    "SERIAL_NAME_HINTS",
    "_detect_header_rows",
    "_flatten_headers",
    "_heuristic_structure",
    "_looks_like_data_row",
    "extract_excel_facts",
    "extract_facts_from_tables",
    "fill_classification_definitions",
    "generate_metadata_with_llm",
    "generate_sdg_metadata_with_llm",
    "heuristic_structure",
    "looks_like_data_row",
    "parse_llm_metadata_output",
    "parse_llm_sdg_metadata_output",
    "prepare_kyds_for_llm",
]
