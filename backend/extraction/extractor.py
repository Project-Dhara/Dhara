import concurrent.futures
import io
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
import anthropic
from anthropic import RateLimitError as AnthropicRateLimitError
import openai
from openai import RateLimitError as OpenAIRateLimitError

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
OPENAI_MODEL = "gpt-4o-mini"

DDI_PREFIX = "DDI_DEL_DES_VS"
DDI_YEAR   = "2024"
DDI_VER    = "V1"


def _row_text(row) -> str:
    """Join non-empty cells of a raw header row into a single string."""
    if isinstance(row, (list, tuple)):
        return " ".join(str(c).strip() for c in row if c is not None and str(c).strip())
    return str(row).strip()


def _build_ddi_id(tbl: dict) -> str:
    """
    Build a DDI-format table ID.

    _strip_title_desc puts the raw title rows into tbl["table_id"] / tbl["title"];
    raw_header_rows holds the COLUMN header rows (not the table label rows).

    Mapping:
      tbl["table_id"]      e.g. "Table : D-3"                                  → code "D3"
      tbl["title"]         e.g. "Live Birth by Age … (Rural)"                  → top  "RURAL"
      raw_header_rows[0]   e.g. ["Religion-All", None, …]  (optional sub-row)  → nxt  "ALL"

    Result: DDI_DEL_DES_VS_B14_RURAL_ALL_2024_V1
    """
    table_id = tbl.get("table_id", "")
    title    = tbl.get("title", "")
    raw_headers = tbl.get("raw_header_rows", [])

    # 1. Table code from table_id row: "Table : D-3" → "D3", "Table : B-14" → "B14"
    code = ""
    m = re.search(r"\b([A-Za-z]-\d+(?:\.\d+)?)\b", table_id)
    if m:
        code = re.sub(r"[^A-Z0-9]", "", m.group(1).upper())

    # 2. Top-level from the LAST parenthetical in title: "(Urban)" → "URBAN"
    #    The geographic/scope qualifier is always the last parenthetical.
    #    Fall back to table_id if title has none.
    top = ""
    for src in [title, table_id]:
        matches = re.findall(r"\(([^)]+)\)", src)
        if matches:
            candidate = re.sub(r"[^A-Z0-9]", "", matches[-1].strip().upper())
            if candidate and not candidate.isdigit():
                top = candidate
                break

    # 3. Next-level from first raw_header_rows entry: "Religion-All" → "ALL"
    #    Looks for "Word-Value" pattern at end of the row text.
    nxt = ""
    for row in raw_headers:
        text = _row_text(row)
        m = re.search(r"[A-Za-z][A-Za-z\s]*-\s*([A-Za-z][A-Za-z\s]*)$", text.strip())
        if m:
            candidate = re.sub(r"[^A-Z0-9]", "", m.group(1).strip().upper())
            if candidate:
                nxt = candidate
                break

    parts = [DDI_PREFIX]
    if code:
        parts.append(code)
    if top:
        parts.append(top)
    if nxt:
        parts.append(nxt)
    parts.append(DDI_YEAR)
    parts.append(DDI_VER)

    return "_".join(parts)


def _detect_provider(api_key: Optional[str]) -> str:
    """Guess the LLM provider from an API key's prefix. Anthropic-style keys
    are \"sk-ant-...\"; anything else is treated as an OpenAI-compatible
    MEITY-empanelled endpoint."""
    if api_key and api_key.startswith("sk-ant-"):
        return "anthropic"
    return "openai"


def _parse_retry_delay(error: Exception) -> Optional[float]:
    """
    Extract the server-suggested retry delay from a 429 error body.
    Gemini embeds a retryDelay field (e.g. "24s") in the error details.
    Returns seconds as a float, or None if not found.
    """
    try:
        body = getattr(error, "body", None) or {}
        for detail in body.get("error", {}).get("details", []):
            raw = detail.get("retryDelay", "")
            if raw:
                m = re.match(r"([\d.]+)", str(raw))
                if m:
                    return float(m.group(1)) + 3  # add 3 s buffer
    except Exception:
        pass
    return None


def _is_daily_quota_error(error: Exception) -> bool:
    """
    Return True when the quota that's exhausted resets daily (not per-minute).
    Retrying in the same session won't help — fail fast so the caller falls
    back to heuristic immediately instead of burning 60+ seconds waiting.
    """
    try:
        body = getattr(error, "body", None) or {}
        for detail in body.get("error", {}).get("details", []):
            for v in detail.get("violations", []):
                if "PerDay" in v.get("quotaId", ""):
                    return True
        # Also check the plain message string as a fallback
        msg = body.get("error", {}).get("message", "")
        if "PerDay" in msg or "per_day" in msg.lower():
            return True
    except Exception:
        pass
    return False


def _call_with_retry(call, max_retries: int = 3):
    """
    Call `call()` (a zero-arg thunk wrapping a provider-specific create call)
    with smart backoff on RateLimitError.
    - Checks Retry-After header for the suggested wait time.
    - Falls back to 30 s / 60 s exponential backoff when no header is present.
    """
    for attempt in range(max_retries):
        try:
            return call()
        except (AnthropicRateLimitError, OpenAIRateLimitError) as e:
            if attempt == max_retries - 1:
                raise
            wait = _parse_retry_delay(e) or (30 * (2 ** attempt))
            print(f"Rate limit — waiting {wait:.0f}s before retry {attempt + 2}/{max_retries} …")
            time.sleep(wait)


def _extract_json_with_key(text: str, required_key: str) -> Optional[Dict]:
    """Find the first valid JSON object in `text` that contains `required_key`."""
    # Strip markdown fences first
    text = re.sub(r"```[a-z]*\n?", "", text).strip().rstrip("`")
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        # Find the next opening brace
        start = text.find("{", idx)
        if start == -1:
            break
        try:
            obj, end_pos = decoder.raw_decode(text, start)
            if isinstance(obj, dict) and required_key in obj:
                return obj
            idx = start + 1
        except json.JSONDecodeError:
            idx = start + 1
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# TableExtractor
# ═══════════════════════════════════════════════════════════════════════════════

class TableExtractor:
    def __init__(self, api_key: Optional[str] = None, skip_llm: bool = False, provider: Optional[str] = None):
        self.skip_llm = skip_llm
        self.provider = provider or _detect_provider(api_key)
        # Don't touch the SDK at all in skip_llm mode -- constructing it raises
        # if no API key is configured anywhere, which would otherwise make
        # SKIP_LLM=1 unusable without also having a (unused) key set.
        if skip_llm:
            self.client = None
        elif self.provider == "openai":
            self.client = openai.OpenAI(api_key=api_key)
        else:
            self.client = anthropic.Anthropic(api_key=api_key)

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_from_file(self, file_content: bytes, filename: str) -> List[Dict]:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
        except Exception as e:
            raise ValueError(f"Cannot open Excel file: {e}")

        # Process sheets concurrently -- each sheet is 1+ independent LLM calls,
        # and a large workbook (e.g. 36 sheets) run sequentially is the main
        # source of slowness. Capped at 5 workers to stay well under Anthropic
        # rate limits; _call_with_retry still backs off if we hit them anyway.
        sheets = [(name, wb[name]) for name in wb.sheetnames]
        results_by_sheet: List[List[Dict]] = [[] for _ in sheets]
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            future_to_idx = {
                pool.submit(self._process_sheet, ws, name, filename): i
                for i, (name, ws) in enumerate(sheets)
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                results_by_sheet[future_to_idx[future]] = future.result()

        all_tables: List[Dict] = []
        for tables in results_by_sheet:
            all_tables.extend(tables)

        # Generate DDI-format table ID from raw header rows.
        # Format: DDI_DEL_DES_VS_{TABLECODE}_{TOPLEVEL}[_{NEXTLEVEL}]_2024_V1
        for tbl in all_tables:
            tbl["id"] = _build_ddi_id(tbl)

        # Deduplicate IDs within this batch (append _2, _3 for collisions)
        seen_ids: Dict[str, int] = {}
        for tbl in all_tables:
            base = tbl["id"]
            if base in seen_ids:
                seen_ids[base] += 1
                tbl["id"] = f"{base}_{seen_ids[base]}"
            else:
                seen_ids[base] = 1

        # Within each sheet, if multiple tables share the same table_id (ignoring
        # whitespace differences like "TABLE: D-3" vs "TABLE : D-3"), keep the
        # first one's table_id unchanged and suffix later ones with (2), (3)…
        seen: Dict[Tuple[str, str], int] = {}  # (sheet, normalised_table_id) -> count seen so far
        for tbl in all_tables:
            norm_key = (tbl["sheet"], re.sub(r'\s+', '', tbl.get("table_id", "")).lower())
            count = seen.get(norm_key, 0) + 1
            seen[norm_key] = count
            if count > 1:
                tbl["table_id"] = f"{tbl['table_id']} ({count})"

        return all_tables

    # ── Sheet processing ──────────────────────────────────────────────────────

    def _process_sheet(self, ws, sheet_name: str, filename: str) -> List[Dict]:
        grid = self._filled_grid(ws)
        if not grid:
            return []

        blocks = self._find_blocks(grid)
        print(f"[DEBUG] sheet={sheet_name!r}  grid_rows={len(grid)}  blocks={blocks}")

        results = []
        for idx, (start, end) in enumerate(blocks):
            try:
                tbl = self._extract_table(grid, start, end, sheet_name, filename, idx)
                if tbl and tbl["row_count"] > 0:
                    results.append(tbl)
            except Exception as e:
                print(f"[{sheet_name}] block {start}-{end} error: {e}")
            # This pause only exists to stay under Anthropic rate limits between
            # per-block LLM calls -- skip it entirely when there are none.
            if not self.skip_llm and idx < len(blocks) - 1:
                time.sleep(3)
        return results

    # ── Grid builder ──────────────────────────────────────────────────────────

    def _filled_grid(self, ws) -> List[List[Any]]:
        merge_lookup: Dict[Tuple[int, int], Any] = {}
        for mrng in ws.merged_cells.ranges:
            master = ws.cell(mrng.min_row, mrng.min_col).value
            for r in range(mrng.min_row, mrng.max_row + 1):
                for c in range(mrng.min_col, mrng.max_col + 1):
                    if r != mrng.min_row or c != mrng.min_col:
                        merge_lookup[(r, c)] = master

        max_row = max_col = 0
        for row in ws.iter_rows():
            for cell in row:
                v = merge_lookup.get((cell.row, cell.column), cell.value)
                if v is not None and str(v).strip():
                    max_row = max(max_row, cell.row)
                    max_col = max(max_col, cell.column)

        if not max_row:
            return []
        return [
            [merge_lookup.get((r, c), ws.cell(r, c).value) for c in range(1, max_col + 1)]
            for r in range(1, max_row + 1)
        ]

    # ── Block detection ───────────────────────────────────────────────────────

    # Short CRS / vital-stats table codes used as full-width banners (D-14, B-6).
    _SHORT_TABLE_CODE_RE = re.compile(
        r"^(?:TABLE\s*[:.\-–—]?\s*)?"
        r"(?P<code>[A-Z]{1,3})\s*[-–—]?\s*(?P<num>\d+(?:\.\d+)?)\s*$",
        re.IGNORECASE,
    )

    @staticmethod
    def _blank(row: List[Any]) -> bool:
        return all(v is None or str(v).strip() == "" for v in row)

    @staticmethod
    def _row_unique_label(row: List[Any]) -> Optional[str]:
        """Single repeated/non-empty label for a full-width banner row, else None."""
        non_empty = [str(v).strip() for v in row if v is not None and str(v).strip()]
        if not non_empty:
            return None
        unique = {s.upper() for s in non_empty}
        if len(unique) != 1:
            return None
        return non_empty[0]

    @classmethod
    def _has_table_marker(cls, row: List[Any]) -> bool:
        """True for a row that *starts* a new table block.

        Matches short id banners (``TABLE: D-12``, ``D-14``, ``TABLE B-6``).
        Rejects column headers like ``Table Name`` and long footnotes that
        merely mention a table code.
        """
        label = cls._row_unique_label(row)
        if label is not None:
            if len(label) <= 40 and cls._SHORT_TABLE_CODE_RE.match(label):
                return True
            if len(label) <= 48 and re.match(
                r"^TABLE\s*[:.\-–—]\s*[A-Z0-9]", label, re.IGNORECASE
            ):
                return True
            return False

        # Single primary cell (rest empty) — still allow short TABLE ids.
        non_empty = [str(v).strip() for v in row if v is not None and str(v).strip()]
        if len(non_empty) != 1:
            return False
        label = non_empty[0]
        if len(label) > 40:
            return False  # footnotes / prose
        if cls._SHORT_TABLE_CODE_RE.match(label):
            return True
        if re.match(r"^TABLE\s*[:.\-–—]\s*[A-Z0-9]", label, re.IGNORECASE):
            return True
        return False

    @staticmethod
    def _is_columnar_header_row(row: List[Any]) -> bool:
        """True when a row looks like a real multi-column header, not a title banner."""
        non_empty = [v for v in row if v is not None and str(v).strip()]
        if len(non_empty) < 3:
            return False
        unique = {str(v).strip().upper() for v in non_empty}
        if len(unique) < 3:
            return False
        # Banners are usually one long label; header labels stay relatively short.
        longish = sum(1 for v in non_empty if len(str(v).strip()) > 48)
        return longish <= max(1, len(non_empty) // 3)

    def _blocks_from_markers(
        self, grid: List[List[Any]], markers: List[int]
    ) -> List[Tuple[int, int]]:
        blocks = []
        for j, start in enumerate(markers):
            limit = markers[j + 1] if j + 1 < len(markers) else len(grid)
            end = limit - 1
            while end > start and self._blank(grid[end]):
                end -= 1
            # Drop trailing footnote prose (long single-cell notes).
            while end > start:
                row = grid[end]
                if self._blank(row):
                    end -= 1
                    continue
                cells = [str(v).strip() for v in row if v is not None and str(v).strip()]
                text = " ".join(cells)
                if (
                    len(cells) <= 2
                    and len(text) > 48
                    and not self._is_columnar_header_row(row)
                    and not self._has_table_marker(row)
                ):
                    end -= 1
                    continue
                break
            if end > start:
                blocks.append((start, end))
        return blocks

    def _blocks_from_blank_gaps(self, grid: List[List[Any]]) -> List[Tuple[int, int]]:
        """Split on 2+ consecutive blank rows (multi-table sheets with gaps)."""
        blocks, current, blanks = [], None, 0
        for i, row in enumerate(grid):
            if self._blank(row):
                blanks += 1
                if blanks >= 2 and current is not None:
                    end = i - blanks
                    if end > current:
                        blocks.append((current, end))
                    current, blanks = None, 0
            else:
                blanks = 0
                if current is None:
                    current = i
        if current is not None:
            end = len(grid) - 1
            while end > current and self._blank(grid[end]):
                end -= 1
            if end > current:
                blocks.append((current, end))
        return blocks

    def _find_blocks(self, grid: List[List[Any]]) -> List[Tuple[int, int]]:
        # 1) Short table-id banners (TABLE: D-12 / D-14) — strongest signal.
        markers = [i for i, r in enumerate(grid) if self._has_table_marker(r)]
        if markers:
            blocks = self._blocks_from_markers(grid, markers)
            if blocks:
                return blocks

        # 2) Blank-gap split when chunks look like separate titled tables
        #    (id/title banner + columnar header). Skip for single inventory
        #    sheets that only have decorative mid-grid blanks.
        gap_blocks = self._blocks_from_blank_gaps(grid)
        if len(gap_blocks) > 1:
            strong = 0
            for start, end in gap_blocks:
                chunk = [r for r in grid[start : end + 1] if not self._blank(r)]
                if len(chunk) < 3:
                    continue
                top = chunk[0]
                titled = bool(self._has_table_marker(top) or self._row_unique_label(top))
                if titled and any(self._is_columnar_header_row(r) for r in chunk[1:6]):
                    strong += 1
            if strong >= 2:
                return gap_blocks

        # 3) Whole sheet as one table (catalogue inventories, single grids).
        non_blank = [i for i, r in enumerate(grid) if not self._blank(r)]
        if not non_blank:
            return []
        start, end = non_blank[0], non_blank[-1]
        return [(start, end)] if end >= start else []

    # ── Table extraction ──────────────────────────────────────────────────────

    def _extract_table(
        self, grid, start: int, end: int, sheet_name: str, filename: str, idx: int
    ) -> Optional[Dict]:
        block = grid[start : end + 1]
        table_id, title, body_start = self._strip_title_desc(block)
        body = block[body_start:]
        if not body:
            return None

        n_cols = max(len(r) for r in body)

        if self.skip_llm:
            structure = self._heuristic_structure(body, n_cols)
        else:
            try:
                structure = self._direct_llm_structure(body, table_id, title, n_cols)
            except Exception as e:
                print(f"Structure analysis failed ({e}), using heuristic")
                structure = self._heuristic_structure(body, n_cols)

        header_rows: int = structure.get("header_rows", 1)
        skip_set: set = set(structure.get("skip_rows", []))
        columns: List[str] = list(structure.get("columns", []))

        # Clamp runaway multi-row headers on rectangular catalogue sheets
        # (LLM + heuristic both used to swallow early data rows as headers).
        try:
            from metadata.metadata_llm import (
                _looks_like_data_row,
                _row_looks_like_column_labels,
            )
            if (
                header_rows > 1
                and body
                and _row_looks_like_column_labels(body[0])
                and any(_looks_like_data_row(r) for r in body[1:min(5, len(body))])
            ):
                header_rows = 1
                skip_set = {i for i in skip_set if i < 1}
                columns = [
                    str(v).strip() if v is not None else f"Col_{i+1}"
                    for i, v in enumerate(body[0][:n_cols])
                ]
        except Exception:
            pass

        while len(columns) < n_cols:
            columns.append(f"Col_{len(columns)+1}")
        columns = columns[:n_cols]

        # Deduplicate column names
        seen: Dict[str, int] = {}
        deduped = []
        for col in columns:
            if col in seen:
                seen[col] += 1
                deduped.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                deduped.append(col)
        columns = deduped

        # Keep titles short and free of column-list suffixes before row build.
        from metadata.validation import normalize_table_title
        title = normalize_table_title(title, columns) or title
        if not (title or "").strip():
            title = sheet_name or f"Table {idx + 1}"
        if not (table_id or "").strip() or table_id == title:
            # Prefer a stable id when strip left the columnar header as "title".
            if self._is_columnar_header_row(body[0] if body else []):
                table_id = f"Table {idx + 1}"
            elif not (table_id or "").strip():
                table_id = f"Table {idx + 1}"

        rows = []
        for i, row in enumerate(body[header_rows:], start=header_rows):
            if i in skip_set or self._blank(row):
                continue
            padded = list(row) + [None] * (n_cols - len(row))
            row_dict = {}
            for j, col in enumerate(columns):
                v = padded[j]
                if hasattr(v, "item"):
                    v = v.item()
                row_dict[col] = v
            rows.append(row_dict)

        def _ser(row):
            out = []
            for v in row:
                if v is None:
                    out.append(None)
                elif hasattr(v, "item"):
                    out.append(v.item())
                else:
                    out.append(str(v).strip())
            return out

        # Raw header rows before AI flattening (multi-level structure)
        raw_header_rows = [_ser(row) for row in body[:header_rows]]

        # Column-index rows like (1)(2)(3) that were skipped
        raw_col_num_rows = [_ser(body[i]) for i in sorted(skip_set) if i < len(body)]

        # Footer notes: text-heavy rows at the end of the body after data
        raw_notes: List[str] = []
        for row in reversed(body[header_rows:]):
            non_none = [v for v in row if v is not None and str(v).strip()]
            if not non_none:
                continue
            nums = sum(1 for v in non_none if isinstance(v, (int, float)))
            if nums > len(non_none) * 0.3:
                break  # hit a data row — stop scanning
            text = " ".join(str(v).strip() for v in non_none)
            if len(text) > 8:
                raw_notes.insert(0, text)
            if len(raw_notes) >= 10:
                break

        # Leading sheet rows for title repair if validation later disagrees.
        title_context_rows: List[str] = []
        for row in block[:8]:
            if self._blank(row):
                continue
            seen_vals, parts = set(), []
            for v in row:
                if v is None:
                    continue
                sv = str(v).strip()
                if sv and sv not in seen_vals:
                    seen_vals.add(sv)
                    parts.append(sv)
            if parts:
                title_context_rows.append(" ".join(parts))
            if len(title_context_rows) >= 6:
                break

        return {
            "id": f"{filename}__{sheet_name}__{idx}",
            "table_id": table_id or f"Table {idx+1}",
            "title": title,
            "sheet": sheet_name,
            "filename": filename,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "raw_header_rows": raw_header_rows,
            "raw_col_num_rows": raw_col_num_rows,
            "raw_notes": raw_notes,
            "title_context_rows": title_context_rows,
        }

    # ── Title / description extraction ────────────────────────────────────────

    def _strip_title_desc(self, block: List[List[Any]]) -> Tuple[str, str, int]:
        """
        Pull Source Table ID + descriptive title from leading full-width banners.

        Same pattern as PDF in-grid captions: ``TABLE: B-12`` then the long
        title row, then optional subtitle banners (joined into the title).
        Falls back to the legacy first/second-row heuristic when no banner
        pattern is detected.
        """
        from pdf.pdf_header_utils import extract_in_grid_caption

        def row_text(row):
            seen_vals, parts = set(), []
            for v in row:
                if v is None:
                    continue
                sv = str(v).strip()
                if sv and sv not in seen_vals:
                    seen_vals.add(sv)
                    parts.append(sv)
            return " ".join(parts)

        caption = extract_in_grid_caption(block)
        table_id = (caption.get("table_id_label") or "").strip()
        title = (caption.get("title") or "").strip()
        body_start = int(caption.get("rows_consumed") or 0)

        if table_id or title:
            while body_start < len(block) and self._blank(block[body_start]):
                body_start += 1
            # If we only got an id, try the next non-blank row as title (legacy).
            if table_id and not title:
                for j in range(body_start, len(block)):
                    if self._blank(block[j]):
                        continue
                    text = row_text(block[j])
                    non_none = [v for v in block[j] if v is not None and str(v).strip()]
                    n_nums = sum(1 for v in non_none if isinstance(v, (int, float)))
                    if text and len(text) > 10 and n_nums < max(1, len(non_none) / 2):
                        # Prefer a single-label banner-like row over a real header.
                        unique = {str(v).strip().upper() for v in non_none}
                        if len(unique) == 1 or len(non_none) <= 2:
                            title = text
                            body_start = j + 1
                    break
            while body_start < len(block) and self._blank(block[body_start]):
                body_start += 1
            return table_id, title, body_start

        # Rectangular sheets (catalogue inventories, SQL dumps): keep the first
        # multi-column header row inside the body so structure detection can use
        # it. Peeling it as "title" + the next row as "description" drops early
        # data rows and feeds data into the header flattener.
        non_blank = [(i, r) for i, r in enumerate(block) if not self._blank(r)]
        if not non_blank:
            return "", "", 0

        i0, r0 = non_blank[0]
        if self._is_columnar_header_row(r0):
            return "", "", i0

        first = row_text(r0)
        body_start = i0 + 1
        second = ""

        if len(non_blank) > 1:
            i1, r1 = non_blank[1]
            # Never swallow a dense data/header-looking row as a "description".
            if not self._is_columnar_header_row(r1):
                text1 = row_text(r1)
                non_none = [v for v in r1 if v is not None and str(v).strip()]
                unique = {str(v).strip().upper() for v in non_none}
                n_nums = sum(1 for v in non_none if isinstance(v, (int, float)))
                banner_like = len(unique) == 1 or len(non_none) <= 2
                if (
                    banner_like
                    and text1
                    and len(text1) > 10
                    and n_nums < len(non_none) / 2
                ):
                    second = text1
                    body_start = i1 + 1

        # Prefer true TABLE-id banners as id when present.
        if self._has_table_marker(r0):
            table_id, title = first, second
        elif second and len(non_blank) > 1 and self._has_table_marker(non_blank[1][1]):
            table_id, title = second, first
        else:
            table_id, title = first, second

        while body_start < len(block) and self._blank(block[body_start]):
            body_start += 1
        return table_id, title, body_start

    # ── LLM completion (provider-agnostic) ───────────────────────────────────

    def _complete(self, prompt: str, max_tokens: int) -> str:
        """Single-turn plain-text completion, routed to whichever provider
        this extractor was constructed for."""
        if self.provider == "openai":
            resp = _call_with_retry(lambda: self.client.chat.completions.create(
                model=OPENAI_MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            ))
            return resp.choices[0].message.content.strip()
        resp = _call_with_retry(lambda: self.client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        ))
        return resp.content[0].text.strip()

    # ─────────────────────────────────────────────────────────────────────────
    # STRATEGY A — Direct LLM (single prompt → single response)
    # ─────────────────────────────────────────────────────────────────────────

    def _direct_llm_structure(
        self, body: List[List[Any]], title: str, description: str, n_cols: int
    ) -> Dict:
        n_sample = min(10, len(body))
        lines = []
        for i, row in enumerate(body[:n_sample]):
            vals = "\t".join("" if v is None else str(v).strip() for v in row)
            lines.append(f"Row {i+1}:\t{vals}")
        grid_text = "\n".join(lines)

        prompt = f"""Analyze this government statistical table body and return its structure.

Table: {title}
{f"Description: {description}" if description else ""}
Columns: {n_cols}, Total rows: {len(body)}

First {n_sample} rows (tab-separated):
{grid_text}

Return JSON with:
- "header_rows": count of rows at start that are column headers (not data)
- "skip_rows": 0-based row indices to skip (e.g. column-number rows like "(1)(2)(3)")
- "columns": exactly {n_cols} flat column names

For multi-level headers (group row + sub-column row), combine: "AGE_<1", "AGE_1-4"
Return ONLY valid JSON, no markdown fences."""

        text = self._complete(prompt, max_tokens=2048)
        text = re.sub(r"```[a-z]*\n?", "", text).strip().rstrip("`").strip()
        return json.loads(text)

    # ── LLM-based category metadata extraction ───────────────────────────────

    def extract_category_metadata(
        self,
        title: str,
        description: str,
        raw_header_rows: List[List],
        columns: List[str],
        sample_rows: List[Dict],
        raw_notes: List[str],
    ) -> List[Dict]:
        """
        Ask the LLM to semantically identify all categorical dimensions present in
        the table — e.g. Area Type (Rural/Urban), Care Setting (Institution/Domiciliary),
        Gender (Male/Female), Geography (State, District), Age Group, etc.
        Returns a list of category dicts: {name, description, values:[{value,code,description}]}
        """
        if self.skip_llm:
            return []

        # Format original header matrix so the LLM sees the raw multi-level structure
        header_lines = []
        for i, row in enumerate(raw_header_rows):
            deduped: List[str] = []
            seen_in_row: set = set()
            for v in row:
                sv = str(v).strip() if v is not None else ""
                if sv and sv not in seen_in_row:
                    deduped.append(sv)
                    seen_in_row.add(sv)
            if deduped:
                header_lines.append(f"  Header level {i+1}: {' | '.join(deduped)}")

        # Sample the first few data rows so the LLM can see row-dimension values
        data_sample_lines = []
        for row in sample_rows[:6]:
            vals = " | ".join(str(v) for v in list(row.values())[:6] if v is not None)
            if vals:
                data_sample_lines.append(f"  {vals}")

        prompt = f"""You are analyzing a government statistical table to build a metadata catalogue.

Table: {title}
{f'Description: {description}' if description else ''}

Original multi-level column headers (before flattening):
{chr(10).join(header_lines) if header_lines else '  (single-level headers)'}

Flat column names after AI extraction ({len(columns)} total):
  {', '.join(columns[:30])}{'…' if len(columns) > 30 else ''}

First few data rows (first 6 values each):
{chr(10).join(data_sample_lines) if data_sample_lines else '  (no sample)'}
{f"Source notes: {'; '.join(raw_notes[:4])}" if raw_notes else ''}

Your task: identify EVERY categorical dimension in this table.
A "category" is any grouping variable — examples:
- Column-group headers like RURAL / URBAN (spans multiple sub-columns)
- Sub-group headers like INSTITUTION / DOMICILIARY
- Cross-tabulation variables like Male / Female, Age bands, Year
- Row-dimension labels like State, District, Block, Taluk

Rules:
- Each category name must be UNIQUE — do not repeat the same category twice
- Each value within a category must be UNIQUE — list each value only once
- Merge overlapping categories into one (e.g. "Area" and "Location Type" are the same)
- Omit "Total" or "Grand Total" rows — those are aggregates, not categories

For each category:
- Give it a clear human-readable name (e.g. "Area Type", "Care Setting", "Gender")
- Write a one-sentence description of what it classifies
- List every unique value you can identify from the headers and data sample
- Generate a short UPPERCASE_UNDERSCORE code for each value
- Write a brief plain-English description for each value

Return ONLY a valid JSON object — no prose, no markdown fences:
{{
  "categories": [
    {{
      "name": "Area Type",
      "description": "Classifies data by geographic area type",
      "values": [
        {{"value": "Rural", "code": "RURAL", "description": "Data from rural areas outside municipal limits"}},
        {{"value": "Urban", "code": "URBAN", "description": "Data from urban areas within municipal limits"}}
      ]
    }}
  ]
}}"""

        text = self._complete(prompt, max_tokens=1000)
        parsed = _extract_json_with_key(text, "categories")
        if parsed is None:
            return []
        return parsed.get("categories", [])

    # ── DES Catalogue enrichment ──────────────────────────────────────────────

    def enrich_for_catalogue(self, table: dict) -> dict:
        """Use Claude to generate DES-catalogue-compatible metadata for one table."""
        if self.skip_llm:
            return {
                "short_description": table.get("title", "") or table.get("table_id", ""),
                "long_description": table.get("title", "") or table.get("table_id", ""),
                "units": "Count",
                "classifications": {},
                "age_column_keys": {},
            }

        columns = table.get("columns", [])
        sample_rows = table.get("rows", [])[:6]

        prompt = f"""You are a data cataloguer for the Delhi Economic Survey (DES). Given an extracted Excel table, generate structured catalogue metadata.

Source Table ID: {table.get('table_id', '')}
Sheet: {table.get('sheet', '')}
Columns ({len(columns)}): {columns}
Sample rows (first 6): {json.dumps(sample_rows, default=str)}
Existing title: {table.get('title', '')}

Return ONLY a JSON object with exactly these fields:
{{
  "short_description": "1-2 sentence factual summary of what data this table contains",
  "long_description": "3-5 sentence detailed description: what is measured, geographic scope, time period, disaggregation levels, and how to interpret the data",
  "units": "measurement unit as a short string, e.g. 'Count', 'Percentage', 'Rs. Crore', 'Lakhs', 'Rate per 1000'",
  "classifications": {{
    "dimension_name": ["value1", "value2"]
  }},
  "age_column_keys": {{
    "col_name_or_key": "readable age label"
  }}
}}

Rules for classifications:
- Identify categorical dimensions from column names and sample data values (e.g. gender_classification, area_type, administrative_body, place_of_occurrence)
- For each dimension list up to 15 unique values found in column names or sample data
- Use snake_case dimension names
- Do NOT include numeric/quantitative columns as classifications
- If no clear categorical dimensions exist, return an empty object {{}}

Rules for age_column_keys:
- Only populate if the table has columns representing age groups (e.g. "<1", "1-4", "15-24", "65+")
- Map the column name to a readable human label
- Return empty object {{}} if no age-related columns exist

Return only valid JSON, no markdown fences, no explanation."""

        text = self._complete(prompt, max_tokens=1500)
        # strip markdown fences
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            parsed = _extract_json_with_key(text, "short_description")
            result = parsed or {}

        return {
            "short_description": result.get("short_description", table.get("title", "")),
            "long_description": result.get("long_description", table.get("title", "")),
            "units": result.get("units", "Count"),
            "classifications": result.get("classifications", {}),
            "age_column_keys": result.get("age_column_keys", {}),
        }

    # ── Heuristic fallback ────────────────────────────────────────────────────

    @staticmethod
    def _heuristic_structure(body: List[List[Any]], n_cols: int) -> Dict:
        # Use the richer multi-row header flattener shared with metadata facts —
        # the local one-row heuristic left many scheme sheets under-extracted.
        from metadata.metadata_llm import _heuristic_structure as _better_heuristic
        return _better_heuristic(body, n_cols)
