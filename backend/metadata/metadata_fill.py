"""Stage 4 -- LLM metadata autofill for catalogue/PDF groups (mirrors the
notebook's `generate_metadata_per_group`)."""
import json as _json
from typing import Optional

from extraction.extractor import TableExtractor
from metadata.metadata_llm import (
    METADATA_FIELDS,
    SDG_METADATA_FIELDS,
    extract_excel_facts,
    extract_facts_from_tables,
    generate_metadata_with_llm,
    generate_sdg_metadata_with_llm,
    parse_llm_metadata_output,
    parse_llm_sdg_metadata_output,
)


def _group_metadata_is_empty(metadata: Optional[dict], fields: Optional[list] = None) -> bool:
    keys = fields if fields is not None else METADATA_FIELDS
    return not any((metadata or {}).get(f) for f in keys)


def _stringify_field_values(metadata: dict, fields: list) -> dict:
    """Normalize LLM field values to plain strings for form inputs."""
    out = {}
    for field in fields:
        v = metadata.get(field)
        if v is None or v == "":
            out[field] = None
        elif isinstance(v, (dict, list)):
            out[field] = _json.dumps(v)
        else:
            out[field] = str(v)
    return out


def _stringify_metadata_values(metadata: dict) -> dict:
    """The LLM can return a structured value for a field like `key_statistics`
    (see the notebook's own example output, a JSON object of headline
    numbers) -- normalize every field to a plain string so it renders safely
    in a text input/textarea on the frontend."""
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
    KYDS responses come from Postgres (see catalogue.get_latest_kyds_responses).

    `extractor` supplies the LLM call, built from the caller's own Settings
    key/provider (see `deps._extractor_for`) rather than a server-side env var.

    Returns `(skipped_no_key, errors)` where `errors` lists per-group failures
    as `{group, error}` so the UI can explain why fields are still empty and
    let the user fill them in manually.
    """
    if not kyds_responses:
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

    has_fillable_group = any(_is_empty(g) and _group_tables(g) for g in groups)
    if not has_fillable_group:
        return False, []
    if extractor.skip_llm:
        return True, []

    facts_cache: dict = {}
    errors: list[dict] = []

    for gi, g in enumerate(groups):
        if not _is_empty(g):
            continue
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
            else:
                llm_output = generate_metadata_with_llm(
                    facts, kyds=kyds_responses, complete_fn=extractor._complete,
                )
                g["metadata"] = _stringify_metadata_values(parse_llm_metadata_output(llm_output))
            # Keep a display name when the client sent PDF-style groups.
            if not g.get("file_name") and g.get("name"):
                g["file_name"] = g["name"]
        except Exception as e:
            msg = str(e).strip() or e.__class__.__name__
            print(f"Stage 4 LLM metadata generation failed for group {group_label}: {msg}")
            errors.append({"index": gi, "group": group_label, "error": msg})

    return False, errors
