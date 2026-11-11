"""Convert LGD CODES Excel exports into JSON.

The workbooks are Local Government Directory downloads for Delhi: state,
district, sub-district, village, local body, cantonment board, and ward.
Each file has one sheet, a header row, and several empty columns left over
from the website (View Details, View History, View Map). Those empty columns
are left out. Census codes are kept as text so leading zeros stay intact.

Village and sub-district rows store their parents in a Hierarchy string such
as ``Shahdara(Sub-District) / North East(District) / Delhi(State)``. That
string is kept, and split into ``hierarchy_parts``.

Ward workbooks do not name their local body. This script fills
``local_body_name`` and ``local_body_lgd_code`` from the file name, using the
codes in the local-body and cantonment-board exports.

Writes:

- ``output/lgd_codes.json`` — every entity
- ``output/<entity>.json`` — one array per entity
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    import importlib
    import subprocess

    install = [sys.executable, "-m", "pip", "install", "openpyxl"]
    try:
        subprocess.check_call(install)
    except subprocess.CalledProcessError:
        # Debian and Ubuntu mark the system Python as externally managed (PEP 668).
        subprocess.check_call(install + ["--break-system-packages"])
    importlib.invalidate_caches()
    import openpyxl

import openpyxl.reader.excel as excel_reader

# The directory workbooks ship a stylesheet openpyxl rejects. Values do not depend on it.
excel_reader.apply_stylesheet = lambda *args, **kwargs: None

ENTITY_BY_FOLDER = {
    "STATE": "state",
    "DISTRICT": "district",
    "SUB DISTRICT": "sub_district",
    "VILLAGES": "village",
    "LOCAL BODIES": "local_body",
    "CANTONMENT BOARDS": "cantonment_board",
    "WARDS": "ward",
}

# Ward files are split by local body. Codes come from the local-body and cantonment exports.
WARD_LOCAL_BODIES = {
    "MUNICIPAL(EAST)": {
        "local_body_name": "East Delhi Municipal Corporation",
        "local_body_lgd_code": "276400",
    },
    "MUNICIPAL(NORTH)": {
        "local_body_name": "North Delhi Municipal Corporation",
        "local_body_lgd_code": "276401",
    },
    "MUNICIPAL(SOUTH)": {
        "local_body_name": "South Delhi Municipal Corporation",
        "local_body_lgd_code": "276402",
    },
    "CANTONMENT BOARD(DELHI)": {
        "local_body_name": "Delhi Cantonment Board",
        "local_body_lgd_code": "276403",
    },
}

CODE_FIELD = {
    "state": "state_lgd_code",
    "district": "district_lgd_code",
    "sub_district": "sub_district_lgd_code",
    "village": "village_lgd_code",
    "local_body": "local_body_lgd_code",
    "cantonment_board": "local_body_lgd_code",
    "ward": "ward_code",
}

HIERARCHY_PART = re.compile(r"^(.+?)\(([^()]+)\)$")

# Leftover website buttons. They never hold directory data.
UI_COLUMNS = {"view_details", "view_history", "view_map", "gis_map_view"}


def find_project_root() -> Path:
    """Directory that contains the ``LGD CODES`` folder.

    Prefer the script's own directory so the conversion works no matter
    which directory the command is run from, then walk up from the
    current working directory.
    """
    script_dir = Path(__file__).resolve().parent
    starts = [script_dir, Path.cwd().resolve()]
    seen = set()
    for start in starts:
        if start in seen:
            continue
        seen.add(start)
        for candidate in (start, *start.parents):
            if (candidate / "LGD CODES").is_dir():
                return candidate
    raise FileNotFoundError(
        f"Could not find 'LGD CODES' starting from {script_dir} or {Path.cwd().resolve()}"
    )


def column_key(header: str) -> str:
    text = str(header).strip()
    text = text.replace("(In English)", " English")
    text = text.replace("(In Local language)", " Local")
    text = text.replace("Census2011", "Census 2011")
    key = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return {"view_government_order": "government_order"}.get(key, key)


def clean_cell(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def as_code(value):
    value = clean_cell(value)
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return str(value)


def is_code_key(key: str) -> bool:
    return key.endswith("_code") or key.endswith("_number") or key.startswith("census_")


def parse_hierarchy(value):
    if not value:
        return None
    parts = {}
    for piece in str(value).split("/"):
        match = HIERARCHY_PART.match(piece.strip())
        if not match:
            continue
        name, level = match.group(1).strip(), match.group(2).strip()
        level_key = re.sub(r"[^a-z0-9]+", "_", level.lower()).strip("_")
        parts[level_key] = name
    return parts or None


def without_ui_columns(records):
    return [
        {key: value for key, value in record.items() if key not in UI_COLUMNS}
        for record in records
    ]


def align_records(records):
    """Use one set of keys for the entity. Drop a key only when every value is null."""
    if not records:
        return records
    keys = []
    seen = set()
    for record in records:
        for key in record:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    keys = [key for key in keys if any(record.get(key) is not None for record in records)]
    return [{key: record.get(key) for key in keys} for record in records]


def file_label(path: Path) -> str:
    stem = path.stem
    return stem.split(",", 1)[1].strip() if "," in stem else stem


def read_workbook(path: Path):
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        worksheet = workbook[workbook.sheetnames[0]]
        rows = list(worksheet.iter_rows(values_only=True))
        sheet_name = worksheet.title
    finally:
        workbook.close()

    if not rows:
        return sheet_name, []

    headers = [
        column_key(cell) if cell is not None else f"column_{index}"
        for index, cell in enumerate(rows[0])
    ]
    records = []
    for raw in rows[1:]:
        if raw is None or all(clean_cell(cell) is None for cell in raw):
            continue
        record = {}
        for key, cell in zip(headers, raw):
            record[key] = as_code(cell) if is_code_key(key) else clean_cell(cell)
        records.append(record)
    return sheet_name, without_ui_columns(records)


def load_all(source_dir: Path):
    grouped = {entity: [] for entity in ENTITY_BY_FOLDER.values()}
    files = sorted(path for path in source_dir.rglob("*.xlsx") if not path.name.startswith("."))
    if not files:
        raise FileNotFoundError(f"No .xlsx files under {source_dir}")

    for path in files:
        folder = path.parent.name
        entity = ENTITY_BY_FOLDER.get(folder)
        if entity is None:
            entity = re.sub(r"[^a-z0-9]+", "_", folder.lower()).strip("_")
            grouped.setdefault(entity, [])
            print(f"Unknown folder '{folder}', stored as '{entity}'")

        sheet_name, records = read_workbook(path)
        relative = path.relative_to(source_dir).as_posix()
        label = file_label(path)
        for record in records:
            item = {
                "entity_type": entity,
                "source_file": relative,
                "source_sheet": sheet_name,
            }
            if entity == "ward":
                parent = WARD_LOCAL_BODIES.get(label)
                if parent is None:
                    raise KeyError(f"No local body mapping for ward file label '{label}'")
                item.update(parent)
            elif entity in {"local_body", "cantonment_board"}:
                item["list_name"] = label
            item.update(record)
            if "hierarchy" in item:
                item["hierarchy_parts"] = parse_hierarchy(item.get("hierarchy"))
            grouped[entity].append(item)
    return {entity: align_records(records) for entity, records in grouped.items()}


def check_records(records_by_entity):
    problems = []
    for entity, records in records_by_entity.items():
        code_field = CODE_FIELD.get(entity)
        if code_field is None:
            problems.append(f"{entity}: no code field configured")
            continue
        missing = [record["source_file"] for record in records if not record.get(code_field)]
        if missing:
            problems.append(f"{entity}: {len(missing)} records missing {code_field}")
        if entity in {"district", "sub_district", "village"}:
            unparsed = [
                record["hierarchy"]
                for record in records
                if record.get("hierarchy") and not record.get("hierarchy_parts")
            ]
            if unparsed:
                problems.append(f"{entity}: {len(unparsed)} hierarchy values did not parse")

    if problems:
        raise RuntimeError("\n".join(problems))


def write_json(output_dir: Path, records_by_entity):
    output_dir.mkdir(parents=True, exist_ok=True)

    combined = {
        "source": "LGD CODES",
        "description": "Local Government Directory records converted from the Excel exports.",
        "counts": {entity: len(records) for entity, records in records_by_entity.items()},
        "entities": records_by_entity,
    }
    combined["counts"]["total"] = sum(combined["counts"].values())

    combined_path = output_dir / "lgd_codes.json"
    combined_path.write_text(
        json.dumps(combined, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {combined_path} ({combined['counts']['total']} records)")

    for entity, records in records_by_entity.items():
        path = output_dir / f"{entity}.json"
        path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {path} ({len(records)} records)")


def main():
    project_root = find_project_root()
    source_dir = project_root / "LGD CODES"
    output_dir = project_root / "output"

    print(f"Source: {source_dir}")
    print(f"Output: {output_dir}")

    records_by_entity = load_all(source_dir)
    for entity, records in records_by_entity.items():
        print(f"{entity:20} {len(records):5} records")
    print(f"{'total':20} {sum(len(records) for records in records_by_entity.values()):5} records")

    check_records(records_by_entity)
    samples = {entity: records[0] for entity, records in records_by_entity.items() if records}
    print(json.dumps(samples, indent=2, ensure_ascii=False))
    print("Checks passed")

    write_json(output_dir, records_by_entity)


if __name__ == "__main__":
    main()
