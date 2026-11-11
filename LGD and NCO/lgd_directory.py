"""Shared LGD hierarchy index and search."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

TOKEN_RE = re.compile(r"[0-9a-z]+")
PALETTE = [
    "#e7d3b0",
    "#7eb6d6",
    "#e9c46a",
    "#f4a261",
    "#2a9d8f",
    "#e76f51",
    "#cdb4db",
    "#90be6d",
    "#f4f1de",
    "#ffb703",
]
GROUP_COLOR = "#c4b6a0"


def find_hierarchy_path() -> Path:
    here = Path(__file__).resolve().parent
    candidates = [
        here / "output" / "hierarchy_lgd.json",
        Path.cwd() / "output" / "hierarchy_lgd.json",
        Path.cwd() / "LGD" / "output" / "hierarchy_lgd.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Could not find hierarchy_lgd.json. Run from repo root (Dhara) or LGD/."
    )


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().casefold())


def tokenize(name: str) -> tuple[str, ...]:
    return tuple(TOKEN_RE.findall(normalize_name(name)))


def compact_name(name: str) -> str:
    return "".join(tokenize(name))


def scalar_text(value) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def humanize(label: str) -> str:
    parts = [part.capitalize() for part in str(label).split("_") if part]
    return " ".join("and" if part == "And" else part for part in parts)


def display_name(node: dict) -> str:
    entity_type = str(node.get("entity_type") or "")
    named = []
    for key, value in node.items():
        text = scalar_text(value)
        if text and "name" in key:
            named.append((key, text))
    preferred = [text for key, text in named if entity_type and entity_type in key and "english" in key]
    if not preferred:
        preferred = [text for key, text in named if entity_type and entity_type in key]
    if not preferred:
        preferred = [text for key, text in named if "english" in key]
    if not preferred and named:
        preferred = [named[0][1]]
    return preferred[0] if preferred else entity_type


def ancestor_names(ancestors: list[dict]) -> set[str]:
    names = set()
    for ancestor in ancestors:
        for key, value in ancestor.items():
            text = scalar_text(value)
            if text and "name" in key:
                names.add(normalize_name(text))
    return names


def own_alias_texts(node: dict, ancestors: list[dict]) -> list[str]:
    entity_type = str(node.get("entity_type") or "")
    taken = ancestor_names(ancestors)
    texts = []
    seen = set()
    for key, value in node.items():
        text = scalar_text(value)
        if not text or ("name" not in key and "number" not in key):
            continue
        if entity_type not in key and normalize_name(text) in taken:
            continue
        folded = normalize_name(text)
        if folded in seen:
            continue
        seen.add(folded)
        texts.append(text)
    return texts


def own_codes(node: dict, ancestors: list[dict]) -> list[tuple[str, str]]:
    inherited: dict[str, set[str]] = {}
    for ancestor in ancestors:
        for key, value in ancestor.items():
            text = scalar_text(value)
            if text and key.endswith("_code"):
                inherited.setdefault(key, set()).add(text)
    pairs = []
    for key, value in node.items():
        text = scalar_text(value)
        if not text or not key.endswith("_code"):
            continue
        if text in inherited.get(key, set()):
            continue
        pairs.append((key, text))
    return pairs


def primary_code(pairs: list[tuple[str, str]], entity_type: str) -> str | None:
    if not pairs:
        return None
    chosen = sorted(
        pairs,
        key=lambda item: (
            not ("lgd" in item[0] and entity_type in item[0]),
            entity_type not in item[0],
            "lgd" not in item[0],
            item[0],
        ),
    )
    return chosen[0][1]


def contains_entity(node) -> bool:
    if isinstance(node, dict):
        if isinstance(node.get("entity_type"), str):
            return True
        return any(contains_entity(value) for value in node.values() if isinstance(value, (dict, list)))
    if isinstance(node, list):
        return any(contains_entity(item) for item in node)
    return False


def detect_hierarchy_separator(root) -> str:
    def walk_for_separator(node):
        if isinstance(node, dict):
            hierarchy = node.get("hierarchy")
            if isinstance(hierarchy, str):
                match = re.search(r"\)([^0-9A-Za-z]+)(?=\S)", hierarchy)
                if match:
                    return match.group(1)
            for value in node.values():
                found = walk_for_separator(value)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk_for_separator(item)
                if found:
                    return found
        return None

    return walk_for_separator(root) or " "


def levenshtein(left: str, right: str, budget: int) -> int | None:
    if left == right:
        return 0
    if budget <= 0 or abs(len(left) - len(right)) > budget:
        return None
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i]
        row_min = i
        for j, right_char in enumerate(right, 1):
            value = min(
                current[j - 1] + 1,
                previous[j] + 1,
                previous[j - 1] + (left_char != right_char),
            )
            current.append(value)
            if value < row_min:
                row_min = value
        if row_min > budget:
            return None
        previous = current
    distance = previous[-1]
    return distance if distance <= budget else None


def add_to_bucket(index: dict, key: str, record: dict) -> None:
    if not key:
        return
    bucket = index.setdefault(key, [])
    if all(existing is not record for existing in bucket):
        bucket.append(record)


class Directory:
    def __init__(self, data: dict, source: Path):
        self.data = data
        self.source = source
        self.lookup: dict[str, list[dict]] = {}
        self.compact_lookup: dict[str, list[dict]] = {}
        self.code_lookup: dict[str, list[dict]] = {}
        self.token_index: dict[str, list[dict]] = {}
        self.record_by_id: dict[int, dict] = {}
        self.name_token_count: dict[int, int] = {}
        self.entities: list[dict] = []
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.parent_of: dict[str, str | None] = {}
        self.hierarchy_separator = detect_hierarchy_separator(data)
        self._walk(data, None, [])
        self._layout()
        self.legend = self._legend()

    @classmethod
    def load(cls) -> Directory:
        path = find_hierarchy_path()
        with path.open(encoding="utf-8") as handle:
            return cls(json.load(handle), path)

    def _add_node(self, node: dict, parent_id: str | None) -> None:
        node["parent_id"] = parent_id
        self.nodes.append(node)
        self.parent_of[node["id"]] = parent_id
        if parent_id:
            self.edges.append({"from": parent_id, "to": node["id"]})

    def _index_entity(self, node: dict, ancestors: list[dict], parent_id: str | None) -> dict:
        entity_type = str(node["entity_type"])
        display = display_name(node)
        alias_texts = own_alias_texts(node, ancestors)
        if normalize_name(display) not in {normalize_name(text) for text in alias_texts}:
            alias_texts.insert(0, display)

        code_pairs = own_codes(node, ancestors)
        code = primary_code(code_pairs, entity_type)
        source_hierarchy = node.get("hierarchy")
        if isinstance(source_hierarchy, str) and source_hierarchy.strip():
            hierarchy = source_hierarchy.strip()
        else:
            labels = [
                f"{display_name(ancestor)}({humanize(ancestor['entity_type'])})"
                for ancestor in reversed(ancestors)
            ]
            hierarchy = self.hierarchy_separator.join(labels) if labels else None

        source_parts = node.get("hierarchy_parts")
        if isinstance(source_parts, dict) and source_parts:
            hierarchy_parts = dict(source_parts)
        elif ancestors:
            hierarchy_parts = {
                str(ancestor["entity_type"]): display_name(ancestor) for ancestor in ancestors
            }
        else:
            hierarchy_parts = None

        folded_display = normalize_name(display)
        aliases = [text for text in alias_texts if normalize_name(text) != folded_display]
        node_id = f"{entity_type}:{code}" if code else f"{entity_type}:{len(self.entities)}"
        if node_id in self.parent_of:
            node_id = f"{node_id}:{len(self.entities)}"

        record = {
            "node_id": node_id,
            "entity_type": entity_type,
            "lgd_code": code,
            "name_english": display,
            "aliases": aliases,
            "hierarchy": hierarchy,
            "hierarchy_parts": hierarchy_parts,
        }
        for text in alias_texts:
            add_to_bucket(self.lookup, normalize_name(text), record)
            add_to_bucket(self.compact_lookup, compact_name(text), record)
            for token in tokenize(text):
                add_to_bucket(self.token_index, token, record)
        for _, coded in code_pairs:
            add_to_bucket(self.code_lookup, coded, record)
            add_to_bucket(self.code_lookup, coded.casefold(), record)

        self.record_by_id[id(record)] = record
        self.name_token_count[id(record)] = len(tokenize(display))
        self.entities.append(record)
        self._add_node(
            {
                "id": node_id,
                "label": display,
                "kind": "entity",
                "entity_type": entity_type,
                "lgd_code": code,
                "hierarchy": hierarchy,
            },
            parent_id,
        )
        return record

    def _walk(self, node, parent_id: str | None, ancestors: list[dict]) -> None:
        if isinstance(node, dict) and isinstance(node.get("entity_type"), str):
            record = self._index_entity(node, ancestors, parent_id)
            next_ancestors = ancestors + [node]
            for value in node.values():
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and isinstance(item.get("entity_type"), str):
                            self._walk(item, record["node_id"], next_ancestors)
            return
        if isinstance(node, list):
            for item in node:
                self._walk(item, parent_id, ancestors)
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(value, (dict, list)) or not contains_entity(value):
                    continue
                group_id = f"group:{key}:{len(self.nodes)}"
                self._add_node(
                    {
                        "id": group_id,
                        "label": humanize(key),
                        "kind": "group",
                        "entity_type": None,
                        "lgd_code": None,
                        "hierarchy": None,
                    },
                    parent_id,
                )
                self._walk(value, group_id, ancestors)

    def _layout(self) -> None:
        children: dict[str, list[str]] = defaultdict(list)
        seen_child = set()
        for edge in self.edges:
            children[edge["from"]].append(edge["to"])
            seen_child.add(edge["to"])
        by_id = {node["id"]: node for node in self.nodes}

        def place(node_id: str, depth: int) -> None:
            node = by_id[node_id]
            node["depth"] = depth
            for child in children.get(node_id, []):
                place(child, depth + 1)

        for node in self.nodes:
            if node["id"] not in seen_child:
                place(node["id"], 0)

    def _legend(self) -> list[dict]:
        counts = Counter(record["entity_type"] for record in self.entities)
        legend = []
        for index, (entity_type, count) in enumerate(counts.most_common()):
            color = PALETTE[index % len(PALETTE)]
            legend.append(
                {
                    "entity_type": entity_type,
                    "label": humanize(entity_type),
                    "color": color,
                    "count": count,
                }
            )
        colors = {item["entity_type"]: item["color"] for item in legend}
        for node in self.nodes:
            node["color"] = colors.get(node.get("entity_type") or "", GROUP_COLOR)
        return legend

    def path(self, node_id: str) -> list[str]:
        chain = []
        seen = set()
        while node_id and node_id not in seen:
            seen.add(node_id)
            chain.append(node_id)
            node_id = self.parent_of.get(node_id)
        chain.reverse()
        return chain

    def graph_payload(self) -> dict:
        counts = Counter(record["entity_type"] for record in self.entities)
        return {
            "source": str(self.source),
            "description": self.data.get("description"),
            "entity_count": len(self.entities),
            "counts": dict(counts),
            "legend": self.legend,
            "nodes": self.nodes,
            "edges": self.edges,
        }

    def _pack(self, query: str, matches: list[dict], kind: str, cap: int) -> dict:
        shown = []
        for record in matches[:cap]:
            shown.append(
                {
                    "node_id": record["node_id"],
                    "entity_type": record["entity_type"],
                    "lgd_code": record["lgd_code"],
                    "name_english": record["name_english"],
                    "aliases": record["aliases"],
                    "hierarchy": record["hierarchy"],
                    "hierarchy_parts": record["hierarchy_parts"],
                    "path": self.path(record["node_id"]),
                }
            )
        return {"query": query, "kind": kind, "total": len(matches), "matches": shown}

    def _costs_for_token(self, query_token: str, fuzzy: bool) -> dict[int, int]:
        options: dict[int, int] = {}

        def offer(record: dict, cost: int) -> None:
            record_id = id(record)
            current = options.get(record_id)
            if current is None or cost < current:
                options[record_id] = cost

        for record in self.token_index.get(query_token, []):
            offer(record, 0)
        for token, records in self.token_index.items():
            if token == query_token or not token.startswith(query_token):
                continue
            gap = len(token) - len(query_token)
            for record in records:
                offer(record, gap)
        if fuzzy:
            budget = len(query_token) // 4
            if budget:
                for token, records in self.token_index.items():
                    if token.startswith(query_token):
                        continue
                    distance = levenshtein(query_token, token, budget)
                    if not distance:
                        continue
                    for record in records:
                        offer(record, distance)
        return options

    def _match_tokens(self, query_tokens: tuple[str, ...], fuzzy: bool) -> list[dict]:
        combined: dict[int, int] | None = None
        for query_token in query_tokens:
            options = self._costs_for_token(query_token, fuzzy)
            if not options:
                return []
            if combined is None:
                combined = options
                continue
            shared = {
                record_id: combined[record_id] + cost
                for record_id, cost in options.items()
                if record_id in combined
            }
            if not shared:
                return []
            combined = shared
        ranked = []
        for record_id, cost in (combined or {}).items():
            record = self.record_by_id[record_id]
            extra = max(0, self.name_token_count.get(record_id, 0) - len(query_tokens))
            ranked.append((cost, extra, record["name_english"] or "", record["lgd_code"] or "", record))
        ranked.sort()
        return [item[-1] for item in ranked]

    def _similar_records(self, query: str) -> list[dict]:
        folded = compact_name(query)
        budget = len(folded) // 4
        if budget <= 0:
            return []
        ranked = []
        for record in self.entities:
            best = None
            for text in [record.get("name_english"), *(record.get("aliases") or [])]:
                if not text:
                    continue
                distance = levenshtein(folded, compact_name(text), budget)
                if distance is None:
                    continue
                if best is None or distance < best:
                    best = distance
            if best is None:
                continue
            ranked.append(
                (
                    best,
                    abs(len(compact_name(record.get("name_english") or "")) - len(folded)),
                    record.get("name_english") or "",
                    record.get("lgd_code") or "",
                    record,
                )
            )
        ranked.sort()
        return [item[-1] for item in ranked]

    def by_code(self, code: str) -> list[dict]:
        raw = str(code).strip()
        if not raw:
            return []
        hits = []
        for key in (raw, raw.casefold()):
            for record in self.code_lookup.get(key, []):
                if all(existing is not record for existing in hits):
                    hits.append(record)
        return hits

    def search(self, query: str, limit: int = 30, suggestions: int = 3) -> dict:
        raw = str(query).strip()
        folded = normalize_name(raw)
        if not folded:
            return {"query": "", "kind": None, "total": 0, "matches": []}

        code_hits = self.by_code(raw)
        if code_hits:
            return self._pack(raw, code_hits, "code", limit)

        exact = self.lookup.get(folded, [])
        if exact:
            return self._pack(raw, exact, "exact name", limit)

        compact_hits = self.compact_lookup.get(compact_name(raw), [])
        if compact_hits:
            return self._pack(raw, compact_hits, "normalized name", limit)

        query_tokens = tokenize(raw)
        if not query_tokens:
            return {"query": raw, "kind": None, "total": 0, "matches": []}

        partial = self._match_tokens(query_tokens, fuzzy=False)
        if partial:
            return self._pack(raw, partial, "partial name", limit)

        fuzzy = self._match_tokens(query_tokens, fuzzy=True)
        if fuzzy:
            return self._pack(raw, fuzzy, "fuzzy name", limit)

        similar = self._similar_records(raw)
        if similar:
            return self._pack(raw, similar, "similar name", suggestions)

        return {"query": raw, "kind": None, "total": 0, "matches": []}
