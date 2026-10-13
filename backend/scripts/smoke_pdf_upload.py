"""Smoke: PreValidationInput + POST /api/upload for a small Testing files PDF."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv

load_dotenv(_BACKEND / ".env")
os.environ.setdefault("JWT_SECRET", "local-smoke-test-secret")

from app.core import security as _auth
from app.services.extraction.pdf import extract_pdf_to_pre_input

PDF = _BACKEND.parent / "Testing files" / "SDA_INDIA_222-224.pdf"


def main_smoke() -> None:
    if not PDF.is_file():
        raise SystemExit(f"Missing fixture: {PDF}")

    pre = extract_pdf_to_pre_input(PDF)
    assert "pages_grouped" in pre and "unit_context" in pre
    assert pre.get("source_type") == "pdf"
    n_cands = sum(len(v) for v in pre["pages_grouped"].values())
    print(f"PreValidationInput: {len(pre['pages_grouped'])} unit(s), {n_cands} candidate(s)")
    assert n_cands >= 1

    from fastapi.testclient import TestClient

    import main  # noqa: WPS433 — import after PyMuPDF extract (macOS spawn)

    token = _auth.create_token("pipeline-test@example.gov.in")
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(main.app) as client:
        with PDF.open("rb") as f:
            resp = client.post(
                "/api/upload",
                headers=headers,
                data={"type": "pdf"},
                files={"file": (PDF.name, f, "application/pdf")},
            )
        print("POST /api/upload", resp.status_code, resp.json())
        resp.raise_for_status()
        job_id = resp.json()["job_id"]

        for _ in range(180):
            st = client.get(f"/api/pdf/jobs/{job_id}", headers=headers)
            body = st.json()
            status = body.get("status")
            prog = body.get("progress") or {}
            if status != "running":
                print("job status:", status, prog.get("message", ""))
            if status == "done":
                break
            if status == "error":
                raise SystemExit(f"Job failed: {body}")
            time.sleep(1)
        else:
            raise SystemExit("Job timed out")

        result = client.get(f"/api/pdf/jobs/{job_id}/result", headers=headers).json()
        tables = result.get("tables") or []
        print(f"Job result: {len(tables)} validated table(s) from {result.get('filename')}")
        n_tables = len(tables)
        assert n_tables >= 1
    print("OK")


if __name__ == "__main__":
    main_smoke()
