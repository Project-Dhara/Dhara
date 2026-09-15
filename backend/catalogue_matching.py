"""Matches AI-extracted dataset tables against uploaded metadata workbooks.

Three tiers, tried in order, first hit wins:

  1. exact  -- the extractor's generated ID (e.g. "DDI_DEL_DES_VS_S1_URBAN_
     2024_V1") matches a metadata `unique dataset id` exactly (normalized).
  2. stem   -- same as above but ignoring a trailing "_<year>_<version>"
     segment, to tolerate typos in the source spreadsheet (real example:
     "_2024_V1" vs "_2024_vV").
  3. code   -- falls back to a short table code (e.g. "D10", "B12(1)")
     matched against the metadata's `table_id` column. When a code has more
     than one metadata row (e.g. an urban/rural split, or a religion
     breakdown), it disambiguates using a keyword unique to each row's
     description, searched against the table's title/description/sheet
     *and* its own extracted ID -- the ID often carries a breakdown label
     (e.g. "..._HINDU_...") that the title/description doesn't, because the
     extractor derives it from the sheet's sub-header rows, not just the
     title. Two identical-looking tables ("...religion of the family
     (urban)") can only be told apart this way.

Code derivation differs by side:
  - metadata `table_id` (e.g. "b-12(1)"): the "(1)" is a real government
    sub-table number, kept as-is.
  - extracted table `title` (e.g. "TABLE: B-12 (2)"): a trailing "(N)" here
    is the extractor's OWN per-sheet dedup counter (e.g. "2nd table found on
    this sheet" = rural, after urban) -- unrelated noise, always stripped.
    The real sub-table number (e.g. mother's education level) instead lives
    in the table's `sheet` name ("table 12(i)", "table 12 (2)") and is
    pulled from there.

Nothing here writes to the database -- it only produces a proposed mapping
for a human to review before anything is pushed.
"""

import re
from typing import Dict

ROMAN_TO_INT = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}


def normalize_id(raw: str) -> str:
    if not raw:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(raw).upper())


def id_stem(raw: str) -> str:
    """Drops a trailing "_<4-digit-year>_<version>" segment before
    normalizing, so near-identical IDs that only differ in a typo'd
    year/version suffix still match."""
    if not raw:
        return ""
    s = str(raw).upper()
    s = re.sub(r"_\d{4}_[A-Z0-9]+$", "", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def normalize_inventory_code(raw: str) -> str:
    """"b-12(1)" -> "B121". Strips annotations like "(PROVISIONAL)" but
    keeps numeric sub-table suffixes like "(1)" -- these are real
    government table numbers in the metadata's table_id column."""
    if not raw:
        return ""
    s = str(raw).upper()
    s = re.sub(r"TABLE", "", s)
    s = re.sub(r"\([^)\d][^)]*\)", "", s)
    return re.sub(r"[^A-Z0-9&]", "", s)


def _sheet_suffix(sheet_name: str) -> str:
    """Pulls a trailing "(1)" / "(i)" off a sheet name and returns it as a
    plain digit string, converting roman numerals if needed."""
    match = re.search(r"\(([A-Za-z0-9]+)\)\s*$", str(sheet_name or "").strip())
    if not match:
        return ""
    token = match.group(1).upper()
    if token.isdigit():
        return token
    roman = ROMAN_TO_INT.get(token)
    return str(roman) if roman else ""


def extracted_table_code(table: dict) -> str:
    """Derives a matchable code from an extracted table's table_id + sheet
    name. Unlike normalize_inventory_code, ALL parenthetical content in the
    table_id is stripped -- see module docstring for why."""
    table_id = str(table.get("table_id", "") or "").upper()
    table_id = re.sub(r"TABLE", "", table_id)
    table_id = re.sub(r"\([^)]*\)", "", table_id)
    base = re.sub(r"[^A-Z0-9&]", "", table_id)
    suffix = _sheet_suffix(table.get("sheet", ""))
    return f"{base}{suffix}" if suffix else base


def _distinguishing_word(description: str, others: list) -> str:
    words = re.findall(r"[a-z]+", str(description or "").lower())
    other_words = set()
    for o in others:
        other_words.update(re.findall(r"[a-z]+", str(o or "").lower()))
    for w in words:
        if len(w) > 3 and w not in other_words:
            return w
    return None


def _base_title(title: str) -> str:
    """Strips a trailing parenthetical qualifier, e.g. "INFANT DEATHS BY ...
    (URBAN)" -> "INFANT DEATHS BY ...", so an urban/rural (or similar) split
    of the same table collapses to one base title. Ported from the
    notebook's Stage 3 `auto_group_tables`."""
    base = re.sub(r"\s*\([^)]*\)\s*$", "", title or "").strip()
    base = re.sub(r"\s+", " ", base).upper()
    return base or (title or "").strip().upper()


_GROUP_NAME_NOISE = {"sl", "no"}


def build_group_name(base_title: str) -> str:
    """Derives a presentable name for an auto-grouped bucket of tables from
    their (final, user-saved) title alone -- e.g. "Age Urban Rural All"
    rather than "Infant & Mother Death D12-D182.xlsx — Sl. No. Age Urban
    Rural All". Never includes the source filename or any other file detail,
    and is never truncated -- the full title is always shown."""
    title = re.sub(r"\s+", " ", (base_title or "")).strip()
    if not title:
        return "Untitled group"

    # Drop leading enumeration/header noise ("Sl.", "No.") -- it labels a
    # column, not the table's subject, so it adds no meaning to a group name.
    words = title.split(" ")
    while words and words[0].strip(".,").lower() in _GROUP_NAME_NOISE:
        words.pop(0)
    cleaned = " ".join(words).strip(" .,-") or title

    return cleaned.title()


def auto_group_tables(tables: list) -> list:
    """Title-base buckets used when matching leftovers against inventory.

    Primary no-metadata grouping for Excel/SQL/PDF now lives in
    ``pdf_grouping.propose_groups_from_table_dicts`` (via
    ``_groups_without_metadata``). This helper remains for inventory-match
    disambiguation and client-side title re-homing.

    Tables sharing the same base title (trailing URBAN/RURAL-style qualifier
    stripped) land together across sheets and source files.
    """
    groups_dict: Dict[str, dict] = {}
    order = []
    for table in tables:
        source_file = table.get("source_file") or "Dataset"
        sheet = table.get("sheet", "")
        base_title = _base_title(table.get("title", ""))
        group_key = base_title

        if group_key not in groups_dict:
            groups_dict[group_key] = {
                "source_file": source_file,
                "sheet": sheet,
                "source_files": set(),
                "base_title": base_title,
                "tables": [],
            }
            order.append(group_key)
        groups_dict[group_key]["source_files"].add(source_file)
        groups_dict[group_key]["tables"].append(table)

    result = [groups_dict[k] for k in order]
    for g in result:
        g["source_files"] = sorted(g["source_files"])
    return result


_EMPTY_METADATA = {
    "title": "",
    "product": "",
    "category": "",
    "geography": "",
    "frequency": "",
    "time_period": "",
    "data_source": "",
    "description": "",
    "last_updated": "",
    "future_release": "",
    "key_statistics": "",
    "remarks": "",
}


def _groups_without_metadata(extracted_tables: list) -> dict:
    """Propose catalogue groups when no metadata workbook was uploaded.

    Uses the shared PDF title / SDG grouping rules (``pdf_grouping``) so
    Excel, SQL, and PDF all bucket tables the same way after preview.
    Lazy-import avoids a circular import with ``pdf_grouping``.
    """
    from pdf_grouping import (
        propose_groups_from_table_dicts,
        proposal_to_catalogue_match_result,
    )

    source_type = "xlsx"
    default_source = "Dataset"
    if extracted_tables:
        first = extracted_tables[0] or {}
        st = str(first.get("source_type") or "").lower()
        if st in ("pdf", "sql", "xlsx", "xls"):
            source_type = "xlsx" if st == "xls" else st
        default_source = first.get("source_file") or first.get("filename") or default_source

    proposal = propose_groups_from_table_dicts(extracted_tables)
    return proposal_to_catalogue_match_result(
        proposal,
        source_type=source_type,
        default_source_file=default_source,
    )


def match_tables_to_metadata(extracted_tables: list, metadata_workbooks: list) -> dict:
    """
    extracted_tables: [{id, table_id, title, sheet, source_file, ...}, ...]
    metadata_workbooks: [{file_name, summary, inventory, concepts, classifications}, ...]

    Returns:
      {
        "groups": [{workbook_index, file_name, metadata, concepts,
                    classifications, matched_tables: [{table, inventory_item,
                    confidence}]}, ...],
        "unmatched_tables": [{table, confidence}, ...],
        "unmatched_inventory": [{file_name, inventory_item}, ...],
      }
    """
    if not metadata_workbooks:
        return _groups_without_metadata(extracted_tables)

    exact_index = {}
    stem_index = {}
    code_index = {}
    for wi, mw in enumerate(metadata_workbooks):
        for item in mw["inventory"]:
            uid = item["unique_dataset_id"]
            exact_index[normalize_id(uid)] = (wi, item)
            stem_index.setdefault(id_stem(uid), []).append((wi, item))
            code_index.setdefault(normalize_inventory_code(item["table_id"]), []).append((wi, item))

    groups = [
        {
            "workbook_index": wi,
            "file_name": mw["file_name"],
            "metadata": mw["summary"],
            "concepts": mw["concepts"],
            "classifications": mw["classifications"],
            "matched_tables": [],
        }
        for wi, mw in enumerate(metadata_workbooks)
    ]

    used_inventory_ids = set()
    unmatched_tables = []

    def _available(candidates):
        return [c for c in candidates if id(c[1]) not in used_inventory_ids]

    for table in extracted_tables:
        tid = table.get("id", "")
        hit = None
        confidence = None

        exact_hit = exact_index.get(normalize_id(tid))
        if exact_hit and id(exact_hit[1]) not in used_inventory_ids:
            hit, confidence = exact_hit, "exact"

        if not hit:
            candidates = _available(stem_index.get(id_stem(tid), []))
            if len(candidates) == 1:
                hit, confidence = candidates[0], "stem"

        if not hit:
            code = extracted_table_code(table)
            candidates = _available(code_index.get(code, []))
            if len(candidates) == 1:
                hit, confidence = candidates[0], "code"
            elif len(candidates) > 1:
                # The extracted ID itself often carries a breakdown label
                # (e.g. "..._HINDU_...") that the table_id/title doesn't,
                # since the extractor derives it from sub-header rows deeper
                # in the sheet -- include it in the search text.
                haystack = " ".join([
                    str(table.get("table_id", "")),
                    str(table.get("title", "")),
                    str(table.get("sheet", "")),
                    str(table.get("id", "")),
                ]).lower()
                descriptions = [c[1]["short_description"] for c in candidates]
                keyword_hits = []
                for c, desc in zip(candidates, descriptions):
                    others = [d for d in descriptions if d != desc]
                    kw = _distinguishing_word(desc, others)
                    if kw and kw in haystack:
                        keyword_hits.append(c)
                if len(keyword_hits) == 1:
                    hit, confidence = keyword_hits[0], "code+keyword"
                else:
                    confidence = "ambiguous"

        if not confidence:
            confidence = "none"

        if hit:
            wi, item = hit
            groups[wi]["matched_tables"].append({
                "table": table,
                "inventory_item": item,
                "confidence": confidence,
            })
            used_inventory_ids.add(id(item))
        else:
            unmatched_tables.append({"table": table, "confidence": confidence})

    # Fallback pass: a table that couldn't be tied to one specific metadata
    # row (e.g. a "combined" sheet that duplicates several already-matched
    # sub-tables) still clearly belongs to the same group as its sibling
    # tables -- either from the same source dataset file, or sharing the
    # same base title in a different uploaded file. Group it there instead
    # of leaving it orphaned -- pushing only ever needed the table itself,
    # not a specific inventory row (that's used for the confidence badge
    # only).
    source_file_groups: Dict[str, set] = {}
    base_title_groups: Dict[str, set] = {}
    for wi, g in enumerate(groups):
        for mt in g["matched_tables"]:
            source_file_groups.setdefault(mt["table"].get("source_file"), set()).add(wi)
            base_title_groups.setdefault(_base_title(mt["table"].get("title", "")), set()).add(wi)

    still_unmatched = []
    for u in unmatched_tables:
        source_file = u["table"].get("source_file")
        candidate_groups = source_file_groups.get(source_file, set())
        if len(candidate_groups) != 1:
            base_title = _base_title(u["table"].get("title", ""))
            title_candidates = base_title_groups.get(base_title, set())
            if len(title_candidates) == 1:
                candidate_groups = title_candidates
        if len(candidate_groups) == 1:
            wi = next(iter(candidate_groups))
            groups[wi]["matched_tables"].append({
                "table": u["table"],
                "inventory_item": None,
                "confidence": "grouped",
            })
        else:
            still_unmatched.append(u)

    # Dataset files that didn't match any metadata workbook still need a
    # metadata card (empty Product / Category / Geography etc.) so the user
    # can fill them in by hand — same as uploading with no metadata files.
    leftover = _groups_without_metadata([u["table"] for u in still_unmatched])
    base = len(groups)
    for g in leftover["groups"]:
        g["workbook_index"] = base + g["workbook_index"]
        groups.append(g)
    unmatched_tables = leftover["unmatched_tables"]

    unmatched_inventory = []
    for mw in metadata_workbooks:
        for item in mw["inventory"]:
            if id(item) not in used_inventory_ids:
                unmatched_inventory.append({"file_name": mw["file_name"], "inventory_item": item})

    return {
        "groups": groups,
        "unmatched_tables": unmatched_tables,
        "unmatched_inventory": unmatched_inventory,
    }
