"""Build a two-pillar LGD hierarchy from ``output/lgd_codes.json``.

Mirrors the Local Government Directory model:

- **revenue**: state → district → sub_district → village (via ``hierarchy_parts``)
- **local_governments.urban**: municipalities / corporations and cantonment boards → wards
  (linked by ``local_body_lgd_code``, not ``hierarchy_parts``)

Writes ``output/hierarchy_lgd.json`` with a ``validation`` section listing linkage problems.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_HIERARCHY_PARTS = {
    "district": frozenset({"state"}),
    "sub_district": frozenset({"state", "district"}),
    "village": frozenset({"state", "district", "sub_district"}),
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

SOURCE_NOISE = frozenset({"source_file", "source_sheet", "s_no"})


def find_lgd_dir() -> Path:
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "output" / "lgd_codes.json").is_file():
        return script_dir
    raise FileNotFoundError(
        f"Expected {script_dir / 'output' / 'lgd_codes.json'}. "
        "Run convert_lgd_codes_to_json.py first."
    )


def norm(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"\s+", " ", str(name).strip().casefold())


def slim(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in SOURCE_NOISE}


def validate_hierarchy_parts(
    entity_type: str,
    record: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, Any] | None:
    expected = EXPECTED_HIERARCHY_PARTS.get(entity_type)
    if expected is None:
        return record.get("hierarchy_parts")

    code = record.get(CODE_FIELD[entity_type])
    parts = record.get("hierarchy_parts")
    if not parts:
        issues.append(
            {
                "type": "missing_hierarchy_parts",
                "entity_type": entity_type,
                "code": code,
            }
        )
        return None

    keys = frozenset(parts)
    if keys != expected:
        issues.append(
            {
                "type": "unexpected_hierarchy_keys",
                "entity_type": entity_type,
                "code": code,
                "expected": sorted(expected),
                "got": sorted(keys),
            }
        )
    return parts


def build_revenue_tree(
    entities: dict[str, list[dict[str, Any]]],
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    states = [slim(r) for r in entities.get("state", [])]
    districts = entities.get("district", [])
    sub_districts = entities.get("sub_district", [])
    villages = entities.get("village", [])

    districts_by_code: dict[str, dict[str, Any]] = {}
    districts_by_state_name: dict[tuple[str, str], dict[str, Any]] = {}

    for raw in districts:
        validate_hierarchy_parts("district", raw, issues)
        rec = slim(raw)
        code = rec["district_lgd_code"]
        districts_by_code[code] = rec
        hp = raw.get("hierarchy_parts") or {}
        districts_by_state_name[(norm(hp.get("state")), norm(rec["district_name_english"]))] = rec

    sub_by_code: dict[str, dict[str, Any]] = {}
    sub_by_triple: dict[tuple[str, str, str], dict[str, Any]] = {}

    for raw in sub_districts:
        validate_hierarchy_parts("sub_district", raw, issues)
        rec = slim(raw)
        code = rec["sub_district_lgd_code"]
        sub_by_code[code] = rec
        hp = raw.get("hierarchy_parts") or {}
        sub_by_triple[
            (
                norm(hp.get("state")),
                norm(hp.get("district")),
                norm(rec["sub_district_name_english"]),
            )
        ] = rec

    villages_by_sub_code: dict[str, list[dict[str, Any]]] = {}

    for raw in villages:
        validate_hierarchy_parts("village", raw, issues)
        rec = slim(raw)
        hp = raw.get("hierarchy_parts") or {}
        key = (
            norm(hp.get("state")),
            norm(hp.get("district")),
            norm(hp.get("sub_district")),
        )
        parent_sub = sub_by_triple.get(key)
        if parent_sub is None:
            issues.append(
                {
                    "type": "unresolved_village_parent",
                    "village_lgd_code": rec.get("village_lgd_code"),
                    "hierarchy_parts": hp,
                }
            )
            continue
        sub_code = parent_sub["sub_district_lgd_code"]
        villages_by_sub_code.setdefault(sub_code, []).append(rec)

    revenue_states: list[dict[str, Any]] = []

    for state_rec in states:
        state_name_norm = norm(state_rec.get("state_name_english"))
        state_node: dict[str, Any] = {
            **state_rec,
            "districts": [],
        }

        for d_rec in districts_by_code.values():
            hp = d_rec.get("hierarchy_parts") or {}
            if norm(hp.get("state")) != state_name_norm:
                continue

            district_node: dict[str, Any] = {
                **d_rec,
                "sub_districts": [],
            }

            for s_rec in sub_by_code.values():
                shp = s_rec.get("hierarchy_parts") or {}
                if norm(shp.get("state")) != state_name_norm:
                    continue
                if norm(shp.get("district")) != norm(d_rec["district_name_english"]):
                    continue

                sub_code = s_rec["sub_district_lgd_code"]
                district_node["sub_districts"].append(
                    {
                        **s_rec,
                        "villages": villages_by_sub_code.get(sub_code, []),
                    }
                )

            district_node["sub_districts"].sort(
                key=lambda row: row.get("sub_district_name_english") or ""
            )
            state_node["districts"].append(district_node)

        state_node["districts"].sort(key=lambda row: row.get("district_name_english") or "")
        revenue_states.append(state_node)

    return revenue_states


def build_local_governments(
    entities: dict[str, list[dict[str, Any]]],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    municipalities: list[dict[str, Any]] = []
    cantonment_boards: list[dict[str, Any]] = []
    bodies_by_code: dict[str, dict[str, Any]] = {}

    for raw in entities.get("local_body", []):
        rec = {**slim(raw), "entity_type": "local_body", "wards": []}
        code = rec["local_body_lgd_code"]
        municipalities.append(rec)
        bodies_by_code[code] = rec

    for raw in entities.get("cantonment_board", []):
        rec = {**slim(raw), "entity_type": "cantonment_board", "wards": []}
        code = rec["local_body_lgd_code"]
        cantonment_boards.append(rec)
        bodies_by_code[code] = rec

    for raw in entities.get("ward", []):
        rec = slim(raw)
        lb_code = rec.get("local_body_lgd_code")
        parent = bodies_by_code.get(lb_code)
        if parent is None:
            issues.append(
                {
                    "type": "ward_unknown_local_body",
                    "ward_code": rec.get("ward_code"),
                    "local_body_lgd_code": lb_code,
                }
            )
            continue
        parent["wards"].append(rec)

    for body in bodies_by_code.values():
        body["wards"].sort(key=lambda row: (row.get("ward_number") or "", row.get("ward_code") or ""))

    municipalities.sort(key=lambda row: row.get("local_body_name_english") or "")
    cantonment_boards.sort(key=lambda row: row.get("local_body_name_english") or "")

    return {
        "urban": {
            "municipalities_and_corporations": municipalities,
            "cantonment_boards": cantonment_boards,
        },
        "rural": {
            "panchayats": [],
            "note": "Not present in current Delhi LGD CODES export.",
        },
    }


def summarize_validation(
    entities: dict[str, list[dict[str, Any]]],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    village_rows = entities.get("village", [])
    with_parts = sum(1 for row in village_rows if row.get("hierarchy_parts"))
    return {
        "issue_count": len(issues),
        "issues": issues,
        "counts": {
            entity: len(entities.get(entity, []))
            for entity in (
                "state",
                "district",
                "sub_district",
                "village",
                "local_body",
                "cantonment_board",
                "ward",
            )
        },
        "villages_with_hierarchy_parts": with_parts,
        "villages_total": len(village_rows),
        "all_villages_have_hierarchy_parts": with_parts == len(village_rows),
    }


def build_hierarchy(payload: dict[str, Any]) -> dict[str, Any]:
    entities = payload["entities"]
    issues: list[dict[str, Any]] = []

    revenue = build_revenue_tree(entities, issues)
    local_governments = build_local_governments(entities, issues)

    return {
        "source": "lgd_codes.json",
        "description": (
            "Local Government Directory hierarchy: revenue admin tree and urban local "
            "governments with wards."
        ),
        "validation": summarize_validation(entities, issues),
        "revenue": revenue,
        "local_governments": local_governments,
    }


def main() -> int:
    lgd_dir = find_lgd_dir()
    input_path = lgd_dir / "output" / "lgd_codes.json"
    output_path = lgd_dir / "output" / "hierarchy_lgd.json"

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    hierarchy = build_hierarchy(payload)

    output_path.write_text(
        json.dumps(hierarchy, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    validation = hierarchy["validation"]
    print(f"Wrote {output_path}")
    print(
        f"Validation: {validation['issue_count']} issue(s); "
        f"villages with hierarchy_parts {validation['villages_with_hierarchy_parts']}/"
        f"{validation['villages_total']}"
    )
    if validation["issue_count"]:
        for item in validation["issues"][:10]:
            print(f"  - {item}")
        if validation["issue_count"] > 10:
            print(f"  ... and {validation['issue_count'] - 10} more")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
