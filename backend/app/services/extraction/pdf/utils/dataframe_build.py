"""Build pandas DataFrames from extracted PDF table row grids."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence

from app.services.extraction.pdf.utils.caption import (
    _blank,
    _cell_str,
    _is_leaf_header_token,
    _is_measurement_number,
    _pad_row,
    _row_is_column_number_strip,
    extract_in_grid_caption,
)

from app.services.extraction.pdf.utils.header_detect import (
    _fill_blank_leading_serial_header,
    _row_is_subheader,
    _row_is_text_header,
    _row_looks_like_data,
    _split_hybrid_leaf_data_row,
    _uniquify_columns,
    detect_header_rows,
    resolve_column_headers,
)

from app.services.extraction.pdf.utils.grid_repair import (
    _find_sex_column,
    coalesce_phantom_grid_columns,
    expand_collapsed_sex_pair_rows,
    fold_label_wrap_continuation_rows,
    fold_orphan_parenthetical_share_rows,
    repair_glued_numeric_cells,
    repair_sex_pair_next_row_label_bleed,
)

def _looks_like_birth_order_leaf_strip(row: Sequence[Any], n_cols: int) -> bool:
    """True for Sl.No. / age-stub / 1,2,…,>8,All header strips parked as data."""
    padded = _pad_row(row, n_cols)
    non_empty = [v for v in padded if _cell_str(v)]
    if len(non_empty) < max(4, int(n_cols * 0.5)):
        return False
    if sum(1 for v in non_empty if _is_measurement_number(v)) >= 2:
        return False
    # Reject bare 1..N / (1)(2)(3) index strips — those are not leaf headers.
    if all(
        bool(re.match(r"^\(?\d+\)?$", _cell_str(v).replace(" ", "")))
        for v in non_empty
    ):
        return False
    leafish = sum(1 for v in non_empty if _is_leaf_header_token(v))
    if leafish < max(3, int(len(non_empty) * 0.55)):
        return False
    # Need a serial / stub label plus several short order codes.
    has_serial = any(
        re.match(r"^(?:sl\.?\s*no\.?|s\.?\s*no\.?|sno)$", _cell_str(v), re.I)
        for v in non_empty
    )
    order_codes = sum(
        1 for v in non_empty
        if re.match(r"^(?:\d+|>\s*8|≥\s*8|all)$", _cell_str(v).replace(" ", ""), re.I)
    )
    return bool(has_serial and order_codes >= 3)

def _promote_leading_leaf_strip(
    header_matrix: List[List[Any]],
    header_count: int,
    padded: List[List[Any]],
    skip_rows: List[int],
    n_cols: int,
) -> Tuple[List[List[Any]], int, List[List[Any]]]:
    """Pull a misplaced 1..>8 leaf strip from the first body row into headers."""
    next_i = header_count
    while next_i < len(padded) and (next_i in skip_rows or _blank(padded[next_i])):
        next_i += 1
    if next_i >= len(padded):
        return header_matrix, header_count, padded
    candidate = padded[next_i]
    if not _looks_like_birth_order_leaf_strip(candidate, n_cols):
        return header_matrix, header_count, padded
    # Already have distinct short leaves under the group — nothing to promote.
    if header_matrix:
        last = header_matrix[-1]
        last_non_empty = [v for v in last if _cell_str(v)]
        if (
            len(last_non_empty) >= max(4, int(n_cols * 0.5))
            and sum(1 for v in last_non_empty if _is_leaf_header_token(v))
            >= max(3, int(len(last_non_empty) * 0.55))
        ):
            return header_matrix, header_count, padded
    new_matrix = list(header_matrix) + [_pad_row(candidate, n_cols)]
    return new_matrix, next_i + 1, padded

def _recover_stub_from_caption(
    leaf_names: List[str],
    column_meta: List[dict],
    caption_title: Optional[str],
) -> Tuple[List[str], List[dict]]:
    """Rename a truncated age stub using the descriptive caption.

    PyMuPDF often splits ``AGE OF MOTHER`` across header rows (``AGE OF`` on
    the group row, ``MOTHER`` on the leaf). Stub resolution keeps only the
    parent token; restore the full phrase when the caption clearly has it.
    """
    title = _cell_str(caption_title).upper()
    if not title or "MOTHER" not in title:
        return leaf_names, column_meta
    full = None
    if "AGE OF THE MOTHER" in title:
        full = "AGE OF THE MOTHER"
    elif "AGE OF MOTHER" in title:
        full = "AGE OF MOTHER"
    if not full:
        return leaf_names, column_meta
    names = list(leaf_names)
    meta = [dict(m) for m in column_meta]
    for i, name in enumerate(names):
        u = str(name).strip().upper()
        if u not in {"MOTHER", "AGE OF", "AGE OF THE"}:
            continue
        names[i] = full
        if i < len(meta):
            meta[i]["name"] = full
            path = [str(p) for p in (meta[i].get("header_path") or []) if str(p).strip()]
            if path:
                path[-1] = full
            else:
                path = [full]
            meta[i]["header_path"] = path
        break
    return names, meta

def dataframe_from_extracted_rows(rows: Optional[List[List[Any]]]):
    """
    Build a pandas DataFrame from a pymupdf `tab.extract()` grid, flattening
    multi-row / merged headers when present.

    Hierarchy is stored on ``df.attrs["dhara_column_meta"]`` as
    ``[{"name", "header_group", "header_path"}, ...]`` for Preview.
    """
    import pandas as pd

    if not rows:
        return pd.DataFrame()

    n_cols = max((len(r) for r in rows), default=0)
    if n_cols == 0:
        return pd.DataFrame()

    # Expand collapsed M/F stacks while newlines still exist; then unglue
    # horizontally packed measure values into neighbouring empty columns.
    padded = expand_collapsed_sex_pair_rows([_pad_row(r, n_cols) for r in rows])
    n_cols = max((len(r) for r in padded), default=n_cols)
    sex_col = _find_sex_column(padded, n_cols)
    # Also repair already-separate rows where a next-disease title bled into
    # the empty F stub (common with wrapped Name cells).
    padded = repair_sex_pair_next_row_label_bleed(padded, sex_col)
    padded = repair_glued_numeric_cells([_pad_row(r, n_cols) for r in padded])
    header_count, skip_rows = detect_header_rows(padded, n_cols)

    root = None
    for i in range(header_count):
        if i not in skip_rows and not _blank(padded[i]):
            root = padded[i]
            break

    # Pull any remaining subheader strips that follow the detected block.
    while True:
        next_i = header_count
        while next_i < len(padded) and next_i in skip_rows:
            next_i += 1
        if next_i >= len(padded):
            break
        if root is not None:
            leaf_part, data_part = _split_hybrid_leaf_data_row(padded[next_i], root, n_cols)
            if leaf_part is not None and data_part is not None:
                padded[next_i] = leaf_part
                padded.insert(next_i + 1, data_part)
                header_count = next_i + 1
                break
        if _row_looks_like_data(padded[next_i], root):
            break
        if _row_is_subheader(padded[next_i], root) or _row_is_text_header(
            padded[next_i], continuation=True, parent_row=root
        ):
            header_count = next_i + 1
            continue
        break

    header_matrix = [padded[i] for i in range(header_count) if i not in skip_rows]
    if not header_matrix:
        header_matrix = [padded[0]]
        header_count = 1

    # When a group banner (education / BIRTH ORDER) absorbed "AGE OF" into the
    # header and the real leaf strip (Sl.No. / MOTHER / 1..>8) was treated as
    # data, promote that first body row back into the header block.
    header_matrix, header_count, padded = _promote_leading_leaf_strip(
        header_matrix, header_count, padded, skip_rows, n_cols
    )

    resolved = resolve_column_headers(header_matrix, n_cols)
    leaf_names = _uniquify_columns([c["name"] for c in resolved])
    column_meta = []
    for i in range(n_cols):
        path = [str(p) for p in (resolved[i].get("header_path") or []) if str(p).strip()]
        if not path:
            path = [resolved[i].get("name") or leaf_names[i]]
        # Keep original leaf labels in header_path for display (S.R.S. under
        # Birth Rate vs Death Rate). DataFrame column names stay uniquified.
        column_meta.append({
            "name": leaf_names[i],
            "header_group": path[-2] if len(path) >= 2 else None,
            "header_path": path,
        })
    leaf_names, column_meta = _fill_blank_leading_serial_header(leaf_names, column_meta)

    body = [
        padded[i]
        for i in range(header_count, len(padded))
        if i not in skip_rows and not _blank(padded[i])
    ]
    # Index strips (1..N / (1)(2)(3)) are skipped for header naming but must
    # remain visible as the first body row(s) when they sit under the headers.
    leading_index: List[List[Any]] = []
    for i in range(header_count, len(padded)):
        if i not in skip_rows:
            break
        if _blank(padded[i]):
            continue
        if _row_is_column_number_strip(padded[i], n_cols):
            leading_index.append(padded[i])
        else:
            # Non-index skip (banner) — stop; don't pull mid-table strips forward.
            break
    if leading_index:
        body = leading_index + body
    caption = extract_in_grid_caption(padded)
    leaf_names, column_meta = _recover_stub_from_caption(
        leaf_names, column_meta, caption.get("title")
    )

    def _attach_caption_attrs(frame):
        frame.attrs["dhara_column_meta"] = column_meta
        if caption.get("title"):
            frame.attrs["dhara_table_caption"] = caption["title"]
        if caption.get("table_id_label"):
            frame.attrs["dhara_banner_table_id"] = caption["table_id_label"]
        return frame

    if not body:
        df = pd.DataFrame(columns=leaf_names)
        return _attach_caption_attrs(df)

    clean_body: List[List[Any]] = [
        [_cell_str(v) or None for v in row] for row in body
    ]
    df = pd.DataFrame(clean_body, columns=leaf_names)
    df = _attach_caption_attrs(df)
    # Collapse PyMuPDF interstitial phantom columns (Cause/(2)/(3), Male/(2)/(3))
    # and fold stub-only wrap rows into the parent disease row.
    df = coalesce_phantom_grid_columns(df)
    df = fold_label_wrap_continuation_rows(df)
    df = fold_orphan_parenthetical_share_rows(df)
    return df

__all__ = [
    "dataframe_from_extracted_rows",
]
