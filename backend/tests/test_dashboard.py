"""Dashboard upload-centric rows and file-type Source labels."""
from app.services.catalogue.dashboard import _infer_source_label
from app.api.routes.dashboard import _pdf_dashboard_row


def test_infer_source_label_file_types_only():
    assert _infer_source_label("report.pdf") == "PDF"
    assert _infer_source_label("workbook.xlsx") == "XLSX"
    assert _infer_source_label("export.csv") == "CSV"
    assert _infer_source_label("postgresql://localhost/db") == "SQL"
    # Descriptive / OCR junk must not leak into the Source column.
    assert _infer_source_label("Births and Deaths Report 2023") == "—"
    assert _infer_source_label("Maaiinn VViittaall Ilnnddiiccaat") == "—"
    assert _infer_source_label(None, fallback="—") == "—"
    # Prefer metadata workbook filename over prose data_source.
    assert _infer_source_label("meta.xlsx", "Births and Deaths Report 2023") == "XLSX"


def test_pdf_dashboard_row_stays_visible_after_metadata():
    job = {
        "job_id": "j1",
        "filename": "births_death_report_2023_cond.pdf",
        "status": "done",
        "percent": 100,
        "needs_review_count": 0,
        "table_count": 12,
    }
    row5 = _pdf_dashboard_row(job, "saved", 5)
    assert row5 is not None
    assert row5["name"] == "births_death_report_2023_cond.pdf"
    assert row5["source"] == "PDF"
    assert row5["status_key"] == "classification_review"
    assert "/console/grouping/j1" in row5["href"]

    row6 = _pdf_dashboard_row(job, "saved", 6)
    assert row6 is not None
    assert row6["status_key"] == "published"
    assert row6["href"] == "/catalogue"
