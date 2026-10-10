# Stage 11 — Access layer (Catalogue / API / MCP)

**Status:** Catalogue UI + authenticated REST `/api/v1` + HTTP `/mcp` + stdio MCP live

## Purpose

Expose **only approved, authorised** data for discovery and consumption.

```text
Catalogue → API → MCP (agents)
```

## Live today

| Surface | Behaviour |
|---------|-----------|
| **Catalogue UI** | Browse **published groups (releases)**; download ZIP of all tables + classifications |
| **REST API (v1)** | JWT-protected query routes under `/api/v1` (tables still addressable by dataset id) |
| **MCP (HTTP)** | Streamable HTTP at **`/mcp`** on the same deploy (Bearer JWT by default) |
| **MCP (stdio)** | `python -m app.mcp` from `backend/` |
| **des-website** | External consumer of the same catalogue DB |

### Catalogue group download

`GET /api/catalogue/groups/{metadata_id}/download` returns a ZIP of the
group’s tables only. Each table has `*_Code` and `*_Definition` columns
appended after every classified / harmonised dimension (looked up from the
steward code lists).

```text
Live_births.xlsx   — State | Occupation | Occupation_Code | Occupation_Definition | …
Still_births.xlsx
```

List releases with `GET /api/catalogue/groups` (one card per `metadata_groups` row).
Table-level listing remains at `GET /api/catalogue/datasets` for API consumers.

## REST (`/api/v1`)

All routes require the same Bearer JWT as the Console.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1` | Access API index |
| GET | `/api/v1/datasets` | Search/list (`q`, `metadata_id`, `limit`, `offset`) |
| GET | `/api/v1/datasets/{dataset_id}` | Dataset metadata |
| GET | `/api/v1/datasets/{dataset_id}/rows` | Paginated rows (`limit`, `offset`, optional `column` + `equals`/`contains`) |

Shared helpers live in `backend/catalogue/query.py` (also used by the MCP server).

Example:

```bash
TOKEN=…   # from POST /api/login
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/datasets?q=births&limit=10"
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/datasets/DS_EXAMPLE/rows?limit=50&column=State&contains=Delhi"
```

## MCP tools

### Remote HTTP (deployed)

Same host as the app — copy from Catalogue → **MCP endpoint**:

```text
https://<your-host>/mcp
```

Auth (default): open for published catalogue reads. Set `MCP_HTTP_AUTH=jwt` to require
`Authorization: Bearer <JWT from POST /api/login>`, or use a long-lived `MCP_AUTH_TOKEN`.

Cursor / Claude / any remote MCP client (URL only):

```json
{
  "mcpServers": {
    "dhara-catalogue": {
      "url": "https://<your-host>/mcp"
    }
  }
}
```

| Tool | Maps to |
|------|---------|
| `search_datasets` | search/list datasets |
| `get_metadata` | one dataset card |
| `get_table` | paginated rows + optional column filter |

### Local stdio

From `backend/` (with `DATABASE_URL` / `.env` loaded):

```bash
cd backend && python -m app.mcp
```

```json
{
  "mcpServers": {
    "dhara-catalogue": {
      "command": "python",
      "args": ["-m", "app.mcp"],
      "cwd": "/absolute/path/to/dhara-poc/backend"
    }
  }
}
```

## Design

```text
                    metadata_groups / datasets
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Catalogue UI    Versioned REST     MCP server
                         (scoped JWT)     (tool schema)
```

Access policy should honour steward approval state — unpublished or
soft-deleted work must not appear on public surfaces. Row filters are
equality / substring on a single JSONB key only (no free-form SQL).
