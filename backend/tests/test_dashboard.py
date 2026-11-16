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


def test_pdf_dashboard_row_default_pending_is_preview_not_failed():
    """DB default grouping_status='pending' must not imply Grouping / failure.

    Excel/CSV jobs often have tables in the extraction result before Continue
    persists pdf_tables — table_count stays 0 while Preview still has tables.
    """
    preview = {
        "job_id": "j-xlsx",
        "filename": "D1-D9-Final (1) (1).xlsx",
        "status": "done",
        "percent": 100,
        "needs_review_count": 0,
        "table_count": 0,
        # Result still has tables; only pdf_tables is empty pre-Continue.
        "extracted_table_count": 12,
    }
    # grouping_status defaults to 'pending' on insert; pipeline_step unset.
    row = _pdf_dashboard_row(preview, "pending", None)
    assert row is not None
    assert row["status_key"] == "table_review"
    assert row["status"] == "Preview"
    assert row["href"] == "/console/review/j-xlsx"

    empty = {
        **preview,
        "job_id": "j-empty",
        "extracted_table_count": 0,
    }
    row_empty = _pdf_dashboard_row(empty, "pending", None)
    assert row_empty is not None
    assert row_empty["status_key"] == "failed"
    assert row_empty["status"] == "No tables extracted"
    assert row_empty["href"] == "/console/processing/j-empty"

    failed = {
        **preview,
        "job_id": "j-failed",
        "status": "failed",
        "message": "No tables were extracted — upload another file or try again",
        "extracted_table_count": 0,
    }
    row_f = _pdf_dashboard_row(failed, "pending", None)
    assert row_f is not None
    assert row_f["status_key"] == "failed"
    assert row_f["status"] == "No tables extracted"


def test_pdf_dashboard_row_persisted_tables_infer_grouping():
    job = {
        "job_id": "j-grouped",
        "filename": "districts.xlsx",
        "status": "done",
        "percent": 100,
        "needs_review_count": 0,
        "table_count": 4,
    }
    row = _pdf_dashboard_row(job, "pending", None)
    assert row is not None
    assert row["status_key"] == "harmonisation"
    assert row["href"] == "/console/grouping/j-grouped?step=3"


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
    # Open the step shown on the Dashboard (Preview still via stage rail).
    assert row5["href"] == "/console/grouping/j1?step=5"

    row4 = _pdf_dashboard_row(job, "saved", 4)
    assert row4 is not None
    assert row4["status_key"] == "metadata_review"
    assert row4["href"] == "/console/grouping/j1?step=4"

    row3 = _pdf_dashboard_row(job, "pending", 3)
    assert row3 is not None
    assert row3["status_key"] == "harmonisation"
    assert row3["href"] == "/console/grouping/j1?step=3"

    row2 = _pdf_dashboard_row(job, None, 2)
    assert row2 is not None
    assert row2["href"] == "/console/review/j1"

    xlsx_job = {**job, "job_id": "j2", "filename": "districts.xlsx"}
    row_xlsx = _pdf_dashboard_row(xlsx_job, "pending", 3)
    assert row_xlsx is not None
    assert row_xlsx["source"] == "XLSX"
    assert row_xlsx["href"] == "/console/grouping/j2?step=3"

    row6 = _pdf_dashboard_row(job, "saved", 6)
    assert row6 is not None
    assert row6["status_key"] == "harmonisation_review"
    assert row6["status"] == "Harmonisation"
    assert row6["href"] == "/console/grouping/j1?step=6"

    row7 = _pdf_dashboard_row(job, "saved", 7)
    assert row7 is not None
    assert row7["status_key"] == "published"
    assert row7["href"] == "/catalogue"
