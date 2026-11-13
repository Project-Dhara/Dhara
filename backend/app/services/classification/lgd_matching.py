"""Match classification values to LGD codes using the explorer Directory.search.

Same cascade as ``LGD and NCO/lgd_explorer.py`` / ``lgd_directory.Directory.search``:
code → exact name → normalized name → partial name → fuzzy name → similar name.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from app.services.classification.lgd_directory import Directory

_AUTO_FILL_KINDS = frozenset(
    {
        "code",
        "exact name",
        "normalized name",
        "partial name",
    }
)
_REVIEW_KINDS = frozenset({"fuzzy name", "similar name"})

_directory: Optional[Directory] = None
_directory_lock = threading.Lock()
_directory_error: Optional[str] = None


def reset_lgd_directory_cache() -> None:
    """Test helper — drop the process-wide index."""
    global _directory, _directory_error
    with _directory_lock:
        _directory = None
        _directory_error = None


def get_lgd_directory() -> Directory:
    """Lazy-load and cache the hierarchy index (preload on first use)."""
    global _directory, _directory_error
    with _directory_lock:
        if _directory is not None:
            return _directory
        if _directory_error:
            raise FileNotFoundError(_directory_error)
        try:
            _directory = Directory.load()
        except FileNotFoundError as exc:
            _directory_error = str(exc)
            raise
        return _directory


def _candidate_from_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "code": hit.get("lgd_code"),
        "lgd_code": hit.get("lgd_code"),
        "title": hit.get("name_english"),
        "name_english": hit.get("name_english"),
        "entity_type": hit.get("entity_type"),
        "hierarchy": hit.get("hierarchy"),
        "hierarchy_parts": hit.get("hierarchy_parts"),
        "path": hit.get("path") or [],
    }


def _unique_code_candidates(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dedupe search hits by LGD code (same place name, multiple directory codes)."""
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for hit in matches:
        code = str(hit.get("lgd_code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(_candidate_from_hit(hit))
    return out


def _steward_match(search_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    matches = search_result.get("matches") or []
    if not matches:
        return None
    top = matches[0]
    kind = search_result.get("kind")
    code = top.get("lgd_code")
    title = top.get("name_english")
    candidates = _unique_code_candidates(matches)
    ambiguous = len(candidates) > 1
    # Single unique code keeps prior auto-fill rules; multiple codes need a pick.
    auto_fill = (not ambiguous) and kind in _AUTO_FILL_KINDS and bool(code)
    needs_review = ambiguous or kind in _REVIEW_KINDS or not auto_fill
    if ambiguous:
        confidence = "medium"
    elif auto_fill:
        confidence = "high"
    elif kind in _REVIEW_KINDS:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "code": code,
        "title": title,
        "level": top.get("entity_type"),
        "entity_type": top.get("entity_type"),
        "lgd_code": code,
        "name_english": title,
        "aliases": top.get("aliases") or [],
        "hierarchy": top.get("hierarchy"),
        "hierarchy_parts": top.get("hierarchy_parts"),
        "kind": kind,
        "path": top.get("path") or [],
        "confidence": confidence,
        "auto_fill": auto_fill,
        "needs_manual_review": needs_review,
        "ambiguous": ambiguous,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "source": "lgd",
        # Keep alternates for older clients; full list is ``candidates``.
        "alternates": candidates[1:6],
    }


def match_lgd_values(values: List[Any]) -> Dict[str, Dict[str, Any]]:
    """Return ``{ input_value: steward_match }`` using explorer search per value."""
    directory = get_lgd_directory()
    out: Dict[str, Dict[str, Any]] = {}
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw).strip() if raw is not None else ""
        if not value or value in seen:
            continue
        seen.add(value)
        packed = directory.search(value)
        steward = _steward_match(packed)
        if steward:
            out[value] = steward
    return out
