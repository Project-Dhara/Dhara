"""OpenAPI must expose editable JSON bodies for /docs Try it out."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _resolve(schema: dict, content: dict) -> dict:
    if "$ref" in content:
        name = content["$ref"].rsplit("/", 1)[-1]
        return schema["components"]["schemas"][name]
    return content


def test_login_and_signup_have_json_body_fields():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert "BearerAuth" in schema["components"]["securitySchemes"]

    for path in ("/api/login", "/api/signup"):
        post = schema["paths"][path]["post"]
        content = post["requestBody"]["content"]["application/json"]["schema"]
        props = _resolve(schema, content)["properties"]
        assert "email" in props
        assert "password" in props


def test_llm_key_and_kyds_post_have_bodies():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    llm = _resolve(
        schema,
        schema["paths"]["/api/llm-key"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"],
    )
    assert "api_key" in llm["properties"]

    kyds = _resolve(
        schema,
        schema["paths"]["/api/kyds"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"],
    )
    assert "responses" in kyds["properties"]


def test_pdf_and_catalogue_json_routes_have_request_bodies():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    expected = {
        "/api/pdf/jobs/{job_id}/tables/delete": ("post", "table_ids"),
        "/api/pdf/jobs/{job_id}/tables/merge": ("post", "table_ids"),
        "/api/pdf/jobs/{job_id}/tables/ai-search": ("post", "prompt"),
        "/api/pdf/jobs/{job_id}/persist-approved": ("post", "tables"),
        "/api/pdf/jobs/{job_id}/grouping/propose": ("post", "reindex"),
        "/api/pdf/jobs/{job_id}/grouping": ("put", "groups"),
        "/api/catalogue/sql-extract": ("post", "database_url"),
        "/api/catalogue/fill-group-metadata": ("post", "groups"),
        "/api/catalogue/fill-definitions": ("post", "columns"),
        "/api/catalogue/match-nco": ("post", "values"),
        "/api/catalogue/nco-aliases": ("post", "aliases"),
        "/api/table-metadata": ("post", "title"),
        "/api/catalogue/metadata-groups/{metadata_id}/classifications": (
            "patch",
            "codes",
        ),
    }
    for path, (method, field) in expected.items():
        op = schema["paths"][path][method]
        content = op["requestBody"]["content"]["application/json"]["schema"]
        props = _resolve(schema, content).get("properties") or {}
        assert field in props, f"{path} missing {field} in {props}"


def test_persist_approved_without_body_is_not_unprocessable():
    """Grouping UI calls persist-approved with an empty POST body."""
    with TestClient(app) as client:
        r = client.post("/api/pdf/jobs/does-not-matter/persist-approved")
    # Auth fires first; must not be a schema 422 from a missing body.
    assert r.status_code != 422
