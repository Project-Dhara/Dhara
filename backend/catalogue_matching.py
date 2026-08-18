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
    """Derives a matchable code from an extracted table's title + sheet
    name. Unlike normalize_inventory_code, ALL parenthetical content in the
    title is stripped -- see module docstring for why."""
    title = str(table.get("title", "") or "").upper()
    title = re.sub(r"TABLE", "", title)
    title = re.sub(r"\([^)]*\)", "", title)
    base = re.sub(r"[^A-Z0-9&]", "", title)
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


def match_tables_to_metadata(extracted_tables: list, metadata_workbooks: list) -> dict:
    """
    extracted_tables: [{id, title, description, sheet, source_file, ...}, ...]
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
                # (e.g. "..._HINDU_...") that the title/description doesn't,
                # since the extractor derives it from sub-header rows deeper
                # in the sheet -- include it in the search text.
                haystack = " ".join([
                    str(table.get("title", "")),
                    str(table.get("description", "")),
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
    # tables from the same source dataset file. Group it there instead of
    # leaving it orphaned -- pushing only ever needed the table itself, not
    # a specific inventory row (that's used for the confidence badge only).
    source_file_groups: Dict[str, set] = {}
    for wi, g in enumerate(groups):
        for mt in g["matched_tables"]:
            source_file_groups.setdefault(mt["table"].get("source_file"), set()).add(wi)

    still_unmatched = []
    for u in unmatched_tables:
        source_file = u["table"].get("source_file")
        candidate_groups = source_file_groups.get(source_file, set())
        if len(candidate_groups) == 1:
            wi = next(iter(candidate_groups))
            groups[wi]["matched_tables"].append({
                "table": u["table"],
                "inventory_item": None,
                "confidence": "grouped",
            })
        else:
            still_unmatched.append(u)
    unmatched_tables = still_unmatched

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
