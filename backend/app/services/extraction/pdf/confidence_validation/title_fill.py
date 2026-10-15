"""AI title fill when extraction left a table without a usable caption.

Used for both PDF and Excel/CSV tables after confidence validation so Preview
never shows gibberish titles, and missing titles get a crisp AI suggestion
flagged for steward review (``title_filled_by_ai``).
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import openai

from app.services.extraction.pdf.confidence_validation.title_infer import (
    title_looks_like_gibberish,
    title_needs_review,
    _normalize_title_line,
    strip_caption_label_prefix,
)
from app.services.metadata.validation import OPENAI_VALIDATION_MODEL, normalize_table_title

_MAX_TITLE_WORDS = 14
_MIN_TITLE_WORDS = 3


def _column_names(table: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for c in table.get("columns") or []:
        if isinstance(c, dict):
            name = c.get("name")
        else:
            name = c
        s = str(name or "").strip()
        if s:
            names.append(s)
    return names


def _sample_row_lines(table: Dict[str, Any], *, max_rows: int = 4) -> List[str]:
    cols = _column_names(table)
    lines: List[str] = []
    for row in (table.get("rows") or [])[:max_rows]:
        if not isinstance(row, (list, tuple)):
            continue
        parts: List[str] = []
        for i, cell in enumerate(row[: max(len(cols), 8)]):
            if cell is None:
                continue
            sv = str(cell).strip()
            if not sv:
                continue
            label = cols[i] if i < len(cols) else f"c{i+1}"
            parts.append(f"{label}={sv}")
        if parts:
            lines.append("; ".join(parts[:6]))
    return lines


def _context_hint(table: Dict[str, Any]) -> str:
    bits: List[str] = []
    sheet = str(table.get("sheet") or "").strip()
    if sheet:
        bits.append(f"Sheet: {sheet}")
    src = str(table.get("source_file") or table.get("source_filename") or "").strip()
    if src:
        bits.append(f"Source file: {src}")
    banner = str(table.get("banner_table_id") or "").strip()
    if banner:
        bits.append(f"Table id banner: {banner}")
    for row in table.get("title_context_rows") or []:
        s = str(row or "").strip()
        if s:
            bits.append(s)
        if len(bits) >= 6:
            break
    notes = table.get("notes") or []
    for n in notes[:2]:
        s = str(n or "").strip()
        if s:
            bits.append(f"Note: {s}")
    return "\n".join(bits) if bits else "(none)"


def suggest_crisp_table_title_llm(
    table: Dict[str, Any],
    *,
    api_key: Optional[str] = None,
    model: str = OPENAI_VALIDATION_MODEL,
) -> Optional[str]:
    """Ask the model for a short descriptive title grounded in table content."""
    key = (api_key or "").strip()
    if not key:
        return None

    cols = _column_names(table)
    samples = _sample_row_lines(table)
    current = strip_caption_label_prefix(str(table.get("title") or "").strip()) or ""
    col_preview = ", ".join(cols[:12]) or "(unknown)"
    sample_block = "\n".join(f"- {ln}" for ln in samples) or "(no sample rows)"
    context = _context_hint(table)

    prompt = f"""Propose ONE crisp table title for this statistics / data table.

Rules:
- 3 to {_MAX_TITLE_WORDS} words, Title Case or ALL CAPS if the data is vital-statistics style.
- Summarize what the table measures (topic + key breakdown if clear).
- Do NOT include TABLE/Statement ids (e.g. "TABLE: D-14", "D-12").
- Do NOT list column headers or join them with commas / " — ".
- Do NOT invent geography or years that are not supported by headers/rows/context.
- Prefer a clear noun phrase (e.g. "Infant Deaths by Age and Sex (Urban)").
- Respond with ONLY JSON: {{"title": "..."}}

Current title (may be empty or wrong): {current!r}
Column headers: {col_preview}
Sample rows:
{sample_block}
Context:
{context}
"""

    try:
        client = openai.OpenAI(api_key=key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=120,
        )
        text = response.choices[0].message.content or ""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else {}
        raw = str(parsed.get("title") or "").strip()
        cleaned = normalize_table_title(raw, cols) or _normalize_title_line(raw)
        cleaned = strip_caption_label_prefix(cleaned) or ""
        cleaned = _normalize_title_line(cleaned)
        if not cleaned:
            return None
        words = cleaned.split()
        if len(words) < _MIN_TITLE_WORDS or len(words) > _MAX_TITLE_WORDS + 4:
            # Soft clamp: allow slightly long captions, reject tiny stubs.
            if len(words) < _MIN_TITLE_WORDS:
                return None
            cleaned = " ".join(words[:_MAX_TITLE_WORDS])
        from app.services.extraction.pdf.confidence_validation.title_infer import (
            _is_caption_id_only,
            _is_column_group_banner,
        )
        if (
            title_looks_like_gibberish(cleaned)
            or _is_caption_id_only(cleaned)
            or _is_column_group_banner(cleaned)
        ):
            return None
        # Reject titles that are just a column header echo.
        col_low = {c.lower() for c in cols}
        if cleaned.lower() in col_low:
            return None
        return cleaned
    except Exception as exc:
        print(f"[title_fill] LLM title suggestion skipped ({exc})", flush=True)
        return None


def _clear_unusable_title(table: Dict[str, Any]) -> None:
    """Drop gibberish / unusable titles so Preview does not show junk."""
    title = table.get("title")
    cols = table.get("columns") or []
    if not title_needs_review(title, cols) and not title_looks_like_gibberish(title):
        return
    # Keep banner id separately; blank the descriptive title field.
    table["title"] = None
    if table.get("title_source") and str(table.get("title_source")).startswith("heuristic"):
        table["title_source"] = "cleared_unusable"


def apply_ai_title_fill(
    table: Dict[str, Any],
    *,
    api_key: Optional[str] = None,
) -> bool:
    """Fill a missing/bad title via LLM. Returns True when an AI title was set."""
    cols = table.get("columns") or []
    needs = title_needs_review(table.get("title"), cols) or title_looks_like_gibberish(
        table.get("title")
    )
    if not needs:
        return False

    _clear_unusable_title(table)
    suggested = suggest_crisp_table_title_llm(table, api_key=api_key)
    if not suggested:
        # Still needs a steward title.
        table["human_review_needed"] = True
        if not table.get("human_review_reason") or table.get("human_review_reason") in (
            "no_llm_key_heuristic",
            "llm_validation_failed_heuristic",
        ):
            table["human_review_reason"] = "uncertain_title"
        return False

    table["title"] = suggested
    table["title_source"] = "llm_from_content"
    table["title_filled_by_ai"] = True
    # Always needs steward confirmation; keep a higher-priority extraction
    # reason on the rollup when present, else surface title_filled_by_ai.
    try:
        from app.services.extraction.pdf.confidence_validation.normalize import (
            derive_human_review_needed,
        )
        _needed, reason = derive_human_review_needed(table)
        table["human_review_needed"] = True
        table["human_review_reason"] = reason or "title_filled_by_ai"
    except Exception:
        table["human_review_needed"] = True
        table["human_review_reason"] = "title_filled_by_ai"
    return True


def ensure_usable_titles_on_pages(
    validated_by_page: Dict[Any, Dict[str, Any]],
    *,
    api_key: Optional[str] = None,
    max_workers: int = 6,
) -> Dict[Any, Dict[str, Any]]:
    """Post-pass over validated pages: clear gibberish; AI-fill when possible."""
    key = (api_key or "").strip() or None
    jobs: List[Dict[str, Any]] = []
    for page in (validated_by_page or {}).values():
        for table in page.get("tables") or []:
            cols = table.get("columns") or []
            if title_needs_review(table.get("title"), cols) or title_looks_like_gibberish(
                table.get("title")
            ):
                jobs.append(table)

    if not jobs:
        return validated_by_page

    if not key:
        for table in jobs:
            _clear_unusable_title(table)
            table["human_review_needed"] = True
            if not table.get("human_review_reason") or table.get("human_review_reason") in (
                "no_llm_key_heuristic",
                "llm_validation_failed_heuristic",
            ):
                table["human_review_reason"] = "uncertain_title"
        return validated_by_page

    workers = min(max_workers, max(1, len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(apply_ai_title_fill, t, api_key=key) for t in jobs]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                print(f"[title_fill] worker failed ({exc})", flush=True)
    return validated_by_page
