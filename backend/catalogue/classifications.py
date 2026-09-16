"""Classification code lists: read/rebuild/normalize/persist for the Classify step."""
import json
import re


def _normalize_code_entry(entry):
    """A classification entry is normally {code, value, definition} (from the
    real metadata-excel parse). But when no metadata-excel sheet covered a
    dimension, the LLM-guessed fallback stores it as a flat list of plain
    value strings instead — normalize those too so the frontend always gets
    a consistent {code, value, definition} shape."""
    if isinstance(entry, dict):
        return {"code": entry.get("code"), "value": entry.get("value"), "definition": entry.get("definition")}
    return {"code": entry, "value": entry, "definition": None}


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
            rebuilt = _classifications_from_linked_datasets(conn, metadata_id) or {}
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
            return merged
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
        return [{"code": s, "value": s, "definition": None}] if s else []
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
        return [{"code": s, "value": s, "definition": None}] if s else []

    out = []
    seen = set()
    for v in vals:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                continue
            entry = {"code": s, "value": s, "definition": None}
        else:
            entry = _normalize_code_entry(v)
        key = (str(entry.get("value") or entry.get("code") or "").strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _classifications_from_table_data(tables):
    """Treat low-cardinality non-numeric columns as classification dimensions.

    Used for Excel without a classifications workbook and for SQL extracts,
    where there is no metadata-excel code list."""
    merged = {}
    for table in tables or []:
        raw_columns = table.get("columns") or []
        columns = []
        for i, col in enumerate(raw_columns):
            if isinstance(col, str):
                columns.append(col)
            elif isinstance(col, dict):
                columns.append(str(col.get("name") or f"column_{i + 1}"))
            else:
                columns.append(f"column_{i + 1}")
        rows = table.get("rows") or []
        for col in columns:
            values, seen = [], set()
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
                # Skip pure numerics (measures), keep codes like "01" that are
                # categorical when mixed with non-numeric — only skip if the
                # whole string parses as a number AND has no alpha.
                if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", s.replace(",", "")):
                    continue
                key = s.lower()
                if key in seen:
                    continue
                seen.add(key)
                values.append({"code": s, "value": s, "definition": None})
                if len(values) > 80:
                    break
            if 2 <= len(values) <= 80:
                name = re.sub(r"\s+", "_", str(col).strip()) or str(col)
                if name not in merged:
                    merged[name] = values
                else:
                    existing = {(e.get("value") or "").lower() for e in merged[name]}
                    for e in values:
                        if (e["value"] or "").lower() not in existing:
                            merged[name].append(e)
                            existing.add((e["value"] or "").lower())
    return merged


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
    return merged


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


def _is_occupation_name(name):
    return bool(re.search(r"occupat", name or "", re.I))


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
    return merged


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
