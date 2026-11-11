"""Build an NCO-2015 hierarchy JSON from ``nco_2015_concordance.csv``.

Levels (ISCO-aligned NCO-2015):

- division → subdivision → group → family → occupation

Writes ``output/hierarchy_nco.json`` with a ``validation`` section of counts
and any orphan / blank-code issues. Field names match the backend
``nco_2015_codes`` shape so parsers can reuse the same keys.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any


LEVELS = (
    ("division", "Division_Code", "Division_Title", "subdivisions"),
    ("subdivision", "SubDivision_Code", "SubDivision_Title", "groups"),
    ("group", "Group_Code", "Group_Title", "families"),
    ("family", "Family_Code", "Family_Title", "occupations"),
)


def find_nco_dir() -> Path:
    script_dir = Path(__file__).resolve().parent
    csv_path = script_dir / "nco_2015_concordance.csv"
    if csv_path.is_file():
        return script_dir
    raise FileNotFoundError(
        f"Expected {csv_path}. Place nco_2015_concordance.csv next to this script."
    )


def _code_key(code: str) -> tuple:
    """Sort numeric-looking codes numerically; fall back to string order."""
    text = str(code).strip()
    try:
        return (0, float(text))
    except ValueError:
        return (1, text)


def _occupation_sort_key(occ: dict[str, Any]) -> tuple:
    return _code_key(occ.get("nco_code") or "")


def build_tree(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Nested OrderedDicts keyed by code keep first-seen titles and insert order.
    root: OrderedDict[str, dict[str, Any]] = OrderedDict()
    issues: list[dict[str, Any]] = []
    seen_occupations: set[str] = set()

    for index, row in enumerate(rows, start=2):  # header is line 1
        path: list[tuple[str, str, str]] = []
        skip = False
        for entity_type, code_col, title_col, _child_key in LEVELS:
            code = (row.get(code_col) or "").strip()
            title = (row.get(title_col) or "").strip()
            if not code:
                issues.append(
                    {
                        "type": "blank_code",
                        "entity_type": entity_type,
                        "row": index,
                        "nco_code": (row.get("NCO_2015_Code") or "").strip() or None,
                    }
                )
                skip = True
                break
            path.append((entity_type, code, title))

        if skip:
            continue

        nco_code = (row.get("NCO_2015_Code") or "").strip()
        occupation_title = (row.get("Occupation_Title") or "").strip()
        qp_nos = (row.get("QP_NOS_Reference") or "").strip() or None

        if not nco_code:
            issues.append({"type": "blank_nco_code", "row": index})
            continue
        if nco_code in seen_occupations:
            issues.append(
                {
                    "type": "duplicate_nco_code",
                    "row": index,
                    "nco_code": nco_code,
                }
            )
            continue
        seen_occupations.add(nco_code)

        # Walk / create Division → SubDivision → Group → Family
        cursor_map = root
        leaf_node: dict[str, Any] | None = None
        for depth, (entity_type, code, title) in enumerate(path):
            child_key = LEVELS[depth][3]
            if code not in cursor_map:
                node: dict[str, Any] = {
                    "entity_type": entity_type,
                    f"{entity_type}_code": code,
                    f"{entity_type}_title": title,
                }
                if child_key == "occupations":
                    node[child_key] = []
                else:
                    node[child_key] = OrderedDict()
                cursor_map[code] = node
            else:
                node = cursor_map[code]
                existing_title = node.get(f"{entity_type}_title") or ""
                if title and existing_title and title != existing_title:
                    issues.append(
                        {
                            "type": "title_mismatch",
                            "entity_type": entity_type,
                            "code": code,
                            "existing": existing_title,
                            "got": title,
                            "row": index,
                        }
                    )

            if child_key == "occupations":
                leaf_node = node
            else:
                cursor_map = node[child_key]

        assert leaf_node is not None
        leaf_node["occupations"].append(
            {
                "entity_type": "occupation",
                "nco_code": nco_code,
                "occupation_title": occupation_title,
                "qp_nos_reference": qp_nos,
            }
        )

    divisions = _materialize(root)
    counts = _count_nodes(divisions)
    validation = {
        "issue_count": len(issues),
        "issues": issues,
        "counts": counts,
        "occupation_codes_unique": len(seen_occupations),
    }
    return divisions, validation


def _materialize(node_map: OrderedDict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn OrderedDict children into sorted lists recursively."""
    items = sorted(node_map.values(), key=lambda n: _code_key(next(
        v for k, v in n.items() if k.endswith("_code")
    )))
    out: list[dict[str, Any]] = []
    for node in items:
        materialized = dict(node)
        for child_key in ("subdivisions", "groups", "families"):
            children = materialized.get(child_key)
            if isinstance(children, OrderedDict):
                materialized[child_key] = _materialize(children)
        occupations = materialized.get("occupations")
        if isinstance(occupations, list):
            materialized["occupations"] = sorted(occupations, key=_occupation_sort_key)
        out.append(materialized)
    return out


def _count_nodes(divisions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "division": 0,
        "subdivision": 0,
        "group": 0,
        "family": 0,
        "occupation": 0,
    }
    for division in divisions:
        counts["division"] += 1
        for subdivision in division.get("subdivisions", []):
            counts["subdivision"] += 1
            for group in subdivision.get("groups", []):
                counts["group"] += 1
                for family in group.get("families", []):
                    counts["family"] += 1
                    counts["occupation"] += len(family.get("occupations", []))
    return counts


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        expected = {
            "Division_Code",
            "Division_Title",
            "SubDivision_Code",
            "SubDivision_Title",
            "Group_Code",
            "Group_Title",
            "Family_Code",
            "Family_Title",
            "NCO_2015_Code",
            "Occupation_Title",
            "QP_NOS_Reference",
        }
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path} has no header row")
        missing = expected - set(reader.fieldnames)
        if missing:
            raise ValueError(f"{csv_path} missing columns: {sorted(missing)}")
        return list(reader)


def main() -> int:
    nco_dir = find_nco_dir()
    csv_path = nco_dir / "nco_2015_concordance.csv"
    out_dir = nco_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "hierarchy_nco.json"

    rows = load_rows(csv_path)
    divisions, validation = build_tree(rows)

    payload = {
        "source": csv_path.name,
        "description": (
            "NCO-2015 hierarchy: division → subdivision → group → family → occupation."
        ),
        "validation": validation,
        "divisions": divisions,
    }

    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    counts = validation["counts"]
    print(
        f"Wrote {out_path} — "
        f"{counts['division']} divisions, "
        f"{counts['subdivision']} subdivisions, "
        f"{counts['group']} groups, "
        f"{counts['family']} families, "
        f"{counts['occupation']} occupations "
        f"({validation['issue_count']} issues)."
    )
    return 0 if validation["issue_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
