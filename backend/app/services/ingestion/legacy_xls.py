"""Upload-time normalize: legacy BIFF .xls → Unicode .xlsx (font-aware).

Does not change Excel extraction. Call before dispatch_extraction so the
existing openpyxl pipeline receives a normal .xlsx workbook.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import openpyxl
import xlrd
from openpyxl.utils import get_column_letter
from xlrd import XL_CELL_BOOLEAN, XL_CELL_DATE, XL_CELL_EMPTY, XL_CELL_ERROR, XL_CELL_NUMBER, XL_CELL_TEXT
from xlrd.xldate import xldate_as_datetime

from app.services.ingestion.legacy_hindi_maps import chanakya_to_unicode, krutidev_to_unicode

logger = logging.getLogger(__name__)


class LegacyXlsError(ValueError):
    """Controlled convert failure → upload HTTP 400."""


@dataclass
class _ConvertStats:
    converted: int = 0
    unchanged: int = 0
    flagged: int = 0
    flagged_refs: list[str] = field(default_factory=list)
    legacy_fonts: set[str] = field(default_factory=set)
    sample_converted: list[tuple[str, int, int, str]] = field(default_factory=list)
    sample_nontext: list[tuple[str, int, int, Any]] = field(default_factory=list)
    # sheet -> list of (rlo, rhi, clo, chi) 0-based exclusive end (xlrd)
    merges: dict[str, list[tuple[int, int, int, int]]] = field(default_factory=dict)
    dims: dict[str, tuple[int, int]] = field(default_factory=dict)
    sheet_names: list[str] = field(default_factory=list)


def _is_xls_filename(filename: str) -> bool:
    name = (filename or "").lower()
    return name.endswith(".xls") and not name.endswith(".xlsx") and not name.endswith(".xlsm")


def _font_family(name: str) -> Optional[str]:
    """Return 'krutidev' | 'chanakya' | None (passthrough)."""
    n = re.sub(r"[\s_\-]+", "", (name or "").lower())
    if "kruti" in n:
        return "krutidev"
    if "chanakya" in n:
        return "chanakya"
    return None


def _font_name_for_index(book: xlrd.Book, font_index: int) -> Optional[str]:
    try:
        if font_index < 0 or font_index >= len(book.font_list):
            return None
        return book.font_list[font_index].name or ""
    except Exception:
        return None


def _effective_font_name(book: xlrd.Book, sheet: xlrd.sheet.Sheet, rowx: int, colx: int) -> Optional[str]:
    try:
        xfx = sheet.cell_xf_index(rowx, colx)
        xf = book.xf_list[xfx]
        return _font_name_for_index(book, xf.font_index)
    except Exception:
        return None


def _decode_span(text: str, font_name: Optional[str], stats: _ConvertStats, cell_ref: str) -> str:
    family = _font_family(font_name or "")
    if family is None:
        if font_name:
            # Known Latin / Unicode fonts — passthrough, count unchanged below.
            pass
        else:
            stats.flagged += 1
            if len(stats.flagged_refs) < 50:
                stats.flagged_refs.append(f"{cell_ref}:unreliable-font")
        return text

    stats.legacy_fonts.add(font_name or family)
    try:
        if family == "krutidev":
            out = krutidev_to_unicode(text)
        else:
            out = chanakya_to_unicode(text)
    except Exception as e:
        stats.flagged += 1
        if len(stats.flagged_refs) < 50:
            stats.flagged_refs.append(f"{cell_ref}:decode-error:{e}")
        return text
    return out


def _decode_rich_or_plain(
    book: xlrd.Book,
    sheet: xlrd.sheet.Sheet,
    rowx: int,
    colx: int,
    text: str,
    stats: _ConvertStats,
) -> tuple[str, bool]:
    """Return (decoded_text, was_converted)."""
    cell_ref = f"{sheet.name}!{get_column_letter(colx + 1)}{rowx + 1}"
    runlist = None
    try:
        runlist = sheet.rich_text_runlist_map.get((rowx, colx))
    except Exception:
        runlist = None

    if not runlist:
        font_name = _effective_font_name(book, sheet, rowx, colx)
        if _font_family(font_name or "") is None:
            stats.unchanged += 1
            return text, False
        decoded = _decode_span(text, font_name, stats, cell_ref)
        if decoded != text:
            stats.converted += 1
            if len(stats.sample_converted) < 5:
                stats.sample_converted.append((sheet.name, rowx, colx, decoded))
            return decoded, True
        stats.unchanged += 1
        return text, False

    # Rich text: offsets into the *original* string.
    xf_font = _effective_font_name(book, sheet, rowx, colx)
    runs = sorted(runlist, key=lambda t: t[0])
    parts: list[str] = []
    converted_any = False
    # Leading segment [0, first_offset) uses XF font if first offset > 0
    boundaries: list[tuple[int, Optional[str]]] = []
    if not runs or runs[0][0] > 0:
        boundaries.append((0, xf_font))
    for offset, font_index in runs:
        boundaries.append((offset, _font_name_for_index(book, font_index)))

    for i, (start, font_name) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        if start >= len(text) or start >= end:
            continue
        span = text[start:end]
        if _font_family(font_name or "") is None and font_name is None:
            stats.flagged += 1
            if len(stats.flagged_refs) < 50:
                stats.flagged_refs.append(f"{cell_ref}:rich-unreliable@{start}")
            parts.append(span)
            continue
        if _font_family(font_name or "") is None:
            parts.append(span)
            continue
        decoded = _decode_span(span, font_name, stats, f"{cell_ref}@{start}")
        if decoded != span:
            converted_any = True
        parts.append(decoded)

    out = "".join(parts)
    if converted_any:
        stats.converted += 1
        if len(stats.sample_converted) < 5:
            stats.sample_converted.append((sheet.name, rowx, colx, out))
    else:
        stats.unchanged += 1
    return out, converted_any


def _cell_python_value(book: xlrd.Book, sheet: xlrd.sheet.Sheet, rowx: int, colx: int, stats: _ConvertStats):
    cell = sheet.cell(rowx, colx)
    ctype = cell.ctype
    value = cell.value

    if ctype in (XL_CELL_EMPTY, XL_CELL_ERROR) or value == "":
        return None

    if ctype == XL_CELL_TEXT:
        text = str(value)
        if not text:
            return None
        decoded, _ = _decode_rich_or_plain(book, sheet, rowx, colx, text, stats)
        return decoded

    if ctype == XL_CELL_BOOLEAN:
        if len(stats.sample_nontext) < 3:
            stats.sample_nontext.append((sheet.name, rowx, colx, bool(value)))
        return bool(value)

    if ctype == XL_CELL_DATE:
        try:
            dt = xldate_as_datetime(value, book.datemode)
            if len(stats.sample_nontext) < 3:
                stats.sample_nontext.append((sheet.name, rowx, colx, dt))
            return dt
        except Exception:
            stats.flagged += 1
            if len(stats.flagged_refs) < 50:
                stats.flagged_refs.append(
                    f"{sheet.name}!{get_column_letter(colx + 1)}{rowx + 1}:bad-date"
                )
            return value

    if ctype == XL_CELL_NUMBER:
        # Cached formula results arrive as numbers too.
        num = value
        if isinstance(num, float) and num.is_integer():
            num = int(num)
        if len(stats.sample_nontext) < 3:
            stats.sample_nontext.append((sheet.name, rowx, colx, num))
        return num

    return value


def _write_xlsx(book: xlrd.Book, stats: _ConvertStats) -> bytes:
    wb_out = openpyxl.Workbook()
    # Remove default sheet; recreate in source order.
    default = wb_out.active
    wb_out.remove(default)

    for si in range(book.nsheets):
        sheet = book.sheet_by_index(si)
        name = sheet.name[:31] or f"Sheet{si + 1}"
        stats.sheet_names.append(name)
        ws = wb_out.create_sheet(title=name)
        stats.dims[name] = (sheet.nrows, sheet.ncols)

        # Build set of non-top-left merge slave cells (leave blank).
        merge_ranges = list(sheet.merged_cells or [])
        stats.merges[name] = list(merge_ranges)
        slave: set[tuple[int, int]] = set()
        for rlo, rhi, clo, chi in merge_ranges:
            for r in range(rlo, rhi):
                for c in range(clo, chi):
                    if r != rlo or c != clo:
                        slave.add((r, c))

        for rowx in range(sheet.nrows):
            for colx in range(sheet.ncols):
                if (rowx, colx) in slave:
                    continue
                val = _cell_python_value(book, sheet, rowx, colx, stats)
                if val is None:
                    continue
                ws.cell(row=rowx + 1, column=colx + 1, value=val)

        for rlo, rhi, clo, chi in merge_ranges:
            # openpyxl merge is inclusive; xlrd hi/chi exclusive.
            if rhi - rlo < 1 or chi - clo < 1:
                continue
            if rhi - rlo == 1 and chi - clo == 1:
                continue
            ws.merge_cells(
                start_row=rlo + 1,
                start_column=clo + 1,
                end_row=rhi,
                end_column=chi,
            )

    buf = io.BytesIO()
    wb_out.save(buf)
    return buf.getvalue()


def _self_check(xlsx_bytes: bytes, stats: _ConvertStats) -> None:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    except Exception as e:
        raise LegacyXlsError(f"Normalized workbook failed to open: {e}") from e

    names = list(wb.sheetnames)
    if names != stats.sheet_names:
        raise LegacyXlsError(
            f"Sheet names mismatch after convert: got {names!r}, expected {stats.sheet_names!r}"
        )

    for name in names:
        ws = wb[name]
        exp_rows, exp_cols = stats.dims[name]
        # openpyxl max_row can be 1 for empty; compare only when source had content.
        if exp_rows > 0 and (ws.max_row or 0) < 1:
            raise LegacyXlsError(f"Sheet {name!r} has no rows after convert")

        exp_merges = {
            f"{get_column_letter(clo + 1)}{rlo + 1}:{get_column_letter(chi)}{rhi}"
            for rlo, rhi, clo, chi in stats.merges.get(name, [])
            if not (rhi - rlo == 1 and chi - clo == 1)
        }
        got_merges = {str(r) for r in ws.merged_cells.ranges}
        # Allow string form differences by normalizing via openpyxl parse — compare counts + coverage.
        if len(got_merges) != len(exp_merges):
            # Some writers normalize ranges; verify each expected top-left is covered.
            for rlo, rhi, clo, chi in stats.merges.get(name, []):
                if rhi - rlo == 1 and chi - clo == 1:
                    continue
                covered = False
                for mr in ws.merged_cells.ranges:
                    if (
                        mr.min_row == rlo + 1
                        and mr.min_col == clo + 1
                        and mr.max_row == rhi
                        and mr.max_col == chi
                    ):
                        covered = True
                        break
                if not covered:
                    raise LegacyXlsError(
                        f"Missing merge on {name!r}: "
                        f"{get_column_letter(clo + 1)}{rlo + 1}:{get_column_letter(chi)}{rhi}"
                    )

    for sheet_name, rowx, colx, expected in stats.sample_converted:
        ws = wb[sheet_name]
        got = ws.cell(row=rowx + 1, column=colx + 1).value
        if got != expected:
            raise LegacyXlsError(
                f"Converted cell mismatch at {sheet_name}!"
                f"{get_column_letter(colx + 1)}{rowx + 1}: {got!r} != {expected!r}"
            )

    for sheet_name, rowx, colx, expected in stats.sample_nontext:
        ws = wb[sheet_name]
        got = ws.cell(row=rowx + 1, column=colx + 1).value
        if got is None and expected is not None:
            raise LegacyXlsError(
                f"Non-text cell empty after convert at {sheet_name}!"
                f"{get_column_letter(colx + 1)}{rowx + 1}"
            )


def _convert_xls_bytes(content: bytes, original_filename: str) -> tuple[str, bytes]:
    try:
        fmt = xlrd.inspect_format(content=content)
    except Exception as e:
        raise LegacyXlsError(f"Cannot inspect spreadsheet format: {e}") from e

    if fmt != "xls":
        desc = xlrd.FILE_FORMAT_DESCRIPTIONS.get(fmt, fmt or "unknown")
        raise LegacyXlsError(
            f"File {original_filename!r} is not a legacy BIFF .xls workbook "
            f"(detected {desc}). Re-save or rename correctly before upload."
        )

    try:
        book = xlrd.open_workbook(file_contents=content, formatting_info=True)
    except Exception as e:
        raise LegacyXlsError(f"Cannot read legacy .xls workbook: {e}") from e

    stats = _ConvertStats()
    try:
        xlsx_bytes = _write_xlsx(book, stats)
        _self_check(xlsx_bytes, stats)
    except LegacyXlsError:
        raise
    except Exception as e:
        raise LegacyXlsError(f"Legacy .xls conversion failed: {e}") from e

    stem = Path(original_filename).stem or "upload"
    normalized_name = f"{stem}.xlsx"
    digest = hashlib.sha256(content).hexdigest()
    logger.info(
        "legacy_xls_normalize original=%r normalized=%r sha256=%s "
        "legacy_fonts=%s converted=%d unchanged=%d flagged=%d flagged_refs=%s",
        original_filename,
        normalized_name,
        digest,
        sorted(stats.legacy_fonts),
        stats.converted,
        stats.unchanged,
        stats.flagged,
        stats.flagged_refs[:20],
    )
    return normalized_name, xlsx_bytes


def normalize_excel_upload(filename: str, content: bytes) -> tuple[str, bytes]:
    """If *filename* is `.xls`, convert to Unicode `.xlsx`; otherwise return unchanged.

    Raises:
        LegacyXlsError: malformed, unsupported, or failed conversion.
    """
    if not _is_xls_filename(filename):
        return filename, content
    if not content:
        raise LegacyXlsError("Uploaded .xls file is empty")
    return _convert_xls_bytes(content, filename)
