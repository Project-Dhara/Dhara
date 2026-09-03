"""
Metadata generation from two sources: programmatically-derived Excel facts
and human-provided KYDS (Know Your Dataset) form responses.

extract_excel_facts()      -- regex/structure based, no LLM involved.
generate_metadata_with_llm() -- sends both sources to an LLM, via a
    caller-supplied completion function so it runs on whichever
    provider/key the user configured in Settings (see main.py's
    `_extractor_for` / `TableExtractor._complete`), not a hardcoded
    OpenAI env-var key.
"""

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import openpyxl

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_YEAR_RANGE_RE = re.compile(r"\b(19|20)\d{2}\s*[-/–]\s*(?:(19|20)\d{2}|\d{2})\b")
_TABLE_CODE_RE = re.compile(r"\b([A-Za-z]{1,3}-\d+(?:\.\d+)?)\b")
_UNIT_PAREN_RE = re.compile(
    r"\(([^)]*(?:RS\.?|₹|%|PERCENT|LAKH|CRORE|SQ\.?\s?KM|PER\s+\d+|COUNT|NUMBER|KG|MT|KM)[^)]*)\)",
    re.IGNORECASE,
)
_GEO_KEYWORDS = [
    "URBAN", "RURAL", "DISTRICT", "STATE", "NATIONAL", "ZONE", "REGION",
    "BLOCK", "WARD", "VILLAGE", "TALUKA", "MANDAL", "CIRCLE", "DIVISION",
    "COUNTRY", "CITY", "TOWN", "PANCHAYAT", "COUNTY", "DEPARTMENT",
]

ROW_DIM_HINTS = ("age", "religion", "category", "cause", "place", "area", "district", "state", "sex", "gender")
ROW_LABEL_HEADERS = {"SL. NO.", "SL NO", "SL.NO.", "S.NO.", "SR.NO.", "AGE", "S.NO"}
SERIAL_NAME_HINTS = ("sl no", "sl.no", "s.no", "serial", "sr no", "sr.no", "index", "#")


# ---------------------------------------------------------------------------
# Grid / block detection (ported from backend/extractor.py, refined further)
# ---------------------------------------------------------------------------

def _blank(row: List[Any]) -> bool:
    return all(v is None or str(v).strip() == "" for v in row)


def _has_table_marker(row: List[Any]) -> bool:
    text = " ".join(str(v) for v in row if v is not None)
    return bool(re.search(r"\bTABLE[\s:\-]", text, re.IGNORECASE))


def _filled_grid(ws) -> List[List[Any]]:
    """Merge-resolved, trimmed grid of the sheet (top-left value repeated across a merged range)."""
    merge_lookup: Dict[Tuple[int, int], Any] = {}
    for mrng in ws.merged_cells.ranges:
        master = ws.cell(mrng.min_row, mrng.min_col).value
        for r in range(mrng.min_row, mrng.max_row + 1):
            for c in range(mrng.min_col, mrng.max_col + 1):
                if r != mrng.min_row or c != mrng.min_col:
                    merge_lookup[(r, c)] = master

    max_row = max_col = 0
    for row in ws.iter_rows():
        for cell in row:
            v = merge_lookup.get((cell.row, cell.column), cell.value)
            if v is not None and str(v).strip():
                max_row = max(max_row, cell.row)
                max_col = max(max_col, cell.column)

    if not max_row:
        return []

    return [
        [merge_lookup.get((r, c), ws.cell(r, c).value) for c in range(1, max_col + 1)]
        for r in range(1, max_row + 1)
    ]


def _find_blocks(grid: List[List[Any]]) -> List[Tuple[int, int]]:
    """Split a sheet's grid into (start, end) row-index blocks, on TABLE markers or blank-row runs."""
    markers = [i for i, r in enumerate(grid) if _has_table_marker(r)]
    if markers:
        blocks = []
        for j, start in enumerate(markers):
            limit = markers[j + 1] if j + 1 < len(markers) else len(grid)
            end = limit - 1
            while end > start and _blank(grid[end]):
                end -= 1
            if end > start:
                blocks.append((start, end))
        return blocks

    blocks, current, blanks = [], None, 0
    for i, row in enumerate(grid):
        if _blank(row):
            blanks += 1
            if blanks >= 2 and current is not None:
                end = i - blanks
                if end > current:
                    blocks.append((current, end))
                current, blanks = None, 0
        else:
            blanks = 0
            if current is None:
                current = i
    if current is not None:
        end = len(grid) - 1
        while end > current and _blank(grid[end]):
            end -= 1
        if end > current:
            blocks.append((current, end))
    return blocks


def _row_text(row: List[Any]) -> str:
    seen, parts = set(), []
    for v in row:
        if v is None:
            continue
        sv = str(v).strip()
        if sv and sv not in seen:
            seen.add(sv)
            parts.append(sv)
    return " ".join(parts)


def _strip_title_desc(block: List[List[Any]]) -> Tuple[str, str, int]:
    """Peel a leading title row (and optional description row) off a block."""
    non_blank = [(i, r) for i, r in enumerate(block) if not _blank(r)]
    title = description = ""
    body_start = 0
    if not non_blank:
        return title, description, body_start

    i0, r0 = non_blank[0]
    title = _row_text(r0)
    body_start = i0 + 1

    if len(non_blank) > 1:
        i1, r1 = non_blank[1]
        text1 = _row_text(r1)
        non_none = [v for v in r1 if v is not None]
        n_nums = sum(1 for v in non_none if isinstance(v, (int, float)))
        if text1 and len(text1) > 10 and n_nums < len(non_none) / 2:
            description = text1
            body_start = i1 + 1

    while body_start < len(block) and _blank(block[body_start]):
        body_start += 1
    return title, description, body_start


def _is_numeric_cell(v: Any) -> bool:
    if isinstance(v, (int, float)):
        return True
    if v is None:
        return False
    s = str(v).strip().replace(",", "")
    if not s or s in {"-", "—"}:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _cell_str(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _pad_row(row: List[Any], n_cols: int) -> List[Any]:
    return list(row) + [None] * (n_cols - len(row))


def _forward_fill_row(row: List[Any]) -> List[str]:
    out, last = [], None
    for v in row:
        s = _cell_str(v)
        if s:
            last = s
            out.append(s)
        elif last:
            out.append(last)
        else:
            out.append("")
    return out


def _row_is_header(row: List[Any]) -> bool:
    non_empty = [v for v in row if _cell_str(v)]
    if not non_empty:
        return False
    nums = sum(1 for v in non_empty if _is_numeric_cell(v))
    return nums <= len(non_empty) * 0.35


def _detect_header_rows(body: List[List[Any]], n_cols: int) -> Tuple[int, List[int]]:
    """Number of leading header rows in `body`, plus indices of rows to skip (e.g. "(1) (2) (3)" column-number rows)."""
    skip_rows: List[int] = []
    for i, row in enumerate(body[:8]):
        non_empty = [v for v in row if v is not None]
        if not non_empty:
            continue
        col_nums = sum(1 for v in non_empty if re.match(r"^\(\d+\)$", _cell_str(v)))
        if col_nums > len(non_empty) * 0.5:
            skip_rows.append(i)

    header_count = 0
    for i, row in enumerate(body[:6]):
        if i in skip_rows:
            continue
        if _blank(row):
            break
        if _row_is_header(row):
            header_count = i + 1
        else:
            break

    return max(header_count, 1), skip_rows


def _flatten_headers(header_matrix: List[List[Any]], n_cols: int) -> List[str]:
    rows = [_forward_fill_row(_pad_row(r, n_cols)) for r in header_matrix]
    if len(rows) == 1:
        return [_cell_str(v) or f"Col_{i + 1}" for i, v in enumerate(rows[0][:n_cols])]

    top, bottom = rows[0], rows[-1]
    columns: List[str] = []
    for i in range(n_cols):
        t, b = top[i], bottom[i]
        t_up, b_up = t.upper(), b.upper()
        if t_up in ROW_LABEL_HEADERS or b_up in ROW_LABEL_HEADERS:
            col = t or b or f"Col_{i + 1}"
        elif t and b and t_up != b_up:
            col = f"{t} / {b}"
        elif b:
            col = b
        elif t:
            col = t
        else:
            col = f"Col_{i + 1}"
        columns.append(col)
    return columns


def _extract_header_categories(header_matrix: List[List[Any]], n_cols: int) -> List[Dict[str, Any]]:
    """Category values implied by multi-row headers, e.g. URBAN/RURAL/ALL or MALE/FEMALE/OTHER."""
    rows = [_forward_fill_row(_pad_row(r, n_cols)) for r in header_matrix]
    categories: List[Dict[str, Any]] = []

    if not rows:
        return categories

    top_vals = sorted({
        v for v in rows[0]
        if v and v.upper() not in ROW_LABEL_HEADERS and not re.match(r"^\(\d+\)$", v)
    }, key=str.casefold)
    if top_vals:
        categories.append({
            "source": "column_header",
            "dimension": "Column group",
            "column_name": "(from header row 1)",
            "values": top_vals,
        })

    if len(rows) >= 2:
        sub_vals = sorted({
            v for v in rows[-1]
            if v and v.upper() not in ROW_LABEL_HEADERS and not re.match(r"^\(\d+\)$", v)
        }, key=str.casefold)
        if sub_vals and sub_vals != top_vals:
            categories.append({
                "source": "column_header",
                "dimension": "Sub-column",
                "column_name": "(from header row 2)",
                "values": sub_vals,
            })

    return categories


def _heuristic_structure(body: List[List[Any]], n_cols: int) -> Dict[str, Any]:
    if not body:
        return {"header_rows": 0, "skip_rows": [], "columns": [f"Col_{i + 1}" for i in range(n_cols)]}

    header_rows, skip_rows = _detect_header_rows(body, n_cols)
    header_matrix = [body[i] for i in range(header_rows) if i not in skip_rows]
    if not header_matrix:
        header_matrix = [body[0]]

    columns = _flatten_headers(header_matrix, n_cols)
    while len(columns) < n_cols:
        columns.append(f"Col_{len(columns) + 1}")

    return {
        "header_rows": header_rows,
        "skip_rows": skip_rows,
        "columns": columns[:n_cols],
        "header_matrix": header_matrix,
        "header_categories": _extract_header_categories(header_matrix, n_cols),
    }


def _dedupe_columns(columns: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out = []
    for col in columns:
        if col in seen:
            seen[col] += 1
            out.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 0
            out.append(col)
    return out


def _looks_like_serial_column(name: str) -> bool:
    lowered = str(name).lower().strip()
    return any(hint in lowered for hint in SERIAL_NAME_HINTS)


def _is_row_dimension_column(name: str) -> bool:
    lowered = str(name).lower().strip()
    if lowered in {"age", "religion", "category", "sex", "gender"}:
        return True
    return any(hint in lowered for hint in ROW_DIM_HINTS)


def _is_categorical_column(col_name: str, values: List[Any], n_rows: int, max_unique: int = 50, max_ratio: float = 0.5) -> bool:
    """Return True if a column likely holds categorical row labels (e.g. AGE)."""
    non_null = [v for v in values if v is not None and str(v).strip() != ""]
    if not non_null:
        return False
    if _looks_like_serial_column(col_name):
        return False

    if _is_row_dimension_column(col_name):
        return any(not _is_numeric_cell(v) for v in non_null)

    n = len(non_null)
    unique_vals = set(str(v).strip() for v in non_null)
    nunique = len(unique_vals)
    if nunique <= 1 or nunique == n:
        return False

    ratio = nunique / n
    numeric_count = sum(1 for v in non_null if _is_numeric_cell(v))
    if numeric_count > n * 0.6:
        return False

    if nunique <= max_unique and ratio <= max_ratio:
        return True
    return nunique <= 15


def _categorical_values(values: List[Any]) -> List[str]:
    seen = set()
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s and not _is_numeric_cell(s):
            seen.add(s)
    return sorted(seen, key=str.casefold)


def _extract_row_dimension_categories(columns: List[str], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Categorical dimensions found in row-label columns (e.g. an AGE column)."""
    categories = []
    for col in columns:
        col_values = [r.get(col) for r in rows]
        if not _is_categorical_column(col, col_values, len(rows)):
            continue
        values = _categorical_values(col_values)
        if not values:
            continue
        categories.append({
            "source": "row_column",
            "dimension": "Row dimension",
            "column_name": col,
            "values": values,
        })
    return categories


# ---------------------------------------------------------------------------
# Regex-based content facts (existing capabilities)
# ---------------------------------------------------------------------------

def _extract_geography(text: str) -> List[str]:
    upper = text.upper()
    return sorted({kw for kw in _GEO_KEYWORDS if re.search(rf"\b{kw}\b", upper)})


def _extract_units(text: str) -> List[str]:
    return sorted({m.group(1).strip() for m in _UNIT_PAREN_RE.finditer(text)})


def _extract_periods(text: str) -> Dict[str, List[str]]:
    return {
        "years": sorted(set(m.group(0) for m in _YEAR_RE.finditer(text))),
        "year_ranges": sorted(set(m.group(0) for m in _YEAR_RANGE_RE.finditer(text))),
    }


def _extract_table_codes(text: str) -> List[str]:
    return sorted(set(m.group(1).upper() for m in _TABLE_CODE_RE.finditer(text)))


# ---------------------------------------------------------------------------
# Table extraction combining block detection + heuristic structure
# ---------------------------------------------------------------------------

def _extract_table_from_block(grid: List[List[Any]], start: int, end: int, sheet_name: str, idx: int) -> Optional[Dict[str, Any]]:
    block = grid[start:end + 1]
    title, description, body_start = _strip_title_desc(block)
    body = block[body_start:]
    if not body:
        return None

    n_cols = max(len(r) for r in body)
    structure = _heuristic_structure(body, n_cols)
    header_rows = structure["header_rows"]
    skip_set = set(structure["skip_rows"])
    columns = _dedupe_columns(structure["columns"])
    header_categories = structure.get("header_categories", [])
    raw_header_rows = structure.get("header_matrix", [])

    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(body[header_rows:], start=header_rows):
        if i in skip_set or _blank(row):
            continue
        padded = _pad_row(row, n_cols)
        row_dict = {}
        for j, col in enumerate(columns):
            v = padded[j]
            if hasattr(v, "item"):
                v = v.item()
            row_dict[col] = v
        rows.append(row_dict)

    if not rows:
        return None

    block_text = "\n".join(_row_text(r) for r in block)
    display_title = title or f"Table {idx + 1}"

    row_dim_categories = _extract_row_dimension_categories(columns, rows)
    categorical_dimensions = row_dim_categories + header_categories

    return {
        "sheet_name": sheet_name,
        "title_context": display_title,
        "description": description,
        "table_name": f"{sheet_name} / {display_title}",
        "table_boundaries": {
            "start_row": start,
            "end_row": end,
            "n_rows": end - start + 1,
            "n_cols": n_cols,
        },
        "table_identifiers": _extract_table_codes(block_text),
        "raw_header_rows": raw_header_rows,
        "column_names": columns,
        "multi_row_header": header_rows > 1,
        "n_header_rows": header_rows,
        "sample_rows": rows[:5],
        "row_count": len(rows),
        "periods": _extract_periods(block_text),
        "geography": _extract_geography(block_text),
        "units": _extract_units(block_text),
        "categorical_dimensions": categorical_dimensions,
        "block_index": idx,
    }


def extract_excel_facts(file_content: bytes, filename: str) -> Dict[str, Any]:
    """
    Programmatically derive structural/content facts from an uploaded Excel workbook,
    using regex and grid layout — no LLM involved.

    Returns one entry per detected table block per sheet, with sheet name, table
    boundaries, headers, column names, sample rows, values, identifiers, periods,
    geography, units, title/context, multi-row-header structure, and categorical
    dimensions (row-label columns and header-derived groupings such as URBAN/RURAL
    or MALE/FEMALE).
    """
    import io

    wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)

    facts: Dict[str, Any] = {"filename": filename, "sheets": []}

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        grid = _filled_grid(ws)
        if not grid:
            continue

        blocks = _find_blocks(grid)
        if not blocks:
            blocks = [(0, len(grid) - 1)]

        sheet_facts = {"sheet_name": sheet_name, "tables": []}
        for idx, (start, end) in enumerate(blocks):
            tbl = _extract_table_from_block(grid, start, end, sheet_name, idx)
            if tbl:
                sheet_facts["tables"].append(tbl)

        facts["sheets"].append(sheet_facts)

    return facts


def prepare_kyds_for_llm(kyds: Dict[str, Any]) -> Dict[str, Any]:
    """Trim the KYDS responses down to the fields relevant for metadata generation, to save tokens.

    The full KYDS object is still stored as-is in Postgres — this trimmed view is only for the LLM call.
    """
    # KYDS responses are stored with the form's own camelCase keys (see
    # emptyForm() in frontend/src/components/KydsModal.jsx) -- not the
    # snake_case names used here previously, which meant every field but
    # `modality`/`granularity`/`notes` silently read back None.
    return {
        "dataset_name": kyds.get("datasetName"),
        "description": kyds.get("description"),
        "department": kyds.get("department"),
        "modality": kyds.get("modality"),
        "specific_formats": kyds.get("specificFormats"),
        "granularity": kyds.get("granularity"),
        "update_frequency": kyds.get("updateFrequency"),
        "retention": kyds.get("retention"),
        "notes": kyds.get("notes"),
    }


def generate_metadata_with_llm(
    excel_facts: Dict[str, Any],
    *,
    kyds: Dict[str, Any],
    complete_fn: Callable[[str, int], str],
) -> str:
    """
    Populate catalogue metadata fields using both the programmatically-derived
    Excel facts and the human-provided KYDS form responses (kyds_responses).

    `complete_fn(prompt, max_tokens)` performs the actual LLM call -- pass
    `TableExtractor(api_key=..., provider=...)._complete`, built from the
    caller's own Settings key, so this routes through whichever provider the
    user configured instead of a fixed OpenAI env-var key.

    Only a trimmed subset of KYDS relevant to metadata generation is sent to the
    LLM (see prepare_kyds_for_llm), to save tokens. The full KYDS object should
    still be persisted as-is elsewhere (e.g. Postgres).
    """
    system_prompt = """You are a metadata-generation assistant for a data catalogue.

Generate the following metadata fields using the provided `excel_facts` and `dataset_context` (KYDS):

`title`, `product`, `category`, `geography`, `frequency`, `time_period`, `data_source`, `description`, `last_updated`, `future_release`, `key_statistics`, `remarks`.

Rules:

* Use Excel facts as the primary source for information about the actual data.
* Use KYDS context to understand the dataset's purpose, collection method, granularity, frequency, format, and notes.
* Do not invent or guess information. If a value cannot be determined, return `null`.
* Prefer explicit Excel evidence over inference.
* Do not contradict explicit KYDS information.
* Generate concise, catalogue-ready values.
* `key_statistics` should contain only statistics that can be directly calculated or clearly identified from the provided Excel facts.
* `last_updated` and `future_release` must be `null` unless explicitly supported by the inputs.
* `product` should identify the dataset/product represented by the workbook, not the file format.
* `remarks` should contain relevant caveats, limitations, or contextual notes supported by the inputs.

Return ONLY valid JSON format output for the fields mentioned above.
"""  # TODO: prompt to be added

    kyds_llm = prepare_kyds_for_llm(kyds)
    user_content = {"excel_facts": excel_facts, "dataset_context": kyds_llm}

    prompt = f"{system_prompt}\n\n{json.dumps(user_content, default=str)}"
    return complete_fn(prompt, 1500)


METADATA_FIELDS = [
    "title", "product", "category", "geography", "frequency", "time_period",
    "data_source", "description", "last_updated", "future_release",
    "key_statistics", "remarks",
]


def parse_llm_metadata_output(llm_output: str) -> Dict[str, Any]:
    """
    Parse the JSON metadata object returned by generate_metadata_with_llm and
    normalize it to exactly METADATA_FIELDS (missing fields become None).
    """
    text = re.sub(r"```[a-zA-Z]*\n?", "", llm_output).strip().rstrip("`")
    parsed = json.loads(text)
    return {field: parsed.get(field) for field in METADATA_FIELDS}


def fill_classification_definitions(
    complete_fn: Callable[[str, int], str],
    column_name: str,
    values: List[str],
    facts: Dict[str, Any],
) -> Dict[str, str]:
    """One-sentence definitions for classification values, grounded in catalogue/excel facts."""
    if not values:
        return {}
    prompt = f"""You write brief catalogue labels for classification code-list values.

Dataset facts from the source workbook / catalogue record:
{json.dumps(facts or {{}}, default=str)[:4500]}

Column name: {column_name}
Values: {json.dumps(values)}

Return ONLY a JSON object mapping each value (exact string) to a short definition.
Keep each definition under 8 words. No full sentences unless needed. No statistics.
If the facts do not explain a label, restate the label in plain language.
Do not include occupation/NCO codes."""
    text = complete_fn(prompt, min(800, 160 + 40 * len(values)))
    text = re.sub(r"```[a-zA-Z]*\n?", "", text).strip().rstrip("`")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        return {}
    out = {}
    for v in values:
        d = parsed.get(v)
        if d is None:
            # case-insensitive key match
            d = next((parsed[k] for k in parsed if str(k).strip().lower() == str(v).strip().lower()), None)
        if d:
            words = str(d).strip().rstrip(".").split()
            out[str(v)] = " ".join(words[:8])
    return out

