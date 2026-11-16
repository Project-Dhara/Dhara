"""Curated LGD steward aliases not present in the official dump.

These are common short forms used in government tables. Each alias attaches to
one or more directory records by ``name_english`` match; multi-record aliases
surface as ambiguous candidates so the steward can pick (e.g. MCD → East /
North / South Delhi Municipal Corporation).
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, List, Sequence, Tuple

NamePredicate = Callable[[str], bool]


def _fold(name: str) -> str:
    """Same folding as ``lgd_directory.normalize_name`` (avoid circular import)."""
    return re.sub(r"\s+", " ", str(name or "").strip().casefold())


def _exact(*targets: str) -> NamePredicate:
    folded = {_fold(t) for t in targets if t}
    return lambda name: _fold(name) in folded


def _contains(*needles: str) -> NamePredicate:
    folded = [_fold(n) for n in needles if n]
    return lambda name: any(n in _fold(name) for n in folded)


# (alias display text, which official names it should attach to)
EXTRA_LGD_ALIAS_RULES: Sequence[Tuple[str, NamePredicate]] = (
    # New Delhi Municipal Council
    ("NDMC", _exact("New Delhi Municipal Council")),
    # Cantonment short forms → Sub-District + Cantonment Board (user picks)
    ("Delhi cantt", _contains("Delhi Cantonment")),
    ("Delhi cant", _contains("Delhi Cantonment")),
    # Pre-trifurcation MCD wording → East / North / South (user picks)
    (
        "MCD",
        _exact(
            "East Delhi Municipal Corporation",
            "North Delhi Municipal Corporation",
            "South Delhi Municipal Corporation",
        ),
    ),
    (
        "Municipal Corporation of Delhi",
        _exact(
            "East Delhi Municipal Corporation",
            "North Delhi Municipal Corporation",
            "South Delhi Municipal Corporation",
        ),
    ),
)


def aliases_for_name(name_english: str) -> List[str]:
    """Return curated alias strings that should index onto this official name."""
    out: List[str] = []
    seen: set[str] = set()
    for alias, matches in EXTRA_LGD_ALIAS_RULES:
        if not matches(name_english or ""):
            continue
        folded = _fold(alias)
        if not folded or folded in seen:
            continue
        seen.add(folded)
        out.append(alias)
    return out


def iter_extra_alias_attachments(
    entities: Iterable[dict],
) -> List[Tuple[dict, str]]:
    """Pairs of (record, alias_text) to index after the hierarchy walk."""
    pairs: List[Tuple[dict, str]] = []
    for record in entities:
        name = str(record.get("name_english") or "")
        for alias in aliases_for_name(name):
            pairs.append((record, alias))
    return pairs


__all__ = [
    "EXTRA_LGD_ALIAS_RULES",
    "aliases_for_name",
    "iter_extra_alias_attachments",
]
