"""Local CLI for PDF step 1 (``python -m app.services.extraction.pdf``)."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

# confidence_validation → pdf → extraction → services → app → backend
load_dotenv(Path(__file__).resolve().parents[5] / ".env")

from app.services.llm_prompts import BATCH_SIZE, CPU_WORKERS, OPENAI_WORKERS, OUTPUT_DIR, PDF_PATH
from app.services.extraction.pdf.confidence_validation.confidence_split import (
    _llm_pages_missing_tables,
    split_by_confidence,
)
from app.services.extraction.pdf.confidence_validation.heuristic import heuristic_accept_pages
from app.services.extraction.pdf.confidence_validation.llm import (
    _log_representative_examples,
    validate_all_pages_batched,
)
from app.services.extraction.pdf.confidence_validation.table_confidence import build_pdf_outline_index
from app.services.extraction.pdf.utils.pymupdf import (
    classify_pages,
    extract_all_tables,
    filter_candidate_pages,
    group_by_page,
    log,
    resolve_dual_column_pages,
)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N text-bearing pages (for quick smoke tests). Default: all pages.")
    parser.add_argument("--pages", type=str, default=None, help="Only process text-bearing pages in this 1-based PDF page range, e.g. '80-140'. Takes precedence over --limit.")
    parser.add_argument("--skip-validation", action="store_true", help="Stop after table extraction, skip the OpenAI step.")
    args = parser.parse_args()

    assert PDF_PATH.exists(), f"PDF not found at {PDF_PATH.resolve()}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    t_start = time.time()

    log(f"Stage 1: classifying pages in {PDF_PATH.name}")
    t0 = time.time()
    text_pages, page_text = classify_pages(PDF_PATH)
    log(f"  {len(text_pages)} text-bearing page(s) found in {time.time() - t0:.1f}s")

    if args.pages:
        start, end = (int(x) for x in args.pages.split("-", 1))
        target_pages = [p for p in text_pages if start <= p <= end]
    elif args.limit is not None:
        target_pages = text_pages[: args.limit]
    else:
        target_pages = text_pages
    log(f"Running on {len(target_pages)} page(s)")

    log(f"Stage 2: extracting tables with pymupdf ({CPU_WORKERS} workers)")
    t0 = time.time()
    all_tables = extract_all_tables(PDF_PATH, target_pages)
    log(f"  {len(all_tables)} table candidate(s) found in {time.time() - t0:.1f}s")

    pages_grouped = group_by_page(all_tables)
    log(f"  {len(pages_grouped)} page(s) have at least one table candidate")

    pages_grouped = filter_candidate_pages(pages_grouped)
    log(f"  {len(pages_grouped)} page(s) kept after requiring a ruled-border hit "
        f"(lines_strict or lines) -- drops likely false positives from the looser text strategy")

    pages_grouped = resolve_dual_column_pages(PDF_PATH, pages_grouped, page_text)

    log("Stage 3: confidence-classifying pages (no LLM)")
    t0 = time.time()
    outline_index = build_pdf_outline_index(PDF_PATH)
    high_results, llm_pages, reason_counts = split_by_confidence(
        pages_grouped,
        page_text,
        pdf_path=PDF_PATH,
        outline_index=outline_index,
    )
    log(f"  {len(high_results)} page(s) auto-accepted (no LLM call), {len(llm_pages)} page(s) need OpenAI validation, in {time.time() - t0:.1f}s")
    for reason, count in sorted(reason_counts.items(), key=lambda kv: -kv[1]):
        log(f"    [llm bucket] {count}x: {reason}")

    validated_by_page: Dict[int, Dict[str, Any]] = dict(high_results)

    if args.skip_validation:
        log(f"Skipping OpenAI validation (--skip-validation) -- output only has the {len(high_results)} auto-accepted page(s).")
    else:
        log(f"Stage 4: validating/restructuring {len(llm_pages)} page(s) with OpenAI (batches of {BATCH_SIZE}, {OPENAI_WORKERS} workers)")
        t0 = time.time()
        llm_results = validate_all_pages_batched(llm_pages, page_text)
        log(f"  validated {len(llm_results)} page(s) in {time.time() - t0:.1f}s")
        validated_by_page.update(llm_results)
        missing = _llm_pages_missing_tables(llm_pages, llm_results)
        if missing:
            log(
                f"  LLM returned no tables for {len(missing)} page(s); "
                f"heuristic-accepting ruled-border extractions"
            )
            validated_by_page.update(
                heuristic_accept_pages(
                    missing,
                    page_text,
                    pdf_path=PDF_PATH,
                    outline_index=outline_index,
                    review_reason="llm_validation_failed_heuristic",
                )
            )

        _log_representative_examples(llm_results, high_results)

    validated_by_page = dict(sorted(validated_by_page.items()))
    out_path = OUTPUT_DIR / f"validated_tables_pages_1-{max(target_pages)}.json"
    with open(out_path, "w") as f:
        json.dump(validated_by_page, f, indent=2, default=str)
    log(f"Saved {len(validated_by_page)} page(s) to {out_path}")
    log(f"Total time: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
