"""Source Table ID / Table Title validation and repair helpers.

Mirrors the notebook's Stage 2.5: runs the code-based and prompt-based
validators on each extracted table and annotates it with the results plus
an `id_title_mismatch` flag the frontend uses to decide which tables need
manual reconciliation.
"""
import concurrent.futures
from typing import Optional

from metadata.validation import (
    validate_table_fields_code,
    validate_table_fields_llm,
    repair_table_id_title_llm,
    normalize_table_title,
    _title_looks_like_headers,
)


def _title_looks_like_column_headers(title: str, columns: list) -> bool:
    """True when an extracted 'title' is really the header row joined together."""
    text = " ".join(str(title or "").split()).strip().upper()
    cols = [" ".join(str(c).split()).strip().upper() for c in (columns or []) if c is not None and str(c).strip()]
    if not text or len(cols) < 2:
        return False
    joined = " ".join(cols)
    if text == joined:
        return True
    # Header-like if most leading column names appear as tokens in the title.
    hits = sum(1 for c in cols[: min(6, len(cols))] if c and c in text)
    return hits >= min(3, len(cols))


def _catalogue_table_title(table: dict, inventory_item: Optional[dict] = None) -> str:
    """Prefer a real descriptive title over mis-extracted column-header text."""
    inv_title = str((inventory_item or {}).get("short_description") or "").strip()
    title = str(table.get("title") or "").strip()
    table_id = str(table.get("table_id") or "").strip()
    columns = table.get("columns") or []

    if title and not _title_looks_like_column_headers(title, columns):
        return title
    if inv_title:
        return inv_title
    if table_id and not _title_looks_like_column_headers(table_id, columns):
        return table_id
    return title or inv_title or table_id or str(table.get("id") or "")


def _title_context_rows_for(table: dict) -> list:
    context = list(table.get("title_context_rows") or [])
    if context:
        return context
    for row in (table.get("raw_header_rows") or [])[:4]:
        if isinstance(row, (list, tuple)):
            text = " ".join(str(c).strip() for c in row if c is not None and str(c).strip())
        else:
            text = str(row or "").strip()
        if text:
            context.append(text)
    return context


def _apply_llm_id_title_repair(table: dict, table_id: str, title: str) -> tuple:
    """Apply LLM repair patches; returns (table_id, title, code_result)."""
    repaired = repair_table_id_title_llm(
        table_id,
        title,
        context_rows=_title_context_rows_for(table),
        columns=table.get("columns") or [],
    )
    if not repaired:
        return table_id, title, validate_table_fields_code(table_id, title)

    if repaired.get("table_id") and repaired["table_id"] != (table_id or "").strip():
        table["table_id"] = repaired["table_id"]
        table_id = table["table_id"]
        table["table_id_repaired_by_llm"] = True
    if repaired.get("title") and repaired["title"] != (title or "").strip():
        table["title"] = repaired["title"]
        title = table["title"]
        table["title_repaired_by_llm"] = True
    return table_id, title, validate_table_fields_code(table_id, title)


def _validate_table_id_title(table: dict) -> None:
    """Runs the code-based and prompt-based Source Table ID / Table Title validators
    on one extracted table (mirrors the notebook's Stage 2.5) and annotates
    the table in place with the results plus a `id_title_mismatch` flag the
    frontend uses to decide which tables need manual reconciliation.

    When the LLM auto-fills or corrects either field, sets
    ``table_id_repaired_by_llm`` / ``title_repaired_by_llm`` so Preview can
    highlight them for human review.
    """
    table_id = table.get("table_id", "")
    title = table.get("title", "")
    columns = table.get("columns") or []

    # Deterministic cleanup: drop column-list / overlong " — " suffixes before
    # deciding whether LLM repair is needed.
    cleaned = normalize_table_title(title, columns)
    if cleaned and cleaned != (title or "").strip():
        table["title"] = cleaned
        title = cleaned

    code_result = validate_table_fields_code(table_id, title)
    needs_repair = (
        (not (title or "").strip())
        or (not (table_id or "").strip())
        or _title_looks_like_headers(title, columns)
        or any("swap" in str(i).lower() for i in (code_result.get("issues") or []))
        or any("title" in str(i).lower() and "missing" in str(i).lower() for i in (code_result.get("issues") or []))
        or any("table id" in str(i).lower() and "missing" in str(i).lower() for i in (code_result.get("issues") or []))
    )

    if needs_repair:
        table_id, title, code_result = _apply_llm_id_title_repair(table, table_id, title)

    if not str(table_id or "").strip() and not str(title or "").strip():
        # Nothing to send the model -- both fields are already conclusively
        # invalid, so skip the LLM call rather than prompting it with two
        # empty strings.
        llm_result = {"valid": False, "issues": ["Source Table ID and Table Title are both missing"]}
    else:
        try:
            llm_result = validate_table_fields_llm(table_id, title)
        except Exception as e:
            llm_result = {"valid": None, "issues": [f"LLM validation skipped ({e})"]}

    # If validation still says id/title is wrong, ask the model for a fix once.
    llm_field_issue = any(
        any(k in str(i).lower() for k in ("title", "table id", "swap", "header", "sl.no", "description", "missing"))
        for i in (llm_result.get("issues") or [])
    )
    already_repaired = table.get("title_repaired_by_llm") or table.get("table_id_repaired_by_llm")
    if (
        not already_repaired
        and llm_result.get("valid") is False
        and llm_field_issue
    ):
        table_id, title, code_result = _apply_llm_id_title_repair(table, table_id, title)
        try:
            llm_result = validate_table_fields_llm(table_id, title)
        except Exception as e:
            llm_result = {"valid": None, "issues": [f"LLM validation skipped ({e})"]}

    # The regex/heuristic validator is deterministic and ground-truth for the
    # cases it checks (missing field, no "TABLE" marker, obvious swap), so it
    # is the source of truth for whether a table needs reconciliation. The
    # LLM validator can misfire on well-formed pairs (see validation.py); we
    # only let it force a mismatch when it flags a problem the code validator
    # doesn't already catch -- i.e. the code validator says valid, but the
    # LLM found an actual issue.
    mismatch = (not code_result["valid"]) or (
        code_result["valid"] and llm_result["valid"] is False and llm_result["issues"]
    )

    table["id_validation"] = {"code": code_result, "llm": llm_result}
    table["id_title_mismatch"] = mismatch


def _validate_tables(tables: list) -> None:
    """Runs `_validate_table_id_title` across all tables concurrently (each
    call makes a blocking LLM request) and annotates them in place."""
    if not tables:
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(_validate_table_id_title, tables))
