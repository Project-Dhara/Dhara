"""Read-only reference code lists bundled with the backend (shown in Settings).

NCO 2015 lives in Postgres as a selectable classification standard. The LGD
(Local Government Directory) codes are different: matching reads the bundled
``hierarchy_lgd.json`` directly and needs no selection, so they are reported
here as pre-configured, read-only entries and never touch ``classification_standards``.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.services.classification.lgd_directory import find_hierarchy_path, humanize

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "value": None}


def _plural(label: str, count: int) -> str:
    label = label.lower()
    if count == 1:
        return f"{count} {label}"
    if label.endswith("y") and not label.endswith(("ay", "ey", "oy", "uy")):
        return f"{count} {label[:-1]}ies"
    return f"{count} {label}s"


def _count_entities(root: Any) -> dict[str, int]:
    """Count nodes by ``entity_type`` in first-seen order (state, district, ...)."""
    counts: dict[str, int] = {}
    stack = [root]
    order: list[Any] = []
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            order.append(node)
            stack.extend(reversed([v for v in node.values() if isinstance(v, (dict, list))]))
        elif isinstance(node, list):
            stack.extend(reversed(node))
    for node in order:
        entity_type = node.get("entity_type")
        if isinstance(entity_type, str) and entity_type:
            counts[entity_type] = counts.get(entity_type, 0) + 1
    return counts


def _load_lgd_reference(path: Path) -> dict | None:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return None
    counts = _count_entities(data)
    total = sum(counts.values())
    if total <= 0:
        return None
    return {
        "id": "lgd",
        "kind": "lgd",
        "name": "LGD codes",
        "description": "Pre-configured from backend",
        "original_filename": None,
        "row_count": total,
        "uploaded_by": "system",
        "summary": " · ".join(_plural(humanize(t), n) for t, n in counts.items()),
        "breakdown": counts,
    }


def list_reference_standards() -> list[dict]:
    """Bundled read-only code lists (currently the LGD hierarchy). Empty if the data file is absent."""
    try:
        path = find_hierarchy_path()
    except FileNotFoundError:
        return []
    try:
        key = (str(path), path.stat().st_mtime_ns)
        with _cache_lock:
            if _cache["key"] == key:
                return list(_cache["value"])
        entry = _load_lgd_reference(path)
        value = [entry] if entry else []
        with _cache_lock:
            _cache["key"], _cache["value"] = key, value
        return list(value)
    except Exception:  # never break the Settings list because reference data is unreadable
        logger.exception("could not read bundled LGD reference data")
        return []
