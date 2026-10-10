"""Stage 4 -- LLM metadata autofill for catalogue/PDF groups (mirrors the
notebook's `generate_metadata_per_group`)."""
import concurrent.futures
import json as _json
import os
import re
from typing import Any, Optional

from app.services.ingestion.wizard.extractor import TableExtractor
from app.services.metadata.metadata_llm import (
    METADATA_FIELDS,
    SDG_METADATA_FIELDS,
    extract_excel_facts,
    extract_facts_from_tables,
    generate_metadata_with_llm,
    generate_sdg_metadata_with_llm,
    parse_llm_metadata_output,
    parse_llm_sdg_metadata_output,
)

# Cap concurrent Stage 4 LLM calls the same way Excel extraction does —
# enough to cut wall time across many groups without thrashing rate limits.
_STAGE4_MAX_WORKERS = 5


def _group_metadata_is_empty(metadata: Optional[dict], fields: Optional[list] = None) -> bool:
    """True when no *fillable* catalogue fields are set.

    `title` alone does not count — grouping often stamps a display title while
    Product / Geography / Description etc. are still blank and need Stage 4.
    """
    keys = fields if fields is not None else METADATA_FIELDS
    fillable = [f for f in keys if f != "title"]
    return not any(str((metadata or {}).get(f) or "").strip() for f in fillable)


def _kyds_data_source(kyds: Optional[dict]) -> str:
    """KYDS department/ministry — preferred agency Source, never a filename."""
    if not isinstance(kyds, dict):
        return ""
    return str(kyds.get("department") or "").strip()


_FILE_EXT_RE = re.compile(r"\.(xlsx|xls|csv|pdf|tsv|ods)(\b|$)", re.I)


def _looks_like_filename_source(value: str, known_names: Optional[set] = None) -> bool:
    """True when Source looks like a workbook/path rather than an agency name."""
    text = str(value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if known_names and lower in {str(n).strip().lower() for n in known_names if n}:
        return True
    base = os.path.basename(text.replace("\\", "/"))
    if _FILE_EXT_RE.search(base):
        return True
    if "/" in text or "\\" in text:
        return True
    return False


def _resolve_data_source(
    current: Any,
    kyds: Optional[dict],
    known_filenames: Optional[set] = None,
) -> str:
    """Prefer KYDS department over empty/filename Sources; keep real agency names.

    Groups may legitimately differ — only replace missing or filename-like values.
    """
    kyds_source = _kyds_data_source(kyds)
    text = str(current or "").strip()
    if not text or _looks_like_filename_source(text, known_filenames):
        return kyds_source
    return text


def _sanitize_group_data_source(
    g: dict,
    kyds: Optional[dict],
    known_filenames: Optional[set] = None,
) -> None:
    """Fix filename-like Source on one group; leave distinct agency Sources alone."""
    meta = dict(g.get("metadata") or {})
    resolved = _resolve_data_source(meta.get("data_source"), kyds, known_filenames)
    if resolved != str(meta.get("data_source") or "").strip():
        meta["data_source"] = resolved
        g["metadata"] = meta
    catalogue = g.get("catalogue_metadata")
    if isinstance(catalogue, dict):
        cat_resolved = _resolve_data_source(catalogue.get("data_source"), kyds, known_filenames)
        if cat_resolved != str(catalogue.get("data_source") or "").strip():
            g["catalogue_metadata"] = {**catalogue, "data_source": cat_resolved}


def _known_filenames_for_group(g: dict, facts: Optional[dict] = None) -> set:
    names: set = set()
    if facts and facts.get("filename"):
        names.add(str(facts["filename"]))
    for mt in g.get("matched_tables") or []:
        t = mt.get("table") if isinstance(mt, dict) else None
        if isinstance(t, dict) and t.get("source_file"):
            names.add(str(t["source_file"]))
    for t in g.get("tables") or []:
        if isinstance(t, dict) and t.get("source_file"):
            names.add(str(t["source_file"]))
    if g.get("file_name"):
        names.add(str(g["file_name"]))
    if g.get("name"):
        names.add(str(g["name"]))
    return names


def _format_key_statistics(value: Any) -> Optional[str]:
    """Turn LLM key_statistics into catalogue-ready plain text.

    Models often dump sample_rows as a JSON array of objects; convert that into
    short bullets instead of json.dumps for the metadata textarea.
    """
    if value is None or value == "":
        return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text[0] in "[{":
            try:
                return _format_key_statistics(_json.loads(text))
            except (_json.JSONDecodeError, TypeError, ValueError):
                return text
        return text

    if isinstance(value, dict):
        lines = []
        for key, val in value.items():
            if val is None or str(val).strip() == "":
                continue
            if isinstance(val, (dict, list)):
                nested = _format_key_statistics(val)
                if nested:
                    lines.append(f"• {key}: {nested.replace(chr(10), ' ')}")
            else:
                lines.append(f"• {key}: {val}")
        return "\n".join(lines) if lines else None

    if isinstance(value, list):
        lines = []
        for item in value[:12]:
            if isinstance(item, dict):
                label = (
                    item.get("Sub-Group")
                    or item.get("sub_group")
                    or item.get("subgroup")
                    or item.get("Category")
                    or item.get("category")
                    or item.get("Item")
                    or item.get("item")
                    or item.get("name")
                    or item.get("title")
                    or item.get("Group")
                    or item.get("group")
                )
                weight = item.get("Weight") if "Weight" in item else item.get("weight")
                parts = []
                if label is not None and str(label).strip():
                    parts.append(str(label).strip())
                group = item.get("Group") if label and "Group" in item else None
                if group is not None and str(group).strip() and str(group) != str(label):
                    parts[0] = f"{parts[0]} (Group {group})" if parts else f"Group {group}"
                if weight is not None and str(weight).strip() != "":
                    parts.append(f"weight {weight}")

                skip = {
                    "Group", "group", "Sub-Group", "sub_group", "subgroup",
                    "Category", "category", "Item", "item", "name", "title",
                    "Weight", "weight",
                }
                numeric = []
                extras = []
                for key, val in item.items():
                    if key in skip or val is None or str(val).strip() == "":
                        continue
                    try:
                        numeric.append((str(key), float(str(val).replace(",", ""))))
                    except (TypeError, ValueError):
                        extras.append(f"{key} {val}")
                if numeric:
                    first_k, first_v = numeric[0]
                    last_k, last_v = numeric[-1]
                    if first_k == last_k:
                        parts.append(f"{first_k} {first_v:g}")
                    else:
                        parts.append(f"{first_k} {first_v:g} → {last_k} {last_v:g}")
                parts.extend(extras[:3])
                if parts:
                    lines.append("• " + "; ".join(parts))
                else:
                    compact = ", ".join(f"{k}: {v}" for k, v in list(item.items())[:6])
                    if compact:
                        lines.append(f"• {compact}")
            elif item is not None and str(item).strip():
                lines.append(f"• {item}")
        return "\n".join(lines) if lines else None

    return str(value)


def _stringify_field_values(metadata: dict, fields: list) -> dict:
    """Normalize LLM field values to plain strings for form inputs."""
    out = {}
    for field in fields:
        v = metadata.get(field)
        if field == "key_statistics":
            out[field] = _format_key_statistics(v)
            continue
        if v is None or v == "":
            out[field] = None
        elif isinstance(v, (dict, list)):
            out[field] = _json.dumps(v)
        else:
            out[field] = str(v)
    return out


def _stringify_metadata_values(metadata: dict) -> dict:
    """Normalize every field to a plain string for text inputs/textareas.

    ``key_statistics`` is specially formatted as readable bullets when the LLM
    returns structured JSON instead of prose.
    """
    return _stringify_field_values(metadata, METADATA_FIELDS)


def _stringify_sdg_metadata_values(metadata: dict) -> dict:
    return _stringify_field_values(metadata, SDG_METADATA_FIELDS)


def _fill_empty_group_metadata(
    groups: list,
    dataset_bytes_by_filename: dict,
    kyds_responses: Optional[dict],
    extractor: TableExtractor,
    standard: str = "nmds",
) -> tuple[bool, list[dict]]:
    """Stage 4 -- LLM metadata creation per group (mirrors the notebook's
    `generate_metadata_per_group`). Only groups with no metadata (i.e. not
    matched to a row in an uploaded metadata workbook) are touched; groups
    that already carry values parsed from a metadata file are left as-is,
    per bullet 1 -- metadata-file entry stays the source of truth when the
    user provided one.

    When `standard` is `sdg`, fills UN SDG indicator fields instead of the
    catalogue sheet fields. Catalogue values are still produced when possible
    and stored on `catalogue_metadata` for push/display compatibility.

    Facts come from either:
      - uploaded Excel workbook bytes (`dataset_bytes_by_filename` + extract_excel_facts), or
      - already-extracted in-memory tables (SQL / any source without workbook bytes)
        via extract_facts_from_tables.
    KYDS responses come from Postgres via ``app.db.repositories.kyds``
    (``get_latest_responses``).

    `extractor` supplies the LLM call, built from the caller's own Settings
    key/provider (see `deps._extractor_for`) rather than a server-side env var.

    Returns `(skipped_no_key, errors)` where `errors` lists per-group failures
    as `{group, error}` so the UI can explain why fields are still empty and
    let the user fill them in manually.
    """
    if not kyds_responses:
        # Still report a missing LLM key so the metadata UI can prompt for it
        # even when KYDS is absent (KYDS-missing is a separate client flag).
        if getattr(extractor, "skip_llm", False):
            return True, []
        return False, []

    use_sdg = str(standard or "nmds").lower() == "sdg"

    def _group_tables(g: dict) -> list:
        matched = [mt["table"] for mt in g.get("matched_tables", []) if mt.get("table")]
        if matched:
            return matched
        # PDF grouping shape uses a flat `tables` list until the client
        # normalizes to matched_tables for BatchReview / batch-push.
        return [t for t in (g.get("tables") or []) if isinstance(t, dict)]

    def _is_empty(g: dict) -> bool:
        if use_sdg:
            # Prefer dedicated concept blob when present; otherwise treat
            # metadata keyed by SDG labels as the fill target.
            concept_meta = g.get("concept_metadata")
            if isinstance(concept_meta, dict) and concept_meta:
                return _group_metadata_is_empty(concept_meta, SDG_METADATA_FIELDS)
            return _group_metadata_is_empty(g.get("metadata"), SDG_METADATA_FIELDS)
        return _group_metadata_is_empty(g.get("metadata"), METADATA_FIELDS)

    def _needs_llm_fill(g: dict) -> bool:
        """True when catalogue fields besides title/Source are still blank.

        Grouping stamps a title, and KYDS (or a filename) may already occupy
        Source. Neither of those should block Stage 4 when a Settings key is
        present. Groups that already carry workbook values (Product,
        Description, and so on) stay untouched.
        """
        if not _group_tables(g):
            return False
        if use_sdg:
            return _is_empty(g)
        meta = g.get("metadata") or {}
        others = [f for f in METADATA_FIELDS if f not in ("title", "data_source")]
        return not any(str(meta.get(f) or "").strip() for f in others)

    # Decide before KYDS source injection as well as after a previous pass
    # that only wrote Source. Either way, Source alone must not skip the LLM.
    fill_ids = {i for i, g in enumerate(groups) if _needs_llm_fill(g)}

    # Replace filename-like Sources with KYDS department; leave real agency
    # names alone so groups can still differ when appropriate.
    for g in groups:
        _sanitize_group_data_source(g, kyds_responses, _known_filenames_for_group(g))

    if not fill_ids:
        return False, []
    if extractor.skip_llm:
        return True, []

    # Build facts serially (openpyxl / shared cache), then run LLM calls in
    # parallel. Same per-group outcomes as the old sequential loop.
    facts_cache: dict = {}
    jobs: list[tuple[int, dict, dict]] = []  # (gi, group, facts)
    err_by_gi: dict[int, dict] = {}
    for gi in sorted(fill_ids):
        g = groups[gi]
        tables = _group_tables(g)
        if not tables:
            continue
        group_label = g.get("file_name") or g.get("name") or "Untitled group"
        source_file = tables[0].get("source_file") or group_label or "extracted"
        content = (dataset_bytes_by_filename or {}).get(source_file)
        try:
            if content:
                if source_file not in facts_cache:
                    facts_cache[source_file] = extract_excel_facts(content, source_file)
                facts = facts_cache[source_file]
            else:
                cache_key = f"tables::{source_file}::{g.get('file_name')}"
                if cache_key not in facts_cache:
                    facts_cache[cache_key] = extract_facts_from_tables(tables, source_file)
                facts = facts_cache[cache_key]
            jobs.append((gi, g, facts))
        except Exception as e:
            msg = str(e).strip() or e.__class__.__name__
            print(f"Stage 4 LLM metadata generation failed for group {group_label}: {msg}")
            err_by_gi[gi] = {"index": gi, "group": group_label, "error": msg}

    def _apply_llm_fill(gi: int, g: dict, facts: dict) -> Optional[dict]:
        """Run one group's LLM fill. Returns an error dict on failure, else None.

        Mutates only `g` (unique per index), so concurrent workers do not race.
        """
        group_label = g.get("file_name") or g.get("name") or "Untitled group"
        try:
            if use_sdg:
                llm_output = generate_sdg_metadata_with_llm(
                    facts, kyds=kyds_responses, complete_fn=extractor._complete,
                )
                sdg_meta = _stringify_sdg_metadata_values(parse_llm_sdg_metadata_output(llm_output))
                g["concept_metadata"] = sdg_meta
                # Drive the metadata page grid from SDG fields when that
                # standard is selected; keep any prior catalogue values aside.
                prior = g.get("metadata") or {}
                if any(prior.get(f) for f in METADATA_FIELDS):
                    g["catalogue_metadata"] = {
                        f: prior.get(f) for f in METADATA_FIELDS if prior.get(f)
                    }
                g["metadata"] = sdg_meta
                g["_llm_filled"] = True
                g["_llm_filled_fields"] = [
                    f for f in SDG_METADATA_FIELDS if str(sdg_meta.get(f) or "").strip()
                ]
            else:
                llm_output = generate_metadata_with_llm(
                    facts, kyds=kyds_responses, complete_fn=extractor._complete,
                )
                meta = _stringify_metadata_values(parse_llm_metadata_output(llm_output))
                known = _known_filenames_for_group(g, facts)
                meta["data_source"] = _resolve_data_source(
                    meta.get("data_source"), kyds_responses, known,
                )
                g["metadata"] = meta
                g["_llm_filled"] = True
                g["_llm_filled_fields"] = [
                    f for f in METADATA_FIELDS if str(meta.get(f) or "").strip()
                ]
            # Keep a display name when the client sent PDF-style groups.
            if not g.get("file_name") and g.get("name"):
                g["file_name"] = g["name"]
            return None
        except Exception as e:
            msg = str(e).strip() or e.__class__.__name__
            print(f"Stage 4 LLM metadata generation failed for group {group_label}: {msg}")
            return {"index": gi, "group": group_label, "error": msg}

    if jobs:
        workers = min(_STAGE4_MAX_WORKERS, len(jobs))
        if workers <= 1:
            for gi, g, facts in jobs:
                err = _apply_llm_fill(gi, g, facts)
                if err:
                    err_by_gi[gi] = err
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(_apply_llm_fill, gi, g, facts)
                    for gi, g, facts in jobs
                ]
                for future in concurrent.futures.as_completed(futures):
                    err = future.result()
                    if err:
                        err_by_gi[int(err["index"])] = err

    # Preserve ascending group-index order (matches the old sequential loop).
    errors = [err_by_gi[i] for i in sorted(err_by_gi)]

    # Final pass: strip any filename Sources the model still leaked in.
    for g in groups:
        _sanitize_group_data_source(g, kyds_responses, _known_filenames_for_group(g))
    return False, errors
