"""Classification code lists: read/rebuild/normalize/persist for the Classify step."""
import json
import re

# Serial / row-index columns are identifiers, not codebook dimensions.
_SERIAL_NAME_HINTS = (
    "sl no", "sl.no", "sl_no", "s.no", "s_no", "serial", "sr no", "sr.no",
    "sr_no", "row no", "row_no", "row#", "#",
)
# TOC / index / free-text columns that should never become Classify chips.
_NON_CLASSIFICATION_NAME_HINTS = (
    "contents", "content", "page no", "page_no", "page no.", "pageno",
    "page number", "chapter", "particulars", "remarks", "remark", "notes",
    "note", "description", "list of tables", "table of contents",
)
# Row / record identifiers — never classification dimensions.
_IDENTIFIER_COMPACT_NAMES = frozenset({
    "recordid", "rowid", "uuid", "guid", "pk", "id",
})
_IDENTIFIER_NAME_RE = re.compile(
    r"\b(?:record\s*id|row\s*id|uuid|guid)\b|(?:^|_)(?:record_?id|row_?id)(?:_|$)",
    re.I,
)
# Whole-title match for Contents / Index pages — avoid "Price Index" false hits.
_TOC_TITLE_RE = re.compile(
    r"^\s*(?:table\s+of\s+contents|list\s+of\s+tables|contents|index(?:\s+of\s+tables)?)\s*$"
    r"|\b(?:table\s+of\s+contents|list\s+of\s+tables)\b",
    re.I,
)
_PAGE_VALUE_RE = re.compile(
    r"^(?:p\.?\s*)?(?:\d{1,4}|[ivxlcdm]{1,8})(?:\s*[-–—]\s*(?:\d{1,4}|[ivxlcdm]{1,8}))?$",
    re.I,
)
_NEAR_DUP_JACCARD = 0.85
_NEAR_DUP_CONTAINMENT = 0.9
# Deterministic categorical keep thresholds (fixed; not UI-tunable).
_UNIQUENESS_REJECT = 0.85
# High enough for large occupation/job title lists in employee extracts.
_LABEL_LIKE_MAX = 5000
_CATEGORICAL_LABEL_SHARE = 0.8
_STORED_ID_TOKEN_MIN = 8
_ID_TOKEN_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
_OCCUPATION_ID_TOKENS = frozenset({"id", "code", "number", "no", "num", "key"})
# PDF/Excel placeholder headers (failed header detect) and bare numeric leaf names.
_PLACEHOLDER_COL_RE = re.compile(
    r"^(?:col|column)[_\s-]?\d+$|^unnamed(?:[:\s._-]*\d+)?$",
    re.I,
)
_NUMERIC_COL_RE = re.compile(
    r"^\d+(?:[.,]\d+)?$"  # 15, 1, 2023, 15.0
    r"|^\d{4}\s*[-–/]\s*\d{2,4}$"  # 2023-24 measure year headers
    r"|^\(\d+\)$"  # (1)(2) column-index strip labels
)
_NUMERIC_CELL_RE = re.compile(r"^[-+]?\d+(?:[.,]\d+)?$")


def _normalize_col_key(name: str) -> str:
    return re.sub(r"[\s_\-./]+", "", str(name or "").lower())


def _value_sets_near_duplicate(a: set, b: set) -> bool:
    if not a or not b:
        return False
    if _jaccard(a, b) >= _NEAR_DUP_JACCARD:
        return True
    # One list is almost a subset of the other (common when tables add a few labels).
    inter = len(a & b)
    return inter / min(len(a), len(b)) >= _NEAR_DUP_CONTAINMENT


def _looks_like_serial_column_name(name: str) -> bool:
    lowered = re.sub(r"[\s_\-./]+", " ", str(name or "").lower()).strip()
    compact = _normalize_col_key(name)
    if compact in {"slno", "sno", "srno", "serialno", "serialnumber", "rowno", "index"}:
        return True
    return any(hint in lowered for hint in _SERIAL_NAME_HINTS)


def _looks_like_identifier_column_name(name: str) -> bool:
    """True for recordid / uuid / bare id — row keys, not categories."""
    compact = _normalize_col_key(name)
    if compact in _IDENTIFIER_COMPACT_NAMES:
        return True
    if compact.endswith("recordid") or compact.endswith("rowid"):
        return True
    lowered = re.sub(r"[\s_\-./]+", " ", str(name or "").lower()).strip()
    if _IDENTIFIER_NAME_RE.search(lowered):
        return True
    return False


def _looks_like_placeholder_or_numeric_column_name(name: str) -> bool:
    """True for Col_1 / Unnamed / bare numbers — not real classification dims."""
    s = str(name or "").strip()
    if not s:
        return True
    if _PLACEHOLDER_COL_RE.match(s):
        return True
    if _NUMERIC_COL_RE.match(s):
        return True
    return False


def _looks_like_non_classification_column_name(name: str) -> bool:
    if _looks_like_placeholder_or_numeric_column_name(name):
        return True
    if _looks_like_serial_column_name(name):
        return True
    if _looks_like_identifier_column_name(name):
        return True
    lowered = re.sub(r"[\s_\-./]+", " ", str(name or "").lower()).strip()
    compact = _normalize_col_key(name)
    if compact in {"page", "pages", "pageno", "pagenumber", "contents", "content", "chapter"}:
        return True
    if lowered in {"page", "pages", "title"}:
        return True
    return any(hint in lowered for hint in _NON_CLASSIFICATION_NAME_HINTS)


def _is_numeric_cell(value: str) -> bool:
    return bool(_NUMERIC_CELL_RE.fullmatch(str(value or "").strip().replace(",", "")))


def _column_names_from_table(table) -> list:
    raw_columns = (table or {}).get("columns") or []
    columns = []
    for i, col in enumerate(raw_columns):
        if isinstance(col, str):
            columns.append(col)
        elif isinstance(col, dict):
            columns.append(str(col.get("name") or f"column_{i + 1}"))
        else:
            columns.append(f"column_{i + 1}")
    return columns


def _looks_like_index_or_toc_table(table) -> bool:
    """True for Contents / List-of-tables / serial+page index grids."""
    title = " ".join(
        str((table or {}).get(k) or "")
        for k in ("title", "description", "caption", "table_id")
    )
    if _TOC_TITLE_RE.search(title):
        return True

    columns = _column_names_from_table(table)
    if not columns:
        return False
    lowered = [re.sub(r"[\s_\-./]+", " ", c.lower()).strip() for c in columns]
    has_serial = any(_looks_like_serial_column_name(c) for c in columns)
    has_contents = any(
        any(h in c for h in ("content", "particular", "chapter", "title", "subject"))
        for c in lowered
    )
    has_page = any(
        c == "page" or c.startswith("page ") or "page no" in c or c.endswith(" page")
        for c in lowered
    )
    # Classic TOC shape: Sl.No + Contents (+ Page), or Contents + Page.
    if has_serial and (has_contents or has_page) and len(columns) <= 5:
        return True
    if has_contents and has_page and len(columns) <= 4:
        return True
    return False


def _value_set(entries) -> set:
    out = set()
    for e in entries or []:
        if isinstance(e, dict):
            v = str(e.get("value") or e.get("code") or "").strip().lower()
        else:
            v = str(e).strip().lower()
        if v:
            out.add(v)
    return out


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def _values_look_like_free_text(values: list, n_non_empty: int) -> bool:
    """Near-unique long labels (chapter titles, TOC lines) are not code lists."""
    if not values or n_non_empty <= 0:
        return False
    n_unique = len(values)
    # Almost every row is a distinct string → inventory/TOC text, not a dimension.
    if n_unique >= 8 and n_unique / max(n_non_empty, 1) >= 0.85:
        avg_len = sum(len(str(e.get("value") or "")) for e in values) / n_unique
        if avg_len >= 24:
            return True
    # Mostly page-like tokens.
    pageish = sum(
        1 for e in values
        if _PAGE_VALUE_RE.match(str(e.get("value") or "").strip())
    )
    if pageish >= max(2, int(0.8 * n_unique)):
        return True
    return False


def _value_texts(values: list) -> list[str]:
    out = []
    for e in values or []:
        if isinstance(e, dict):
            t = str(e.get("value") or "").strip()
        else:
            t = str(e).strip()
        if t:
            out.append(t)
    return out


_UUID_VALUE_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _value_looks_like_id_token(text: str) -> bool:
    """True for code/id tokens (REC001, uuid) — not plain category words (Delhi)."""
    t = str(text or "").strip()
    if not t or " " in t or len(t) > 64:
        return False
    if not _ID_TOKEN_RE.fullmatch(t):
        return False
    if _UUID_VALUE_RE.fullmatch(t):
        return True
    # Digits in a compact token → identifier/code, not a place/sex label.
    return any(c.isdigit() for c in t)


def _values_look_like_id_tokens(values: list) -> bool:
    """Mostly compact id/code tokens — used for value-based identifier rejection."""
    texts = _value_texts(values)
    if len(texts) < _STORED_ID_TOKEN_MIN:
        return False
    idish = sum(1 for t in texts if _value_looks_like_id_token(t))
    return (idish / len(texts)) >= 0.8


def _is_occupation_name(name):
    """Occupation and job columns are owned by NCO matching."""
    text = name or ""
    if re.search(r"occupat", text, re.I):
        return True
    tokens = re.findall(r"[a-z]+", text.lower())
    if "job" not in tokens and "jobs" not in tokens:
        return False
    return not any(tok in _OCCUPATION_ID_TOKENS for tok in tokens)


def _is_categorical_column(
    name: str,
    values: list,
    n_non_empty: int,
    n_label: int | None = None,
) -> bool:
    """Keep categorical dimensions via value shape; name deny-list is a safety net.

    Value-based confidence (primary):
      - mostly non-numeric labels
      - not long free-text
      - not near-unique id/code tokens (works even if column is renamed)
      - absolute distinct cap so runaway sets are dropped
    Occupation/job columns are always kept when they have a real value list
    (NCO dimensions; titles are often numerous and near-unique in employee files).
    Name deny-list (additional): recordid/uuid/serial/TOC/etc.
    """
    if not values or len(values) < 2:
        return False
    if _looks_like_non_classification_column_name(name):
        return False
    n_non_empty = max(int(n_non_empty or 0), 1)
    if n_label is not None and (n_label / n_non_empty) < _CATEGORICAL_LABEL_SHARE:
        return False

    # Occupation / job titles are classification dimensions even when nearly
    # unique in employee microdata (many distinct role strings).
    if _is_occupation_name(name):
        return True

    if _values_look_like_free_text(values, n_non_empty):
        return False

    n_unique = len(values)
    uniqueness = n_unique / n_non_empty

    # Primary value-based ID filter: near-unique + id/code-shaped values.
    # Plain category words (Delhi, Male) are not id tokens, so codebooks stay.
    if (
        n_non_empty >= _STORED_ID_TOKEN_MIN
        and uniqueness >= _UNIQUENESS_REJECT
        and _values_look_like_id_tokens(values)
    ):
        return False

    # Absolute cap only — avoids dropping real high-cardinality categories.
    return n_unique <= _LABEL_LIKE_MAX


def _should_keep_classification_column(
    name: str,
    values: list,
    n_non_empty: int,
    n_label: int | None = None,
) -> bool:
    return _is_categorical_column(name, values, n_non_empty, n_label=n_label)


def _filter_classification_dict(classifications: dict) -> dict:
    """Drop serial/TOC/page/identifier dimensions from a stored or rebuilt map.

    Stored lists have unique values only (no row counts), so uniqueness bands
    are not applied here — deny-list + page/id-token shape filters only.
    """
    out = {}
    for name, codes in (classifications or {}).items():
        if _looks_like_non_classification_column_name(name):
            continue
        norm = _normalize_classification_values(codes)
        if len(norm) < 2:
            continue
        pageish = sum(
            1 for e in norm
            if _PAGE_VALUE_RE.match(str(e.get("value") or "").strip())
        )
        if pageish >= max(2, int(0.8 * len(norm))):
            continue
        if _values_look_like_id_tokens(norm):
            continue
        out[str(name)] = norm
    return _collapse_near_duplicate_dimensions(out)


def _pick_canonical_dim_name(names: list) -> str:
    return sorted(names, key=lambda n: (len(str(n)), str(n).lower()))[0]


def _collapse_near_duplicate_dimensions(classifications: dict) -> dict:
    """Merge dimensions with nearly identical value sets (redundant chips)."""
    items = [
        (str(name), _normalize_classification_values(codes))
        for name, codes in (classifications or {}).items()
    ]
    items = [(n, c) for n, c in items if c]
    if len(items) <= 1:
        return {n: c for n, c in items}

    used = set()
    merged = {}
    for i, (name_i, codes_i) in enumerate(items):
        if i in used:
            continue
        group_names = [name_i]
        group_codes = list(codes_i)
        set_i = _value_set(codes_i)
        for j in range(i + 1, len(items)):
            if j in used:
                continue
            name_j, codes_j = items[j]
            # Same normalized name, or highly overlapping value sets.
            same_name = _normalize_col_key(name_i) == _normalize_col_key(name_j)
            overlap = _value_sets_near_duplicate(set_i, _value_set(codes_j))
            if not (same_name or overlap):
                continue
            used.add(j)
            group_names.append(name_j)
            existing = {(e.get("value") or "").lower() for e in group_codes}
            for e in codes_j:
                key = (e.get("value") or "").lower()
                if key and key not in existing:
                    group_codes.append(e)
                    existing.add(key)
            set_i = _value_set(group_codes)
        used.add(i)
        canon = _pick_canonical_dim_name(group_names)
        merged[canon] = group_codes
    return merged


def _normalize_code_entry(entry):
    """A classification entry is normally {code, value, definition} (from the
    real metadata-excel parse). But when no metadata-excel sheet covered a
    dimension, the LLM-guessed fallback stores it as a flat list of plain
    value strings instead — normalize those too so the frontend always gets
    a consistent {code, value, definition} shape.

    Value comes from the data; code starts empty unless a real code was stored
    (not an identity copy of the value)."""
    if isinstance(entry, dict):
        value = entry.get("value")
        code = entry.get("code")
        definition = entry.get("definition")
        if definition in (None, "") and entry.get("description") not in (None, ""):
            definition = entry.get("description")
        if value in (None, "") and code not in (None, ""):
            # Legacy shapes sometimes only set code; treat it as the value.
            value = code
            code = ""
        # Identity placeholders only when still unfilled (no definition yet).
        # Code may equal value when the steward typed it; Fill with AI no longer
        # copies value → code (only NCO matching auto-fills codes).
        if (
            code not in (None, "")
            and value not in (None, "")
            and str(code).strip().lower() == str(value).strip().lower()
            and not str(definition or "").strip()
        ):
            code = ""
        return {
            "code": "" if code is None else code,
            "value": value,
            "definition": definition,
        }
    # Plain string = observed value only; steward fills code later.
    return {"code": "", "value": entry, "definition": None}


def get_metadata_group_classifications(conn, metadata_id):
    """Read metadata_groups.classifications for the Classify step, reshaped
    into the [{name, concept, note, codes}] array the frontend expects."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT classifications FROM metadata_groups WHERE metadata_id = %s",
                (metadata_id,),
            )
            row = cur.fetchone()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    if not row:
        return None

    classifications = row[0] or {}
    if isinstance(classifications, str):
        try:
            classifications = json.loads(classifications) or {}
        except Exception:
            classifications = {}
    if not isinstance(classifications, dict):
        classifications = {}

    if not classifications:
        try:
            classifications = _classifications_from_linked_datasets(conn, metadata_id) or {}
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"[catalogue] rebuild classifications failed for {metadata_id}: {exc}")
            classifications = {}

    classifications = _filter_classification_dict(classifications)

    columns = []
    for name, codes in classifications.items():
        norm = _normalize_classification_values(codes)
        if not norm:
            continue
        columns.append({
            "name": name,
            "concept": name,
            "note": "",
            "codes": norm,
        })
    if not columns:
        # Last resort: rebuild from linked dataset rows (SQL / no workbook).
        try:
            rebuilt = _filter_classification_dict(
                _classifications_from_linked_datasets(conn, metadata_id) or {}
            )
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"[catalogue] linked-dataset rebuild failed for {metadata_id}: {exc}")
            rebuilt = {}
        for name, codes in rebuilt.items():
            norm = _normalize_classification_values(codes)
            if norm:
                columns.append({
                    "name": name,
                    "concept": name,
                    "note": "",
                    "codes": norm,
                })
    return columns


def get_definition_facts(conn, metadata_id):
    """Compact catalogue + workbook facts for filling classification definitions."""
    if not metadata_id:
        return {}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT title, description, product, category, geography, frequency,
                   time_period, data_source, key_statistics, full_record
            FROM metadata_groups WHERE metadata_id = %s
        """, (metadata_id,))
        row = cur.fetchone()
    if not row:
        return {}
    rec = row[9] or {}
    inventory = rec.get("dataset_inventory_list") or []
    return {
        "title": row[0],
        "description": row[1],
        "product": row[2],
        "category": row[3],
        "geography": row[4],
        "frequency": row[5],
        "time_period": row[6],
        "data_source": row[7],
        "key_statistics": row[8],
        "tables": [
            {
                "title": t.get("title"),
                "short_description": t.get("short_description"),
            }
            for t in inventory[:10]
            if isinstance(t, dict)
        ],
    }


def get_recent_classification_columns(conn, user_email, limit=12):
    """Fallback when the frontend has no metadataIds in session: the most
    recently pushed groups for this user."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT metadata_id FROM metadata_groups
            WHERE user_email = %s
            ORDER BY last_updated_date DESC NULLS LAST, metadata_id DESC
            LIMIT %s
        """, (user_email, limit))
        ids = [r[0] for r in cur.fetchall()]
    columns = []
    for mid in ids:
        cols = get_metadata_group_classifications(conn, mid) or []
        for c in cols:
            columns.append({**c, "_metadataId": mid})
    return columns


def _classifications_from_linked_datasets(conn, metadata_id):
    """If the metadata group was saved with empty classifications (LLM skipped),
    rebuild them from per-dataset JSON and, failing that, from stored rows."""
    merged = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT classifications FROM datasets WHERE metadata_id = %s",
            (metadata_id,),
        )
        for (ds_cls,) in cur.fetchall():
            for name, codes in (ds_cls or {}).items():
                if name not in merged and codes:
                    merged[name] = codes
        if merged:
            # Strip identifiers (RecordID etc.) persisted before the categorical filter.
            return _filter_classification_dict(merged)
        cur.execute("""
            SELECT dr.row_data
            FROM datasets d
            JOIN dataset_rows dr ON dr.dataset_id = d.dataset_id
            WHERE d.metadata_id = %s
            ORDER BY d.dataset_id, dr.row_index
        """, (metadata_id,))
        rows = [r[0] or {} for r in cur.fetchall()]
    if not rows:
        return {}
    cols = list(rows[0].keys())
    return _classifications_from_table_data([{"columns": cols, "rows": rows}])


def _normalize_classification_values(vals) -> list:
    """Coerce LLM / workbook / heuristic classification entries to a list of
    {code, value, definition} dicts. Handles list[str], list[dict], a lone
    string (must not iterate characters), and empty/invalid inputs."""
    if vals is None:
        return []
    if isinstance(vals, str):
        s = vals.strip()
        return [{"code": "", "value": s, "definition": None}] if s else []
    if isinstance(vals, dict):
        # Single code-list entry shaped as a dict.
        if any(k in vals for k in ("code", "value", "definition")):
            return [_normalize_code_entry(vals)]
        # Rare LLM shape: {"values": [...]}
        if isinstance(vals.get("values"), list):
            return _normalize_classification_values(vals.get("values"))
        return []
    if not isinstance(vals, (list, tuple)):
        s = str(vals).strip()
        return [{"code": "", "value": s, "definition": None}] if s else []

    out = []
    seen = set()
    for v in vals:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                continue
            entry = {"code": "", "value": s, "definition": None}
        else:
            entry = _normalize_code_entry(v)
        key = (str(entry.get("value") or entry.get("code") or "").strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _classifications_from_table_data(tables):
    """Treat categorical (non-numeric label) columns as classification dimensions.

    Used for Excel without a classifications workbook and for SQL extracts,
    where there is no metadata-excel code list.

    Skips TOC/index tables and serial/contents/page/identifier/free-text
    columns so the Classify UI only shows true categorical chips.
    """
    merged = {}
    for table in tables or []:
        if _looks_like_index_or_toc_table(table):
            continue
        columns = _column_names_from_table(table)
        rows = table.get("rows") or []
        for col in columns:
            if _looks_like_non_classification_column_name(col):
                continue
            values, seen = [], set()
            n_non_empty = 0
            n_label = 0
            for row in rows:
                if isinstance(row, dict):
                    raw = row.get(col)
                elif isinstance(row, (list, tuple)):
                    # Positional rows (rare in Excel/SQL path) — skip; need names.
                    continue
                else:
                    continue
                if raw is None or raw == "":
                    continue
                if isinstance(raw, bool):
                    s = "true" if raw else "false"
                else:
                    s = str(raw).strip()
                if not s:
                    continue
                n_non_empty += 1
                # Pure numerics are measures, not category labels.
                if _is_numeric_cell(s):
                    continue
                n_label += 1
                key = s.lower()
                if key in seen:
                    continue
                seen.add(key)
                values.append({"code": "", "value": s, "definition": None})
            if not _should_keep_classification_column(
                col, values, n_non_empty, n_label=n_label
            ):
                continue
            name = re.sub(r"\s+", "_", str(col).strip()) or str(col)
            if name not in merged:
                merged[name] = values
            else:
                existing = {(e.get("value") or "").lower() for e in merged[name]}
                for e in values:
                    if (e["value"] or "").lower() not in existing:
                        merged[name].append(e)
                        existing.add((e["value"] or "").lower())
    return _collapse_near_duplicate_dimensions(merged)


def _merge_real_classifications(llm_merged, real):
    """Real metadata-excel code lists win per column name; LLM/heuristic
    guesses fill columns the workbook didn't cover. Values are normalized."""
    merged = {
        str(k): _normalize_classification_values(v)
        for k, v in (llm_merged or {}).items()
        if _normalize_classification_values(v)
    }
    for k, v in (real or {}).items():
        norm = _normalize_classification_values(v)
        if norm:
            merged[str(k)] = norm
    return _filter_classification_dict(merged)


def _classification_value_key(entries):
    vals = []
    for e in entries or []:
        if isinstance(e, dict):
            v = str(e.get("value") or "").strip().lower()
        else:
            v = str(e).strip().lower()
        if v:
            vals.append(v)
    return tuple(sorted(vals))


def _expand_alias_names(classifications, names, codes):
    """Include hidden duplicate columns that share the same value list."""
    names = [n for n in names if n]
    target = _classification_value_key(codes)
    if not target:
        return names
    occ = any(_is_occupation_name(n) for n in names)
    extra = [
        n for n, ents in (classifications or {}).items()
        if n not in names
        and _is_occupation_name(n) == occ
        and _classification_value_key(ents) == target
    ]
    return names + extra


def update_metadata_group_classification_column(
    conn, metadata_id, column_name, codes, column_names=None, expand_aliases=True,
):
    """Persist code/definition rows to the metadata group and every linked
    dataset table. expand_aliases copies to hidden same-value columns."""
    names = [n for n in (column_names or [column_name]) if n]
    if not names:
        return False
    with conn.cursor() as cur:
        cur.execute("SELECT classifications FROM metadata_groups WHERE metadata_id = %s FOR UPDATE", (metadata_id,))
        row = cur.fetchone()
        if not row:
            return False
        classifications = row[0] or {}
        if expand_aliases:
            names = _expand_alias_names(classifications, names, codes)
        for name in names:
            classifications[name] = codes
        cur.execute(
            "UPDATE metadata_groups SET classifications = %s WHERE metadata_id = %s",
            (json.dumps(classifications), metadata_id),
        )
        cur.execute(
            "SELECT dataset_id, classifications FROM datasets WHERE metadata_id = %s FOR UPDATE",
            (metadata_id,),
        )
        for dataset_id, ds_cls in cur.fetchall():
            ds_cls = dict(ds_cls or {})
            ds_names = _expand_alias_names(ds_cls, names, codes) if expand_aliases else names
            changed = False
            for name in ds_names:
                if ds_cls.get(name) != codes:
                    ds_cls[name] = codes
                    changed = True
            if changed:
                cur.execute(
                    "UPDATE datasets SET classifications = %s WHERE dataset_id = %s",
                    (json.dumps(ds_cls), dataset_id),
                )
    conn.commit()
    return True


def _merge_classifications(enriched_data: list) -> dict:
    """Merge classifications across all enriched tables, deduplicating values per dimension."""
    merged: dict = {}
    for enriched in enriched_data:
        cls = enriched.get("classifications") or {}
        for dim, vals in cls.items():
            norm = _normalize_classification_values(vals)
            if not norm:
                continue
            if dim not in merged:
                merged[dim] = []
            existing = {(e.get("value") or "").lower() for e in merged[dim]}
            for entry in norm:
                key = (entry.get("value") or "").lower()
                if key and key not in existing:
                    merged[dim].append(entry)
                    existing.add(key)
    return _filter_classification_dict(merged)


def _classification_fill_ratio(classifications) -> float:
    """Share of classification entries that have a non-empty definition."""
    if not isinstance(classifications, dict) or not classifications:
        return 0.0
    total = 0
    filled = 0
    for codes in classifications.values():
        if not isinstance(codes, list):
            continue
        for entry in codes:
            total += 1
            if isinstance(entry, dict):
                if str(entry.get("definition") or "").strip():
                    filled += 1
            # Plain strings are codes without definitions — not filled.
    if total == 0:
        return 0.0
    return filled / total
