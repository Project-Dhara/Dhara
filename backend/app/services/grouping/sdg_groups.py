"""SDG goal detection and SDG-based table grouping."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Optional

from app.services.grouping.embeddings import (
    _cluster_by_distance,
    _groups_from_clusters,
)

_SDG_GOAL_RE = re.compile(r"\bSDG\s*(\d{1,2})\b", re.IGNORECASE)

_SDG_INDICATORS_RE = re.compile(
    r"INDICATORS?\s+OF\s+SDG\s*(\d{1,2})\b", re.IGNORECASE
)

_SDG_INDEX_RE = re.compile(r"\bSDG\s*(\d{1,2})\s*Index\b", re.IGNORECASE)

_TABLE_MAJOR_RE = re.compile(r"\bTABLE\s+(\d{1,2})\.\d+", re.IGNORECASE)

_SDA_TITLE_HINT_RE = re.compile(
    r"\b(SDG|INDICATOR|STATES?\s*/?\s*UTs?)\b", re.IGNORECASE
)

def _valid_sdg_goal(n: int) -> Optional[int]:
    return n if 1 <= n <= 17 else None

def detect_sdg_goal(table: dict) -> Optional[int]:
    """
    Extract SDG goal 1–17 from title / columns / classification when present.
    Returns None if the table does not look goal-tagged.
    """
    title = str(table.get("title") or "")
    subject = str(table.get("subject") or "")
    domain = str(table.get("domain") or "")
    col_names: list[str] = []
    for col in table.get("columns") or []:
        if isinstance(col, dict):
            col_names.append(str(col.get("name") or ""))
        else:
            col_names.append(str(col))
    cols_blob = " | ".join(col_names)

    m = _SDG_INDICATORS_RE.search(title)
    if m:
        return _valid_sdg_goal(int(m.group(1)))

    m = _SDG_INDEX_RE.search(title)
    if m:
        return _valid_sdg_goal(int(m.group(1)))

    m = _SDG_GOAL_RE.search(title)
    if m:
        return _valid_sdg_goal(int(m.group(1)))

    # SDA India style: TABLE 3.1 + States/UTs / indicator wording → goal 3
    m = _TABLE_MAJOR_RE.search(title)
    if m and _SDA_TITLE_HINT_RE.search(title):
        return _valid_sdg_goal(int(m.group(1)))

    m = _SDG_INDEX_RE.search(cols_blob)
    if m:
        return _valid_sdg_goal(int(m.group(1)))

    # Avoid weak "SDG" mentions in long column blobs that list many goals;
    # only accept a single clear Index Score column match (above) or metadata.
    for field in (subject, domain):
        m = _SDG_GOAL_RE.search(field)
        if m:
            return _valid_sdg_goal(int(m.group(1)))

    return None

def corpus_looks_like_sdg_indicator_tables(tables: list[dict]) -> bool:
    """
    True when enough tables carry a detectable SDG goal that SDG-wise
    buckets are safer than embedding clusters.
    """
    if len(tables) < 2:
        return False
    tagged_goals = [detect_sdg_goal(t) for t in tables]
    tagged = [g for g in tagged_goals if g is not None]
    if len(tagged) < 2:
        return False
    ratio = len(tagged) / len(tables)
    distinct = set(tagged)
    # Majority tagged, or several goals with a solid tagged share.
    if ratio >= 0.5:
        return True
    if len(distinct) >= 2 and ratio >= 0.35:
        return True
    return False

def _propose_sdg_groups(
    tables: list[dict],
    embeddings: dict[str, list[float]],
    threshold: float,
) -> list[dict]:
    """Bucket by SDG goal; leftover tables still use embedding clusters."""
    by_goal: dict[int, list[dict]] = defaultdict(list)
    leftovers: list[dict] = []
    for t in tables:
        goal = detect_sdg_goal(t)
        if goal is not None:
            by_goal[goal].append(t)
        else:
            leftovers.append(t)

    groups: list[dict] = []
    for goal in sorted(by_goal.keys()):
        members = by_goal[goal]
        groups.append(
            {
                "name": f"SDG {goal}",
                "tables": members,
                "table_pks": [m["id"] for m in members],
            }
        )

    if leftovers:
        by_id = {t["id"]: t for t in leftovers}
        clusters = _cluster_by_distance(
            [t["id"] for t in leftovers],
            embeddings,
            threshold,
        )
        groups.extend(_groups_from_clusters(clusters, by_id, name_start_index=len(groups)))

    return groups

__all__ = [
    "corpus_looks_like_sdg_indicator_tables",
    "detect_sdg_goal",
]
