"""
Robustness test harness for the PDF table extraction + AI classification
pipeline (sda_india_pdf_extraction.run_pipeline).

Run: python test_pdf_pipeline.py /path/to/file1.pdf [/path/to/file2.pdf ...]

For each PDF, runs the full pipeline and reports:
  - stage timings, page/table counts
  - LLM reliability: batch JSON-parse failures, per-page fallback failures
  - structural integrity: every row length == column count, no ungrounded
    Direction/Trend columns, no duplicate/placeholder column names surviving
    to output, non-empty titles
  - human_review_needed distribution by reason

Exits non-zero if any structural-integrity violation is found, so this can
be looped ("keep running until robust") to drive fixes.
"""
import io
import contextlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import sda_india_pdf_extraction as pipeline


def run_one(pdf_path: Path) -> dict:
    print(f"\n{'=' * 70}\n{pdf_path.name}\n{'=' * 70}")
    log_buf = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(log_buf):
        result = pipeline.run_pipeline(pdf_path)
    elapsed = time.time() - t0
    logs = log_buf.getvalue()
    print(logs[-4000:])  # tail of pipeline log for context

    batch_failures = len(re.findall(r"batch .* failed, falling back to per-page", logs))
    page_fallback_failures = len(re.findall(r"per-page fallback also failed", logs))

    n_pages = len(result)
    n_tables = 0
    high_conf = 0
    llm_conf = 0
    guard_fallback = 0
    review_reasons = Counter()
    structural_issues = []
    empty_titles = 0

    for page_num, page_result in result.items():
        for t in page_result.get("tables", []):
            n_tables += 1
            src = (t.get("extraction") or {}).get("confidence")
            if src == "high":
                high_conf += 1
            elif src == "alignment_guard_fallback":
                guard_fallback += 1
            elif src == "llm_validated":
                llm_conf += 1

            if not (t.get("title") or "").strip():
                empty_titles += 1

            if t.get("human_review_needed"):
                review_reasons[t.get("human_review_reason") or "unknown"] += 1

            cols = t.get("columns") or []
            ncol = len(cols)
            names = [c.get("name") for c in cols]
            if len(set(n for n in names if n)) != len([n for n in names if n]):
                structural_issues.append(f"page {page_num}: duplicate column names {names}")
            for i, row in enumerate(t.get("rows") or []):
                if len(row) != ncol:
                    structural_issues.append(
                        f"page {page_num} row {i}: len(row)={len(row)} != len(columns)={ncol}"
                    )
                    break  # one example per table is enough

            direction_cols = [n for n in names if n and re.search(r"direction|trend", str(n), re.I)]
            if direction_cols:
                flat_vals = {str(v).strip().lower() for row in (t.get("rows") or []) for v in row}
                bad_vals = flat_vals - {"up", "down", "none", ""}
                if bad_vals:
                    structural_issues.append(
                        f"page {page_num}: Direction/Trend column has non up/down values: {bad_vals}"
                    )

    print(f"\n-- summary for {pdf_path.name} --")
    print(f"  elapsed: {elapsed:.1f}s, pages_with_tables={n_pages}, tables={n_tables}")
    print(f"  source breakdown: high={high_conf}, llm_validated={llm_conf}, alignment_guard_fallback={guard_fallback}")
    print(f"  empty titles: {empty_titles}")
    print(f"  batch JSON/parse failures (fell back to per-page): {batch_failures}")
    print(f"  per-page fallback also failed: {page_fallback_failures}")
    print(f"  human_review_needed reasons: {dict(review_reasons)}")
    if structural_issues:
        print(f"  STRUCTURAL ISSUES ({len(structural_issues)}):")
        for issue in structural_issues[:20]:
            print(f"    - {issue}")
    else:
        print("  structural issues: none")

    return {
        "pdf": pdf_path.name,
        "elapsed": elapsed,
        "n_pages": n_pages,
        "n_tables": n_tables,
        "batch_failures": batch_failures,
        "page_fallback_failures": page_fallback_failures,
        "structural_issues": structural_issues,
        "empty_titles": empty_titles,
        "review_reasons": dict(review_reasons),
    }


def main():
    pdf_paths = [Path(p) for p in sys.argv[1:]]
    if not pdf_paths:
        print("usage: python test_pdf_pipeline.py file1.pdf [file2.pdf ...]")
        sys.exit(2)

    all_results = [run_one(p) for p in pdf_paths]

    print(f"\n{'=' * 70}\nOVERALL\n{'=' * 70}")
    total_bad = 0
    for r in all_results:
        bad = bool(r["structural_issues"]) or r["page_fallback_failures"] > 0
        total_bad += bad
        status = "FAIL" if bad else "OK"
        print(f"  [{status}] {r['pdf']}: {r['n_tables']} tables, "
              f"{len(r['structural_issues'])} structural issues, "
              f"{r['batch_failures']} batch-fallbacks, "
              f"{r['page_fallback_failures']} page-fallback-failures")

    with open("pdf_pipeline_test_report.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print("\nFull report: pdf_pipeline_test_report.json")

    sys.exit(1 if total_bad else 0)


if __name__ == "__main__":
    main()
